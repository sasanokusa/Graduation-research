#!/usr/bin/env bash
set -euo pipefail

# observe_runs.sh
#
# 目的:
#   reset -> break -> agent実行 -> results JSON回収 -> summary.csv追記
#   を自動で回す観測スクリプト
#
# 例:
#   chmod +x observe_runs.sh
#   ./observe_runs.sh all --worker llm --prompt-mode blind --repeat 3 --python ./.venv/bin/python
#   ./observe_runs.sh d f h --worker llm --prompt-mode blind
#   ./observe_runs.sh e --worker llm --keep-failed-env
#   ./observe_runs.sh a b c --worker mock --scenario-mode forced
#
# 前提:
#   - カレントディレクトリがリポジトリルート
#   - ./reset.sh, ./break.sh, agent.py, results/ が存在する
#   - Python が使える
#
# 備考:
#   - デフォルトでは auto mode で agent を実行
#   - --scenario-mode forced を付けると各シナリオを明示指定して実行
#   - observations/<timestamp>/ 以下に run ごとのログと summary.csv を保存

SCENARIOS_DEFAULT=(a b c d e f g h i k l)

WORKER="llm"
PROMPT_MODE="blind"
REPEAT=1
PYTHON_BIN="python"
KEEP_FAILED_ENV=0
SCENARIO_MODE="auto"   # auto | forced
OBS_ROOT="observations"
RUN_LABEL=""
SLEEP_AFTER_BREAK="0"

usage() {
  cat <<'EOF'
使い方:
  ./observe_runs.sh all [options]
  ./observe_runs.sh a b c [options]

オプション:
  --worker <llm|mock>         worker種別 (default: llm)
  --prompt-mode <mode>        prompt mode (default: blind)
  --repeat <N>                各シナリオの反復回数 (default: 1)
  --python <path>             使用するPython実行ファイル (default: python)
  --keep-failed-env           失敗時に reset せず環境を残す
  --scenario-mode <auto|forced>
                              auto:  agent.py に --scenario を渡さない
                              forced: agent.py に --scenario <id> を渡す
  --label <text>              観測ディレクトリ名に付与するラベル
  --sleep-after-break <sec>   break後に待つ秒数 (default: 0)
  -h, --help                  このヘルプを表示

例:
  ./observe_runs.sh all --worker llm --prompt-mode blind --repeat 3 --python ./.venv/bin/python
  ./observe_runs.sh d f h --worker llm --prompt-mode blind
  ./observe_runs.sh e --worker llm --keep-failed-env
  ./observe_runs.sh a b c --worker mock --scenario-mode forced
EOF
}

die() {
  echo "[observe] ERROR: $*" >&2
  exit 1
}

need_file() {
  [[ -e "$1" ]] || die "必要ファイルが見つかりません: $1"
}

timestamp_utc() {
  date -u +"%Y%m%dT%H%M%SZ"
}

join_by() {
  local IFS="$1"
  shift
  echo "$*"
}

escape_csv() {
  # CSV用にダブルクォートで包み、内部の " を "" にする
  local s="${1:-}"
  s="${s//\"/\"\"}"
  printf '"%s"' "$s"
}

parse_args() {
  local scenarios=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --worker)
        shift
        [[ $# -gt 0 ]] || die "--worker の値が必要です"
        WORKER="$1"
        ;;
      --prompt-mode)
        shift
        [[ $# -gt 0 ]] || die "--prompt-mode の値が必要です"
        PROMPT_MODE="$1"
        ;;
      --repeat)
        shift
        [[ $# -gt 0 ]] || die "--repeat の値が必要です"
        REPEAT="$1"
        ;;
      --python)
        shift
        [[ $# -gt 0 ]] || die "--python の値が必要です"
        PYTHON_BIN="$1"
        ;;
      --keep-failed-env)
        KEEP_FAILED_ENV=1
        ;;
      --scenario-mode)
        shift
        [[ $# -gt 0 ]] || die "--scenario-mode の値が必要です"
        SCENARIO_MODE="$1"
        ;;
      --label)
        shift
        [[ $# -gt 0 ]] || die "--label の値が必要です"
        RUN_LABEL="$1"
        ;;
      --sleep-after-break)
        shift
        [[ $# -gt 0 ]] || die "--sleep-after-break の値が必要です"
        SLEEP_AFTER_BREAK="$1"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      all)
        scenarios=("${SCENARIOS_DEFAULT[@]}")
        ;;
      [a-z]|[a-z][a-z]*)
        scenarios+=("$1")
        ;;
      *)
        die "不明な引数です: $1"
        ;;
    esac
    shift
  done

  if [[ "${#scenarios[@]}" -eq 0 ]]; then
    scenarios=("${SCENARIOS_DEFAULT[@]}")
  fi

  # 重複除去しつつ順序保持
  local uniq=()
  local seen=" "
  local s
  for s in "${scenarios[@]}"; do
    if [[ "$seen" != *" $s "* ]]; then
      uniq+=("$s")
      seen+="${s} "
    fi
  done

  SCENARIOS=("${uniq[@]}")
}

require_prereqs() {
  need_file "./reset.sh"
  need_file "./break.sh"
  need_file "./agent.py"
  [[ -d "./results" ]] || mkdir -p ./results
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python実行ファイルが見つかりません: $PYTHON_BIN"
  command -v bash >/dev/null 2>&1 || die "bash が必要です"

  [[ "$SCENARIO_MODE" == "auto" || "$SCENARIO_MODE" == "forced" ]] || die "--scenario-mode は auto か forced を指定してください"
  [[ "$WORKER" == "llm" || "$WORKER" == "mock" ]] || die "--worker は llm か mock を指定してください"
  [[ "$REPEAT" =~ ^[0-9]+$ ]] || die "--repeat は整数を指定してください"
}

make_obs_dir() {
  local ts
  ts="$(timestamp_utc)"
  local suffix=""
  if [[ -n "$RUN_LABEL" ]]; then
    suffix="_${RUN_LABEL}"
  fi
  OBS_DIR="${OBS_ROOT}/${ts}${suffix}"
  mkdir -p "$OBS_DIR"
  mkdir -p "$OBS_DIR/runs"

  SUMMARY_CSV="$OBS_DIR/summary.csv"
  cat > "$SUMMARY_CSV" <<'EOF'
run_id,started_at_utc,scenario,repeat_index,worker,prompt_mode,scenario_mode,break_ok,agent_exit_code,final_status,detected_fault_class,elapsed_seconds,additional_observation_used,result_json,planner_error_type,planner_error_stage,planner_retry_count,planner_transport_failure,planner_reasoning_failure,planner_fallback_used,planner_fallback_type,precheck_ok,postcheck_ok,planner_summary,triage_summary
EOF
}

find_latest_result_json() {
  local latest
  latest="$(find ./results -maxdepth 1 -type f -name '*.json' -print0 2>/dev/null | xargs -0 ls -1t 2>/dev/null | head -n 1 || true)"
  if [[ -n "$latest" ]]; then
    printf '%s\n' "$latest"
  fi
}

extract_result_path_from_log() {
  local log_file="$1"
  local path=""
  path="$(grep -E '^result_path:' "$log_file" | tail -n 1 | sed -E 's/^result_path:[[:space:]]*//' || true)"
  if [[ -n "$path" && -f "$path" ]]; then
    printf '%s\n' "$path"
  fi
}

json_field() {
  local json_file="$1"
  local expr="$2"
  "$PYTHON_BIN" - "$json_file" "$expr" <<'PY'
import json, sys
path = sys.argv[1]
expr = sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

# ごく簡易なドット記法
cur = data
if expr:
    for part in expr.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            cur = None
            break

if cur is None:
    print("")
elif isinstance(cur, bool):
    print("true" if cur else "false")
elif isinstance(cur, (int, float)):
    print(cur)
elif isinstance(cur, str):
    print(cur.replace("\n", " ").strip())
else:
    print(json.dumps(cur, ensure_ascii=False))
PY
}

append_summary_row() {
  local run_id="$1"
  local started_at="$2"
  local scenario="$3"
  local repeat_index="$4"
  local break_ok="$5"
  local agent_exit_code="$6"
  local result_json="$7"

  local final_status=""
  local detected_fault_class=""
  local elapsed_seconds=""
  local additional_observation_used=""
  local planner_error_type=""
  local planner_error_stage=""
  local planner_retry_count=""
  local planner_transport_failure=""
  local planner_reasoning_failure=""
  local planner_fallback_used=""
  local planner_fallback_type=""
  local precheck_ok=""
  local postcheck_ok=""
  local planner_summary=""
  local triage_summary=""

  if [[ -n "$result_json" && -f "$result_json" ]]; then
    final_status="$(json_field "$result_json" "final_status")"
    detected_fault_class="$(json_field "$result_json" "detected_fault_class")"
    elapsed_seconds="$(json_field "$result_json" "elapsed_seconds")"
    additional_observation_used="$(json_field "$result_json" "additional_observation_used")"
    planner_error_type="$(json_field "$result_json" "planner_error_type")"
    planner_error_stage="$(json_field "$result_json" "planner_error_stage")"
    planner_retry_count="$(json_field "$result_json" "planner_retry_count")"
    planner_transport_failure="$(json_field "$result_json" "planner_transport_failure")"
    planner_reasoning_failure="$(json_field "$result_json" "planner_reasoning_failure")"
    planner_fallback_used="$(json_field "$result_json" "planner_fallback_used")"
    planner_fallback_type="$(json_field "$result_json" "planner_fallback_type")"
    precheck_ok="$(json_field "$result_json" "verifier_precheck_result.ok")"
    postcheck_ok="$(json_field "$result_json" "verifier_postcheck_result.ok")"
    planner_summary="$(json_field "$result_json" "planner_summary")"
    triage_summary="$(json_field "$result_json" "triage_summary")"
  fi

  {
    escape_csv "$run_id"; printf ","
    escape_csv "$started_at"; printf ","
    escape_csv "$scenario"; printf ","
    escape_csv "$repeat_index"; printf ","
    escape_csv "$WORKER"; printf ","
    escape_csv "$PROMPT_MODE"; printf ","
    escape_csv "$SCENARIO_MODE"; printf ","
    escape_csv "$break_ok"; printf ","
    escape_csv "$agent_exit_code"; printf ","
    escape_csv "$final_status"; printf ","
    escape_csv "$detected_fault_class"; printf ","
    escape_csv "$elapsed_seconds"; printf ","
    escape_csv "$additional_observation_used"; printf ","
    escape_csv "$result_json"; printf ","
    escape_csv "$planner_error_type"; printf ","
    escape_csv "$planner_error_stage"; printf ","
    escape_csv "$planner_retry_count"; printf ","
    escape_csv "$planner_transport_failure"; printf ","
    escape_csv "$planner_reasoning_failure"; printf ","
    escape_csv "$planner_fallback_used"; printf ","
    escape_csv "$planner_fallback_type"; printf ","
    escape_csv "$precheck_ok"; printf ","
    escape_csv "$postcheck_ok"; printf ","
    escape_csv "$planner_summary"; printf ","
    escape_csv "$triage_summary"; printf "\n"
  } >> "$SUMMARY_CSV"
}

run_one() {
  local scenario="$1"
  local repeat_index="$2"

  local run_id
  run_id="$(printf "%s_%02d_%s" "$scenario" "$repeat_index" "$(timestamp_utc)")"

  local run_dir="$OBS_DIR/runs/$run_id"
  mkdir -p "$run_dir"

  local started_at
  started_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  echo
  echo "=================================================="
  echo "[observe] scenario=$scenario repeat=$repeat_index run_id=$run_id"
  echo "=================================================="

  echo "[observe] reset..."
  ./reset.sh >"$run_dir/reset.log" 2>&1 || {
    echo "[observe] reset failed. see $run_dir/reset.log"
    append_summary_row "$run_id" "$started_at" "$scenario" "$repeat_index" "false" "reset_failed" ""
    return 1
  }

  echo "[observe] break..."
  local break_ok="true"
  if ./break.sh "$scenario" >"$run_dir/break.log" 2>&1; then
    :
  else
    break_ok="false"
    echo "[observe] break failed. see $run_dir/break.log"
    append_summary_row "$run_id" "$started_at" "$scenario" "$repeat_index" "$break_ok" "break_failed" ""
    return 1
  fi

  if [[ "$SLEEP_AFTER_BREAK" != "0" ]]; then
    echo "[observe] sleeping ${SLEEP_AFTER_BREAK}s after break..."
    sleep "$SLEEP_AFTER_BREAK"
  fi

  local before_latest=""
  before_latest="$(find_latest_result_json || true)"

  echo "[observe] agent..."
  local agent_cmd=("$PYTHON_BIN" "agent.py" "--worker" "$WORKER" "--prompt-mode" "$PROMPT_MODE")
  if [[ "$SCENARIO_MODE" == "forced" ]]; then
    agent_cmd+=("--scenario" "$scenario")
  fi

  printf '[observe] command:' | tee "$run_dir/agent.command.txt" >/dev/null
  printf ' %q' "${agent_cmd[@]}" | tee -a "$run_dir/agent.command.txt" >/dev/null
  printf '\n' | tee -a "$run_dir/agent.command.txt" >/dev/null

  set +e
  "${agent_cmd[@]}" >"$run_dir/agent.log" 2>&1
  local agent_exit_code=$?
  set -e

  local result_json=""
  result_json="$(extract_result_path_from_log "$run_dir/agent.log" || true)"

  if [[ -z "$result_json" ]]; then
    local after_latest=""
    after_latest="$(find_latest_result_json || true)"
    if [[ -n "$after_latest" && "$after_latest" != "$before_latest" ]]; then
      result_json="$after_latest"
    fi
  fi

  if [[ -n "$result_json" && -f "$result_json" ]]; then
    cp "$result_json" "$run_dir/"
    result_json="$run_dir/$(basename "$result_json")"
  else
    result_json=""
  fi

  append_summary_row "$run_id" "$started_at" "$scenario" "$repeat_index" "$break_ok" "$agent_exit_code" "$result_json"

  if [[ -n "$result_json" && -f "$result_json" ]]; then
    local final_status
    final_status="$(json_field "$result_json" "final_status")"
    local detected_fault_class
    detected_fault_class="$(json_field "$result_json" "detected_fault_class")"
    local elapsed_seconds
    elapsed_seconds="$(json_field "$result_json" "elapsed_seconds")"

    echo "[observe] final_status=${final_status:-unknown} detected_fault_class=${detected_fault_class:-} elapsed=${elapsed_seconds:-}"
    echo "[observe] result_json=$result_json"

    if [[ "$KEEP_FAILED_ENV" -eq 1 && "$final_status" != "success" ]]; then
      echo "[observe] failed env is kept as requested."
    else
      echo "[observe] cleanup reset..."
      ./reset.sh >"$run_dir/post_reset.log" 2>&1 || true
    fi
  else
    echo "[observe] result json not found. see $run_dir/agent.log"
    if [[ "$KEEP_FAILED_ENV" -ne 1 ]]; then
      ./reset.sh >"$run_dir/post_reset.log" 2>&1 || true
    fi
  fi
}

print_final_hint() {
  cat <<EOF

[observe] 完了
[observe] summary: $SUMMARY_CSV
[observe] runs dir: $OBS_DIR/runs

[observe] 例:
  cat "$SUMMARY_CSV"
  column -s, -t < "$SUMMARY_CSV" | less -S
EOF
}

main() {
  parse_args "$@"
  require_prereqs
  make_obs_dir

  echo "[observe] scenarios: $(join_by ' ' "${SCENARIOS[@]}")"
  echo "[observe] worker=$WORKER prompt_mode=$PROMPT_MODE repeat=$REPEAT scenario_mode=$SCENARIO_MODE python=$PYTHON_BIN"
  echo "[observe] output=$OBS_DIR"

  local scenario
  local i
  for scenario in "${SCENARIOS[@]}"; do
    for (( i=1; i<=REPEAT; i++ )); do
      run_one "$scenario" "$i" || true
    done
  done

  print_final_hint
}

main "$@"

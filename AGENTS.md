# Agent Experiment Guide

このファイルは、このリポジトリで実験を再開・実行するエージェント向けの運用手順である。別セッション、別モデル、別の日付で作業しても、同じ前提と公平性で実験できることを目的にする。

## Repository Context

このリポジトリは、Docker Compose で構成された障害注入環境に対して、LLM エージェントが安全に原因推定、追加観測、修正、検証、必要ならロールバックを行えるかを調べる卒業研究用の実験基盤である。

主要な実行系:

- `agent.py`: 単独エージェントの one-shot baseline
- `self_critique_agent.py`: 自己反省ループ baseline
- `multi_agent.py`: triage / planner / reviewer / judge / worker / sensor を含む multi-agent baseline
- `observe_runs.sh`: `reset -> break -> agent run -> collect results -> summary.csv` を行う観測スクリプト
- `aggregate_observations.py`: `summary.csv` の成功率や失敗分類を集計する
- `aggregate_hypothesis_metrics.py`: 仮説遷移ログを集計する

研究上の重要テーマは、単なる成功率だけではなく、誤仮説の固着、追加観測での修正、レビューや判定による危険な修正の抑制、ロールバック、安全制約の影響を比較することである。

## Non-Negotiable Fairness Rules

実験条件の公平性を崩してはいけない。特に以下は守る。

1. 隠れた正解情報を planner / reviewer / judge / worker に与えない。
2. シナリオ固有の答え、既知の壊し方、期待される修正内容をプロンプトに混ぜない。
3. 比較実験では、観測可能な情報、安全制約、prompt mode、scenario mode、最大ターン数、追加観測上限を揃える。
4. 役割分担やモデル差を調べる実験だけは、その変数だけを明示的に変える。
5. 粗い置換は禁止する。特にコードファイルへの `replace_text` は、観測済み snippet に見えている十分な文脈付き `old_text` を使う。
6. `itemz` のような単一トークンだけをコード全体で置換する修正は禁止する。エージェントは明確な観測根拠を持って修正する。
7. `.env` を実験条件変更のために編集しない。モデルや provider は `env ... ./observe_runs.sh ...` の一時環境変数で指定する。
8. `observations/` と `results/` を削除しない。中断時も観測ディレクトリと pending command を記録する。
9. 既存の未コミット変更を勝手に戻さない。作業前に `git status --short` を確認する。
10. ユーザーが「ここで止めて」と言った場合、新しい条件を開始しない。実行中の `observe_runs.sh` が終わったら停止し、次に実行すべき command を報告する。

## Standard Preflight

実験前にリポジトリルートで確認する。

```bash
git status --short
docker compose version
docker info >/dev/null
```

コードを変更した場合は、実験前に可能な限り以下を実行する。

```bash
./check.sh
```

API key の値を表示してはいけない。provider や model の設定だけを確認したい場合は、secret の値を出さない方法を使う。

```bash
grep -E '^(PLANNER|REVIEWER|JUDGE|TRIAGE)_(PROVIDER|MODEL)=' .env || true
```

Docker が止まっている場合は、実験を開始せずユーザーに知らせる。起動後に再開する。

## Experiment State As Of 2026-05-20

Experiment 1 は、公平化した条件で one-shot / self-critique / reviewer-only / reviewer+judge を比較する実験である。対象シナリオは `m n o r u v w x`。

共通条件:

- `PLANNER_MODEL=gpt-5.4`
- `--worker llm`
- `--prompt-mode blind`
- `--scenario-mode forced`
- `--repeat 1`
- `MULTI_AGENT_MAX_TURNS=5`
- `MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3`
- コード修正時は観測済み snippet に根拠を持つ文脈付き置換だけを許可

完了済み:

- Experiment 1-A one-shot: `observations/20260519T044659Z_controlled_oneshot_gpt54_once/summary.csv`
- Experiment 1-B self-critique: `observations/20260519T051414Z_controlled_selfcritique_gpt54_once/summary.csv`
- Experiment 1-C reviewer-only: `observations/20260519T054356Z_controlled_reviewer_only_gpt54_once/summary.csv`

未実行:

- Experiment 1-D reviewer+judge

ユーザーは電池都合で reviewer-only 完了後に一旦停止を希望した。次に実験を続ける場合は、Experiment 1-D から再開する。

## Experiment 1-D Command

reviewer+judge 条件を実行する場合の command:

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  MULTI_AGENT_JUDGE_MODE=enabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 1 \
  --python ./.venv/bin/python \
  --label controlled_multi_gpt54_once
```

## Experiment 2 Draft

Experiment 2 は multi-agent の役割別モデル割り当てを調べるドラフトである。

役割:

- planner: `gpt-5.4`
- reviewer: Claude
- judge: Claude
- triage: Gemini
- observer/sensor: deterministic `sensor_node`。現状のコードでは Gemini は sensor ではなく triage に割り当てる。

draft command:

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=anthropic \
  REVIEWER_MODEL=claude-sonnet-4-6 \
  JUDGE_PROVIDER=anthropic \
  JUDGE_MODEL=claude-sonnet-4-6 \
  TRIAGE_PROVIDER=google \
  TRIAGE_MODEL=gemini-3-flash-preview \
  MULTI_AGENT_JUDGE_MODE=enabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 1 \
  --python ./.venv/bin/python \
  --label experiment2_role_split_multi_gpt54_planner_claude_review_judge_gemini_triage_once
```

Experiment 2 はドラフトであり、実行前にユーザーのレビューを受ける。

## Common Aggregation Commands

単一 run の概要を見る。

```bash
./.venv/bin/python aggregate_observations.py \
  observations/<run>/summary.csv \
  --group-by scenario \
  --show-overall \
  --show-failure-breakdown
```

仮説遷移メトリクスを CSV 化する。

```bash
./.venv/bin/python aggregate_hypothesis_metrics.py \
  observations/<run>/summary.csv \
  --output observations/<run>/hypothesis_metrics.csv
```

複数条件を比較する場合は、各 `summary.csv` に対して同じ集計を実行し、条件名、成功率、失敗分類、空プラン率、追加観測利用、仮説変化率を同じ表に並べる。既存 script が足りない場合だけ、比較用 helper を追加する。

## What To Inspect In Results

単に `final_status` だけを見ない。少なくとも以下を確認する。

- `final_status`
- `planner_error_type`
- 空プランまたは no-op の発生
- `precheck_ok` と `postcheck_ok`
- `additional_observation_count` または追加観測に相当する列
- `planner_summary`
- `detected_fault_class`
- `baseline_condition`
- result JSON 内の `hypothesis_log`
- reviewer / judge の判断履歴
- worker action の `replace_text.old_text` が観測済み snippet に基づいているか
- token usage と elapsed time

自己反省ループが弱く見える場合でも、成功率だけで結論しない。空プラン、観測不足、誤仮説固着、安全制約による拒否、postcheck failure を分けて読む。

## Reporting

実験後の Markdown レポートは `docs/reports/` に置く。

Wiki に含める場合は以下も更新する。

- `docs/wiki/_build.sh`
- `docs/wiki/_template.html`
- `docs/wiki/index.html`
- 必要なら `docs/wiki/_link_map.sed`

Wiki HTML を生成する。

```bash
docs/wiki/_build.sh
```

レポートには最低限以下を書く。

- 実験目的
- 比較条件
- 実行日時と観測ディレクトリ
- 実行 command
- シナリオ別結果
- 失敗分類
- 空プランや追加観測の挙動
- 公平性確認
- 解釈と次の実験案

## Interruption Protocol

実験中断や電池都合の停止が起きた場合:

1. 実行中の command が終わったか確認する。
2. 新しい条件は開始しない。
3. 完了した `observations/<run>/summary.csv` を記録する。
4. 未実行の条件と再開 command を記録する。
5. 結果をまだ解釈しきれていない場合は、その旨を明記する。

途中で Docker や API の問題が起きた場合は、該当 run を成功率比較に混ぜる前に、transport failure / environment failure として分ける。

## Editing Guidance For Future Agents

実験コードを修正する場合:

- まず関連テストを読む。
- 変更範囲を最小化する。
- user の未コミット変更を戻さない。
- `apply_patch` など差分が明確に残る方法で編集する。
- 安全制約を緩める場合は、研究目的と公平性への影響を明記してユーザー確認を取る。
- reviewer-only と reviewer+judge の比較では、judge 有無以外の条件を変えない。

このファイル自体を更新した場合は、どの実験状態が新しくなったのかを最終報告で明示する。

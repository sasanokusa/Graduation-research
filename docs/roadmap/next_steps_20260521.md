# 2026-05-21 次のステップ計画

作成日: 2026-05-21
基礎資料: [`../current_status_20260508.md`](../current_status_20260508.md), [`implementation_roadmap_revised_20260415.md`](implementation_roadmap_revised_20260415.md), [`../reports/controlled_gpt54_fairness_experiment_20260520.md`](../reports/controlled_gpt54_fairness_experiment_20260520.md), [`../reports/safety_metrics_report.md`](../reports/safety_metrics_report.md)

## 0. 状況確認

- 中間発表: 夏頃
- 最終発表 / 卒論提出: 2027 年 2 月後半
- 残期間: 約 9 ヶ月 (中間発表まで 2-3 ヶ月、その後 6-7 ヶ月)

機能実装は卒論の核としてほぼ揃っており、ここからは比較実験を厚くして卒論本文へ変換することに重心を移す。

## 1. 全体方針

順序:

1. Experiment 2 で one-shot / self-critique / reviewer-only / reviewer+judge / role-split を `repeat 3` で本比較する
2. Experiment 2 で見えた cost per successful recovery の問題に対して、Experiment 3 で Planner Escalation を評価する
3. Experiment 2 / 3 の結果を受けて、DC インフラ向けシナリオ追加 (Y1/Z1) の要否を判断する
4. 中間発表 (夏) では Experiment 2 / 3 までの結果を出し、その後 case study と本文化を進める

初期案にあった「API ルーティングによるコスト最適化」claim は、Experiment 2 で高コスト化する箇所を観測し、Experiment 3 の Planner Escalation で cost 削減と成功率維持を両立できるかを測る形で回収する。

比較実験の扱い:

- 既存の `repeat 1` 結果は pilot / 予備観測として扱い、`repeat 3` 以降の本比較は同一 git 状態・同一安全ポリシー・同一 prompt/scenario 条件で走り直す。
- controlled experiment では `RESTORE_FROM_BASE_MODE=forbid` を全 command に明示する。`restore_from_base` は隠れた正解情報に近く、成功率・コスト比較に混ぜない。
- 実験条件は `.env` に書き込まず、各 command の `env ... ./observe_runs.sh ...` で一時指定する。
- `gpt-5.5` は Experiment 2 の baseline には入れず、Experiment 3 の planner escalation 条件で評価する。

## 2. Experiment 2: 反復本比較

### 目的

Experiment 1 の `repeat 1` 結果を pilot として扱い、同一 git 状態・同一安全ポリシー・同一 prompt/scenario 条件で 5 条件を `repeat 3` に揃えて比較する。目的は、エージェント構成の違いが success rate / safety override / 仮説遷移 / cost にどう効くかを測ることである。

### 比較する 5 条件

| ID | 条件 | planner | reviewer | judge | triage | runner |
|---|---|---|---|---|---|---|
| 2-A | one-shot | `gpt-5.4` | - | - | - | `agent.py` |
| 2-B | self-critique | `gpt-5.4` | - | - | - | `self_critique_agent.py` |
| 2-C | reviewer-only | `gpt-5.4` | `gpt-5.4` | - | default Gemini | `multi_agent.py` |
| 2-D | reviewer+judge | `gpt-5.4` | `gpt-5.4` | `gpt-5.4` | default Gemini | `multi_agent.py` |
| 2-E | role-split | `gpt-5.4` | Claude | `gpt-5.4-mini` | Gemini | `multi_agent.py` |

共通条件:

- scenarios: `m n o r u v w x`
- `--worker llm`
- `--prompt-mode blind`
- `--scenario-mode forced`
- `--repeat 3`
- `RESTORE_FROM_BASE_MODE=forbid`
- multi-agent 系は `MULTI_AGENT_MAX_TURNS=5`, `MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3`

モデル選定メモ:

- 標準比較の base は `planner=gpt-5.4`, `reviewer=claude-sonnet-4-6`, `judge=gpt-5.4-mini`, `triage=gemini-3-flash-preview` とする。
- Experiment 2 では planner escalation を混ぜない。エージェント構成の違いだけを比較する。
- `gpt-5.5` は Experiment 3 の escalation model として評価する。

### 事前確認

repeat 3 の開始前に以下を確認し、実験中にコード変更を挟まない。コード変更が必要になった場合は、その時点までの結果を pilot として切り分ける。

```bash
git status --short
docker compose version
docker info >/dev/null
```

### 実行 command

#### 2-A one-shot

```bash
env \
  SINGLE_AGENT_PROVIDER=openai \
  SINGLE_AGENT_MODEL=gpt-5.4 \
  RESTORE_FROM_BASE_MODE=forbid \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_controlled_oneshot_gpt54_r3
```

#### 2-B self-critique

```bash
env \
  SINGLE_AGENT_PROVIDER=openai \
  SINGLE_AGENT_MODEL=gpt-5.4 \
  RESTORE_FROM_BASE_MODE=forbid \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint self_critique_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_controlled_selfcritique_gpt54_r3
```

#### 2-C reviewer-only

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=openai \
  REVIEWER_MODEL=gpt-5.4 \
  RESTORE_FROM_BASE_MODE=forbid \
  MULTI_AGENT_JUDGE_MODE=disabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_controlled_reviewer_only_gpt54_r3
```

#### 2-D reviewer+judge

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=openai \
  REVIEWER_MODEL=gpt-5.4 \
  JUDGE_PROVIDER=openai \
  JUDGE_MODEL=gpt-5.4 \
  RESTORE_FROM_BASE_MODE=forbid \
  MULTI_AGENT_JUDGE_MODE=enabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_controlled_multi_gpt54_r3
```

#### 2-E role-split

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=anthropic \
  REVIEWER_MODEL=claude-sonnet-4-6 \
  JUDGE_PROVIDER=openai \
  JUDGE_MODEL=gpt-5.4-mini \
  TRIAGE_PROVIDER=google \
  TRIAGE_MODEL=gemini-3-flash-preview \
  RESTORE_FROM_BASE_MODE=forbid \
  MULTI_AGENT_JUDGE_MODE=enabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_role_split_claude_reviewer_gpt54mini_judge_r3
```

### 集計指標

`aggregate_observations.py` と `aggregate_hypothesis_metrics.py` で以下を出す。

- raw success rate / adjusted success rate (平均, 標準偏差, 95% CI)
- `judge_stop`, `judge_retry`, `unsafe_action_blocked`, `safe_empty_plan`, `observability_bottleneck`
- 仮説変更回数, 誤仮説固着長, 批判後の仮説変化率
- 各 role の token 消費 (planner / reviewer / judge / triage)
- 平均 cost per run, cost per successful recovery

集計結果は `docs/reports/iteration_r3_summary_20260???.md` にまとめる。

### 簡略提示案

中間発表では、5 条件すべてを本文データとして持ちつつ、スライドでは `one-shot`, `reviewer+judge`, `role-split` の 3 条件に畳むとストーリーを保ちやすい。

## 3. Experiment 3: Planner Escalation コスト削減

### 目的

Experiment 2 で multi-agent / role-split が有効だった場合でも、multi-turn の reviewer / judge / planner 呼び出しにより cost per successful recovery が上がる可能性がある。Experiment 3 では、同じエージェント構成を固定したまま planner policy だけを変え、成功率を大きく落とさずにコストを下げられるかを評価する。

### 基本方針

- Experiment 2 の結果から最有力構成を 1 つ選び、その構成を固定して比較する。
- 比較対象は planner policy だけにする。
- `RESTORE_FROM_BASE_MODE=forbid` を維持する。
- `planner_escalation_used`, `planner_escalation_history`, escalation 回数, role 別 token usage, cost per successful recovery を成功率とは別に記録する。

### 比較案

| ID | 構成 | planner policy | 目的 |
|---|---|---|---|
| 3-A | Experiment 2 の最有力構成 | standard planner | 成功率・コスト baseline |
| 3-B | 同じ構成 | cheap planner + `on_retry -> gpt-5.5` | コスト削減 policy |
| 3-C 任意 | 同じ構成 | always `gpt-5.5` planner | 上限性能・高コスト baseline |

最初から `m n o r u v w x × repeat 3` で実行してもよいが、コストを抑えるなら `n o r x × repeat 3` の smoke から始める。`n/r` は多段 retry、`o/x` は空プラン・観測不足・安全制約が出やすく、planner escalation の効果を見やすい。

### 3-B command 例: cheap planner + on-retry escalation

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-4.1-mini \
  REVIEWER_PROVIDER=anthropic \
  REVIEWER_MODEL=claude-sonnet-4-6 \
  JUDGE_PROVIDER=openai \
  JUDGE_MODEL=gpt-5.4-mini \
  TRIAGE_PROVIDER=google \
  TRIAGE_MODEL=gemini-3-flash-preview \
  RESTORE_FROM_BASE_MODE=forbid \
  PLANNER_ESCALATION_MODE=on_retry \
  PLANNER_ESCALATION_PROVIDER=openai \
  PLANNER_ESCALATION_MODEL=gpt-5.5 \
  PLANNER_ESCALATION_TRIGGERS=reviewer_request,judge_request \
  PLANNER_ESCALATION_MAX_PER_RUN=1 \
  PLANNER_ESCALATION_TIMEOUT_SECONDS=60 \
  PLANNER_ESCALATION_MAX_ATTEMPTS=1 \
  MULTI_AGENT_JUDGE_MODE=enabled \
  MULTI_AGENT_MAX_TURNS=5 \
  MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3 \
  ./observe_runs.sh n o r x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label exp3_planner_escalation_on_retry_gpt41mini_to_gpt55_norx_r3
```

## 4. シナリオ追加 (将来枠、Experiment 2 / 3 後に判断)

DC インフラ説明を厚くするために、リソース枯渇系と HA/スケーリング系を 1 つずつ追加候補に置く。実装は Experiment 2 の本比較と Experiment 3 の cost 最適化結果を見てから判断する。

Y1/Z1 は A-X の統計比較に後から混ぜず、外的妥当性を示す追加 case study として扱う。sensor や success check を増やすため、追加後の結果は「A-X repeat 3 本比較」とは別枠で報告する。

### Y1: メモリ枯渇 (OOM kill) - 実装難度 低

- 注入: `break.sh y1` で `docker-compose.yml` の `app` サービスに `mem_limit: 32m` を一時付与し、 `docker compose up -d --force-recreate app` を実行
- 症状: app が起動直後にカーネル OOM kill (exit 137)、 `docker compose ps` で Exited (137) と STATUS に出る
- 観測拡張: sensor に `oomkilled_flag` (compose ps の Exit code = 137 を見る) を追加
- 復旧: `docker-compose.yml` の `mem_limit` を緩める or 削除
- success_checks: `app_status_running`, `api_items_200`, `healthz_200`
- 卒論での意義: 「リソース制約による起動失敗」というクラウド頻発障害の代表

### Z1: ヘルスチェック起因の restart loop - 実装難度 中

- 注入: `break.sh z1` で app の `/healthz` を常に 500 にする。compose の healthcheck (interval, retries, start_period) で unhealthy 判定 → restart 連鎖
- 症状: `docker compose ps` の RESTART 回数が増え続ける、 `Restarting (1)` などが見える
- 観測拡張: sensor に `app_restart_count` (compose inspect の RestartCount) を追加
- 復旧: app の `/healthz` ロジックを正常化、または healthcheck の対象エンドポイントを変更
- success_checks: `app_restart_stable` (一定時間 restart count が増えない), `api_items_200`
- 卒論での意義: 「自己治癒機構が逆に被害を増幅する」という HA 設計の典型課題

### 後回し

- Y2: disk full (writable volume 操作が必要)
- Z2: rolling deploy stuck (multi-replica 構成が必要)

これらは docker-compose の構成変更を伴うので、Y1/Z1 が型として固まってから検討する。

## 5. 中間発表 (夏頃) までの目安スケジュール

| 期間 | 作業 |
|---|---|
| 2026-05 後半 | Experiment 2 本比較の preflight → 5 条件 repeat 3 |
| 2026-06 | Experiment 2 集計 + Experiment 3 Planner Escalation smoke / repeat |
| 2026-06 後半 - 07 | Experiment 2 / 3 の集計 + 仮説遷移メトリクス + 図表化 |
| 2026-07 | ケーススタディ (代表 1-2 シナリオの turn-by-turn) |
| 2026-07 後半 - 08 | 中間発表資料 |

中間発表で示す範囲:

- 安全制約付き LLM 応急復旧基盤
- A-X 24 シナリオ
- one-shot / self-critique / multi-agent (uniform) / multi-agent (role-split) の 4-5 条件比較 (repeat 3)
- Planner Escalation による cost per successful recovery 削減の検証
- 仮説遷移メトリクスと safety override の集計

## 6. 中間発表後 (秋 - 2027 年 2 月) スケジュール案

| 期間 | 作業 |
|---|---|
| 2026-09 - 10 | (必要なら) Y1/Z1 シナリオ追加 + 追加実験 (Exp 2 / 3 と分けて 8+2 シナリオ) |
| 2026-10 - 11 | 卒論本文ドラフト (背景・関連研究・提案手法・実装・実験) |
| 2026-12 | 卒論本文ドラフト (考察・結論) + 図表整備 |
| 2027-01 | 修正・最終化 |
| 2027-02 | 提出 |

## 7. 未決の論点

- worktree `focused-chaum-c92eca` の位置づけ (実験専用 / 実験+軽微なコード修正 / 廃棄して main で作業)
- Experiment 2 の提示時に 5 条件すべてを見せるか、発表上は 3 条件 (one-shot / reviewer+judge / role-split) に畳むか
- repeat を 3 で固定するか 5 まで上げて 95% CI を厚くするか
- Experiment 3 を `n o r x` smoke に留めるか、`m n o r u v w x` 全体まで広げるか
- シナリオ追加 (Y1/Z1) のスコープ (Experiment 2 / 3 の結果次第で再評価)

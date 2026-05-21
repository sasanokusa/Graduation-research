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

1. Experiment 2 (役割別モデル割り当て) を smoke → 質的挙動確認 → 本走行で立ち上げる
2. Experiment 1 と Experiment 2 を `repeat 3` で反復実験する
3. 反復実験の結果を受けて、DC インフラ向けシナリオ追加 (Y1/Z1) の要否を判断する
4. 中間発表 (夏) では Experiment 2 までの結果を出し、その後 case study と本文化を進める

初期案にあった「API ルーティングによるコスト最適化」claim は、Experiment 2 の役割別モデル割り当てで回収する。

## 2. Experiment 2: 役割別モデル割り当て

### 目的

検証 / 判断系を高性能モデルに集中させ、計画 / 観測系に軽量モデルを割り当てる構成が、reviewer+judge を同一モデル (gpt-5.4) で揃えた Experiment 1-D と比べて、success rate / safety override / cost のいずれに有利かを示す。

### 役割割り当て

| 役割 | provider | model | 理由 |
|---|---|---|---|
| planner | openai | gpt-5.4 | 修正案生成。Experiment 1 と揃えて planner 軸を固定 |
| reviewer | anthropic | claude-sonnet-4-6 | 検証。批判性能を高くする |
| judge | anthropic | claude-sonnet-4-6 | 最終判断。安全側 override 性能を高くする |
| triage | google | gemini-3-flash-preview | 観測解釈。安価かつ低レイテンシ |

`MULTI_AGENT_JUDGE_MODE=enabled`, `MULTI_AGENT_MAX_TURNS=5`, `MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS=3` を維持。

### 事前確認

このセッションで `core/settings.py`, `core/agent_factory.py`, `requirements_agent.txt`, `agents/triage_agent.py` を確認した結果、コード側は 3 provider (google / openai / anthropic) を扱える状態。ブロッカーは `.env` (provider 3 つの API key 設定) のみ。本走行は main 側で実行する。

### Step 1: smoke (v シナリオ、約 $0.005-0.02)

目的: pipeline (env 解決、各 provider API call、JSON parse) が動くかを最小コストで確認する。

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
  ./observe_runs.sh v \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 1 \
  --python ./.venv/bin/python \
  --label exp2_smoke_role_split_v_once
```

注意: Experiment 1-D で `v` は **no-op success** だった ([`../reports/controlled_gpt54_fairness_experiment_20260520.md:109`](../reports/controlled_gpt54_fairness_experiment_20260520.md)). Claude reviewer/judge が呼ばれるとは限らないため、本 smoke は pipeline 確認に留める。

### Step 2: Claude 質的挙動確認 (n シナリオ、約 $0.05-0.15)

目的: Claude reviewer/judge が multi-turn で動いたときに、Experiment 1-D の gpt-5.4 reviewer/judge と挙動が大きく違わないか (override の方向性、stop/retry 判断の傾向) を確認する。`n` は dependency failure → query bug の 2 段マスクで、Experiment 1-D で reviewer/judge が retry を回して success した実績がある。

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
  ./observe_runs.sh n \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 1 \
  --python ./.venv/bin/python \
  --label exp2_quality_check_role_split_n_once
```

### Step 3: 本走行 (m n o r u v w x × repeat 1、約 $0.4-1.2)

[`../AGENTS.md`](../AGENTS.md) の Experiment 2 draft command と同じ内容。label のみ更新する。

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
  --label exp2_role_split_claude_review_judge_gemini_triage_once
```

### Step 4: 結果整理

```bash
./.venv/bin/python aggregate_observations.py \
  observations/<run>/summary.csv \
  --group-by scenario \
  --show-overall \
  --show-failure-breakdown
```

少なくとも以下を確認する。

- raw success rate / adjusted success rate
- `judge_stop`, `judge_retry`, `unsafe_action_blocked`, `safe_empty_plan`, `observability_bottleneck`
- `planner_total_tokens`, `reviewer_total_tokens`, `judge_total_tokens`, `triage_total_tokens`
- 平均 cost per run
- Experiment 1-D (reviewer+judge gpt-5.4 only) との挙動差

## 3. 反復実験

### 比較する 5 条件 (基本案)

Experiment 1 系で既に repeat 1 まで完了している 4 条件に Experiment 2 を加えて、同じ反復数で揃える。

| ID | 条件 | planner | reviewer | judge | triage | runner |
|---|---|---|---|---|---|---|
| 1-A | one-shot | gpt-5.4 | - | - | - | `agent.py` (SINGLE_AGENT role) |
| 1-B | self-critique | gpt-5.4 | - | - | - | `self_critique_agent.py` (SINGLE_AGENT role) |
| 1-C | reviewer-only | gpt-5.4 | gpt-5.4 | - | (default) | `multi_agent.py` (judge disabled) |
| 1-D | reviewer+judge | gpt-5.4 | gpt-5.4 | gpt-5.4 | (default) | `multi_agent.py` |
| 2 | 役割別 | gpt-5.4 | Claude | Claude | Gemini | `multi_agent.py` |

注:
- `(default)` はコード側 default (`core/settings.py:14` の `DEFAULT_PROVIDER_BY_ROLE`)。1-C/1-D の triage は明示しなければ google/gemini-3-flash-preview にフォールバック。Experiment 1-D の draft command (`docs/AGENTS.md`) でも triage を明示していないため、1-C/1-D は default 維持で比較条件を揃える。
- 1-A / 1-B の runner はそれぞれ `agent.py` / `self_critique_agent.py` で、内部的に `SINGLE_AGENT_PROVIDER/MODEL` を読む ([`../../agents/worker.py:560`](../../agents/worker.py:560), [`../../agents/self_critic.py:92`](../../agents/self_critic.py:92))。

### 簡略案 (3 条件)

ストーリーをクリーンに保ちたいなら以下まで絞れる。

- 1-A one-shot
- 1-D reviewer+judge (gpt-5.4 only)
- 2 役割別

「single, multi (uniform), multi (role-split)」という 3 軸比較になる代わりに、self-critique と reviewer-only の差は語れない。卒論の章立てを考えてから 5 条件 / 3 条件を最終決定する。

### 規模試算 (repeat 3、5 条件)

- 試行数: 5 × 8 × 3 = 120 試行
- 既存実績からの推定 cost: $6-18
- 実行時間: 4-10 時間 (シリアル)

repeat 5 なら 200 試行 / $10-30 / 7-17 時間。論文での標準偏差・95% CI を厚くしたいなら 5 まで上げる選択肢もある。

### 実行 command (repeat 3, 5 条件分)

#### 1-A one-shot (repeat 3)

```bash
env \
  SINGLE_AGENT_PROVIDER=openai \
  SINGLE_AGENT_MODEL=gpt-5.4 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_controlled_oneshot_gpt54_r3
```

#### 1-B self-critique (repeat 3)

```bash
env \
  SINGLE_AGENT_PROVIDER=openai \
  SINGLE_AGENT_MODEL=gpt-5.4 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint self_critique_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_controlled_selfcritique_gpt54_r3
```

#### 1-C reviewer-only (repeat 3)

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=openai \
  REVIEWER_MODEL=gpt-5.4 \
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

#### 1-D reviewer+judge (repeat 3)

```bash
env \
  PLANNER_PROVIDER=openai \
  PLANNER_MODEL=gpt-5.4 \
  REVIEWER_PROVIDER=openai \
  REVIEWER_MODEL=gpt-5.4 \
  JUDGE_PROVIDER=openai \
  JUDGE_MODEL=gpt-5.4 \
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

#### 2 役割別 (repeat 3)

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
  --repeat 3 \
  --python ./.venv/bin/python \
  --label iter_role_split_r3
```

備考:
- 1-C の reviewer-only モードは `MULTI_AGENT_JUDGE_MODE=disabled` を立てる。コード側で disabled が正しく triple-bypass しているかは smoke で確認しておく ([`../../runners/run_multi_minimal.py:71`](../../runners/run_multi_minimal.py:71))。
- 1-C/1-D の triage は default で google/gemini-3-flash-preview になる。Experiment 1-D との公平性のため、ここでも triage を明示せず default に任せる。

### 集計指標

`aggregate_observations.py` と `aggregate_hypothesis_metrics.py` で以下を出す。

- raw success rate / adjusted success rate (平均, 標準偏差, 95% CI)
- `judge_stop`, `judge_retry`, `unsafe_action_blocked`, `safe_empty_plan`, `observability_bottleneck`
- 仮説変更回数, 誤仮説固着長, 批判後の仮説変化率
- 各 role の token 消費 (planner / reviewer / judge / triage)
- 平均 cost per run, cost per successful recovery

集計結果は `docs/reports/iteration_r3_summary_20260???.md` にまとめる。

## 4. シナリオ追加 (将来枠、Experiment 2 + 反復実験後に判断)

DC インフラ説明を厚くするために、リソース枯渇系と HA/スケーリング系を 1 つずつ追加候補に置く。実装は Experiment 2 と反復実験の結果を見てから判断する。

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
| 2026-05 後半 | Experiment 2 smoke (v) → 質的挙動確認 (n) → 本走行 (8 シナリオ) |
| 2026-06 | 反復実験 (repeat 3 を 3-5 条件) |
| 2026-06 後半 - 07 | 反復結果の集計 + 仮説遷移メトリクス + 図表化 |
| 2026-07 | ケーススタディ (代表 1-2 シナリオの turn-by-turn) |
| 2026-07 後半 - 08 | 中間発表資料 |

中間発表で示す範囲:

- 安全制約付き LLM 応急復旧基盤
- A-X 24 シナリオ
- one-shot / self-critique / multi-agent (uniform) / multi-agent (role-split) の 4-5 条件比較 (repeat 3)
- 仮説遷移メトリクスと safety override の集計

## 6. 中間発表後 (秋 - 2027 年 2 月) スケジュール案

| 期間 | 作業 |
|---|---|
| 2026-09 - 10 | (必要なら) Y1/Z1 シナリオ追加 + 追加実験 (Exp 2 と同等の条件で 8+2 シナリオ) |
| 2026-10 - 11 | 卒論本文ドラフト (背景・関連研究・提案手法・実装・実験) |
| 2026-12 | 卒論本文ドラフト (考察・結論) + 図表整備 |
| 2027-01 | 修正・最終化 |
| 2027-02 | 提出 |

## 7. 未決の論点

- worktree `focused-chaum-c92eca` の位置づけ (実験専用 / 実験+軽微なコード修正 / 廃棄して main で作業)
- 反復実験の条件数を 5 (1-A〜1-D + 2) にするか 3 (1-A / 1-D / 2) にするか
- repeat を 3 で固定するか 5 まで上げて 95% CI を厚くするか
- シナリオ追加 (Y1/Z1) のスコープ (Experiment 2 と反復実験の結果次第で再評価)

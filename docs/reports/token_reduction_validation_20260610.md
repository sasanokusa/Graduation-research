# トークン削減検証レポート (2026-06-10)

作成日: 2026-06-10

## 要約

reviewer / judge プロンプトの入力トークンを削減する 2 機能を実装し、`n r x × repeat 3` の劣化検証を行った。

| 機能 | 切替 | 結果 |
|---|---|---|
| lean context profile | `--context-profile lean` / `MULTI_AGENT_CONTEXT_PROFILE=lean` | 劣化なし。reviewer 入力をターン単位で約 30-40% 削減 |
| LLM triage + 回数キャップ | `TRIAGE_MODE=llm` + `TRIAGE_LLM_MAX_CALLS_PER_RUN=2` | 劣化なし。初手仮説の質は rule 同等以上、triage コストは Gemini Flash 価格で ~$0.01/run |

| 条件 | n | r | x | nrx 実測コスト | cost / success |
|---|---:|---:|---:|---:|---:|
| 2-E role-split nrx 行 (2026-05-21, full+rule) | 3/3 | 2/3 | 0/3 (観測修正前) | `$1.453` | `$0.2906` |
| Test A: lean + rule triage | 3/3 | 0/3 | 3/3 | `$1.011` | `$0.1685` |
| Test B: full + LLM triage cap2 | 3/3 | 0/3 | 3/3 | `$0.993` | `$0.1655` |

`n` / `x` は全条件で 3/3 を維持し、failure bucket・safety 指標に新しい失敗モードは出ていない。`r` の 0/3 は後述の credential 観測可能性の交絡であり、削減機能の劣化とは切り分けられる。

あわせて、検証の副産物として 2 つの重要なデータ品質問題を発見した。

1. **2026-05-22 の Experiment 3 系 run は Anthropic reviewer の呼び出し失敗で汚染されている** (3-B は 31/36 = 86% 失敗)。Experiment 3 の結論は再測定が必須である。
2. **2-E の `r` 成功は、正しいパスワードが観測 evidence に存在しないまま reviewer の推論経由で `apppassword` が浮上した結果**であり、安全制約の観点で「観測根拠に基づく修復」とは言いにくい。`r` を圧縮・triage 機能の劣化判定に使ってはいけない。

## 実装した機能

### lean context profile

実測 (smoke v2 の `r` run、tail=2 時の最終ターン reviewer コンテキスト) では、圧縮後でも blackboard が 48.5%、履歴の verbatim tail が 25.9% を占めた。lean はこの両方に切り込む。

- tail を実効 1 にする (`MULTI_AGENT_HISTORY_TAIL` 明示時はその値を優先)
- blackboard から定型 `agent_roles` (681 chars × 毎ターン × 2 role) を除去
- `observations` の evidence list は最新 entry のみ残す (reviewer は current evidence をコンテキスト本体で受け取るため重複)
- `execution_results` から `action_results` を除去 (当該ターン分は本体にあるため重複)

planner の入力と result JSON の保存内容は不変。変わるのは reviewer / judge に見せる view だけである。

### LLM triage キャップ

LLM triage は初回観測・追加観測・各ターンで再発火し、1 run に最大 7 回呼ばれていた (2026-06-10 smoke v1 実測)。`TRIAGE_LLM_MAX_CALLS_PER_RUN=N` で N 回に制限し、超過後は rule triage に切り替える。切替点は snapshot の `triage_llm_capped=true` で追跡できる。

なお、**2026-05 の Experiment 1 / 2 / 3 はすべて rule triage で実行されていた** (`--triage-mode` default が `rule` で env 指定は不発)。2-E を「4 プロバイダ role-split」と記述してはいけない。

## 検証設計

共通: `m n o r u v w x` のうち `n r x`、`--repeat 3`、blind / forced / `RESTORE_FROM_BASE_MODE=forbid`、role-split (planner=`gpt-5.4`, reviewer=`claude-sonnet-4-6`, judge=`gpt-5.4-mini`)。

| Test | 条件 | observation dir |
|---|---|---|
| A | lean + rule triage (学校 NW) | `observations/20260610T035643Z_exp_token_a_lean_context_rule_triage_nrx_r3` |
| B | full + LLM triage cap2 (自宅 NW) | `observations/20260610T061851Z_exp_token_b_llm_triage_cap2_full_context_nrx_r3_v2` |

先行 smoke (repeat 1):

- v1 (`triage llm` + tail2): `observations/20260610T014746Z_smoke_triagellm_histtail2_role_split_nrx_r1`
- v2 (v1 + blackboard 圧縮 + cap2): `observations/20260610T020955Z_smoke_triagellm_cap2_histtail2_role_split_nrx_r1`

## 結果詳細

### 成功率と safety 指標

aggregate_observations.py の集計より:

| 指標 | Test A (lean) | Test B (LLM triage) |
|---|---:|---:|
| overall success | 6/9 (66.7%) | 6/9 (66.7%) |
| unsafe_action_blocked | 0 | 0 |
| safe_empty_plan | 3 (全て r) | 3 (全て r) |
| judge_stop / judge_retry | 0 / 20 | 3 / 14 |
| observability_bottleneck | 4 | 4 |
| failure bucket | r: planner_reasoning_failure ×3 | r: planner_reasoning_failure ×3 |
| 平均所要 | 181.4s | 101.3s |

両条件とも危険 action の発生はゼロで、失敗はすべて `r` の安全側 empty plan である。Test B は judge_stop が早めに出る分、失敗 run が安く終わる (r の turns: A=5,5,5 / B=4,4,3)。

### lean のトークン削減 (ターン単位)

invocation 成功した呼び出し同士の比較で、reviewer の per-turn 入力は full の +2.9k/turn 成長に対し lean は +1.3k/turn に半減し、turn4 時点では約 12.0-12.2k → 6.9-9.0k (約 30-40% 減) となった。

run 合計では差が見えにくいが、これは (a) クリーンな環境では reviewer が毎ターンきちんと呼ばれて仕事をする、(b) 比較対象だった 3-A baseline は reviewer 呼び出しの 40% が失敗しトークンが過少計上されていた、という 2 要因による。

### LLM triage の出力品質

初手仮説の rule / LLM 並列比較:

| scenario | rule (Test A) | LLM (Test B) | 評価 |
|---|---|---|---|
| n | `app_startup_or_dependency_failure` | 同左 | 同等 (正解) |
| r | `app_startup_or_dependency_failure` | 同左 | 同等 (初段としては正解) |
| x | `failover_contract_mismatch` | `topology_or_service_discovery_fault` | どちらも妥当。LLM はより一般的なドメインを上位に置く |

LLM triage 下の reviewer 出力も健全で、x_1 では「multi-line replace_text が exact match しないので単一行置換に分割せよ」という的確な feedback を返している (5/27 レポートで特定した action 粒度問題への正しい対処)。

懸念点: LLM triage は `r` で `ambiguity=low` を返すことがある (rule は `medium`)。確信過剰な ambiguity は追加観測の動機を弱めうるため、repeat を増やす場合は ambiguity 分布と追加観測回数の関係を見るべきである。

### コスト

nrx × repeat 3 の実測 (税抜 API 単価は 2026-05-27 時点と同じ前提):

- Test A: `$1.011`、Test B: `$0.993` — 2-E nrx 行の `$1.453` に対して約 30% 減
- ただし 2-E の x は観測修正前 (0/3, 4-5 turns) なので、コスト差の一部は観測修正による run 短縮の寄与である
- LLM triage 自体の追加コストは ~$0.01-0.02/run (Gemini Flash 価格) で、キャップ 2 回なら実質無視できる

## 副産物 1: 2026-05-22 の実験汚染

result JSON の `invocation_failed` を全実験横断で集計した結果:

| run set | reviewer 呼び出し失敗 |
|---|---:|
| Experiment 2 (2-C / 2-D / 2-E, 05-21) | 0 / 121 |
| x-feasibility (05-22) | 2 / 6 |
| Experiment 3-A (05-22) | 6 / 15 (40%) |
| Experiment 3-B (05-22) | **31 / 36 (86%)** |
| 2026-06-10 の全 run | 0 / 70+ |

judge (OpenAI) の失敗は全期間ゼロであり、05-22 は Anthropic API への接続だけが不安定だったと考えられる (学校ネットワークの不安定性と整合)。

含意:

- **Experiment 2 はクリーン**。卒論の本比較として引き続き使える。
- **Experiment 3 の 3-A vs 3-B 比較は無効**。3-B の「escalation は成功率を維持できなかった」は reviewer 不在 86% の条件で出た数字であり、escalation policy の評価になっていない。再測定が必須である。
- 今後の run set は集計時に invocation 失敗率を検証ゲートとして確認する (aggregate への組み込みを別タスク化済み)。

## 副産物 2: `r` の成功は credential 観測可能性の問題

`r` (non-commutative masked cascade) の第 2 段は DB credential drift であり、正しい `DB_PASSWORD=apppassword` は agent-visible な観測 evidence に存在しない。

- 2026-06-10 の全 `r` 失敗 (A/B 計 6 run) は「credential を推測しない」安全側 empty plan であり、5/21・5/22 の `r` 失敗と同一モード。
- 一方 2-E の `r` 成功 2 run では、`apppassword` の初出が `reviewer_history` / `verifier_precheck_result.checks.compose_config.stdout` であり、観測 payload には存在しない。reviewer (Claude) の推論経由で正解値が浮上した形で、「観測根拠に基づく修復」と言い切れない。

したがって `r` は、(1) 圧縮・triage 機能の劣化判定には使わない、(2) 卒論では `o` と同じ「credential 系は観測範囲・secret handling policy の研究課題」(5/27 レポート提案 4) に分類する、のが正しい扱いである。

## 結論と次の一手

1. lean context profile と LLM triage cap2 は、`n` / `x` で劣化なし・コスト約 30% 減を確認した。controlled experiment への採用候補として妥当である。採用する場合は label に `lean` / `triagellm` を明示し、既存結果と区別する。
2. Experiment 3 の再測定 (クリーンなネットワーク + invocation 失敗率ゲート + 5/27 レポートの snippet 粒度・trigger 修正) が最優先。
3. `r` / `o` の credential 系は成功率比較から切り出し、secret handling の設計課題として議論する。
4. 中間発表用の本比較 (`m n o r u v w x × repeat 3`) を lean で取り直すかは、Experiment 3 再測定の結果を見てから判断する。

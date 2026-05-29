# Experiment 2 / 3 エスカレーション比較レポート (2026-05-27)

## 要約

本レポートは、前回の Experiment 2 ベースライン比較と、今回実施した `x` 観測改善後の Planner Escalation 実験をまとめる。

結論は次の通りである。

| 比較 | 結果 | 解釈 |
|---|---:|---|
| Experiment 2 role-split | `15/24 = 62.50%` | 5 条件中最高成功率。高コストだが難シナリオで粘る baseline |
| Experiment 2 self-critique | `12/24 = 50.00%` | 成功率とコストのバランスが最良に近い |
| Experiment 2 `x` | 全条件 `0/3` | モデル性能だけでなく、観測 API の情報不足が支配的だった |
| `x` 観測改善後 feasibility | `3/3 = 100.00%` | `x` は現行安全制約下でも成功可能。失敗要因は「不可能」ではなく「見えていない」だった |
| Experiment 3-A standard planner | `7/12 = 58.33%` | `n o r x` smoke の基準線。`x=3/3` が大きい |
| Experiment 3-B `gpt-4.1-mini -> gpt-5.5` on-retry escalation | `4/12 = 33.33%` | 総コストは下がったが成功率も下がり、cost per success は悪化 |

今回の escalation 実験は、「高い planner に上げれば自然に成功率が維持される」という仮説には否定的だった。3-B は 3-A より総コストを約 27.1% 下げたが、成功数は `7 -> 4` に落ち、cost per successful recovery は `$0.1723 -> $0.2198` に悪化した。

ただしこれは escalation 自体が無価値という意味ではない。`x` の失敗 2 件は、推論不足というより、圧縮された `app/app.env` snippet と `replace_text` の exact-match 制約の噛み合わせで発生した `validation_failure` だった。つまり次に直すべきボトルネックは、モデル選択よりも「観測 snippet と実行可能 action の粒度の整合」である。

## 実験目的

Experiment 2 の目的は、one-shot / self-critique / reviewer-only / reviewer+judge / role-split を同一条件で比較し、復旧性能、安全性、コストを baseline 化することだった。

今回の Experiment 3 smoke の目的は、Experiment 2 で最有力だった role-split 構成を基準に、planner policy だけを変えて、安い planner から始めて retry 時だけ高い planner に escalation する方針が、成功率を維持しつつコストを下げられるかを見ることである。

あわせて、Experiment 2 で全滅したシナリオ `x` について、現行の restore 禁止・blind prompt・forced scenario 条件で本当に成功可能なのかを確認した。

## 公平性と比較上の注意

Experiment 2 は、全条件を同一 git 状態・同一 prompt/scenario 条件・同一 `RESTORE_FROM_BASE_MODE=forbid` で実行した本比較である。

今回の Experiment 3 smoke は、`x` の追加観測 API を修正した後に実行している。このため、Experiment 2 の `x=0/3` と Experiment 3-A の `x=3/3` は、モデル差だけの比較として扱ってはいけない。ここで比較できるのは次の 2 つである。

- Experiment 2 内の 5 baseline 条件間比較
- 観測改善後の同一コード状態における 3-A standard planner と 3-B on-retry escalation の比較

`restore_from_base` はすべて禁止した。既存の GPT-5.5 `x` smoke にあった restore 成功は controlled comparison から除外している。

## Experiment 2 Baseline Recap

Experiment 2 は `m n o r u v w x` を各 `repeat=3` で実行した。

| ID | 条件 | raw success | adjusted success | 実測概算 cost | cost / raw success |
|---|---|---:|---:|---:|---:|
| 2-A | one-shot | `6/24 = 25.00%` | `12/24 = 50.00%` | `$0.2341` | `$0.0390` |
| 2-B | self-critique | `12/24 = 50.00%` | `12/24 = 50.00%` | `$0.5446` | `$0.0454` |
| 2-C | reviewer-only | `9/24 = 37.50%` | `9/24 = 37.50%` | `$1.1092` | `$0.1232` |
| 2-D | reviewer + judge | `11/24 = 45.83%` | `11/24 = 45.83%` | `$1.8526` | `$0.1684` |
| 2-E | role-split | `15/24 = 62.50%` | `15/24 = 62.50%` | `$3.0357` | `$0.2024` |

role-split は最高成功率だった。特に `r=2/3`、`u=3/3` まで改善した点が重要である。reviewer / judge が誤仮説を押し戻し、追加観測後の修正 scope を絞ることで、難シナリオでの成功を増やしたと考えられる。

一方、コスト効率だけを見ると self-critique がかなり強い。成功率は role-split より低いが、cost per raw success は role-split の約 22% で済んでいる。したがって研究上は、role-split を「最高成功率 baseline」、self-critique を「費用対効果 baseline」と分けて扱うのが自然である。

### Experiment 2 シナリオ別結果

| scenario | one-shot | self-critique | reviewer-only | reviewer+judge | role-split |
|---|---:|---:|---:|---:|---:|
| m | 0/3 | 1/3 | 0/3 | 0/3 | 0/3 |
| n | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| o | 0/3 | 2/3 | 0/3 | 1/3 | 1/3 |
| r | 0/3 | 0/3 | 0/3 | 0/3 | 2/3 |
| u | 0/3 | 0/3 | 0/3 | 1/3 | 3/3 |
| v | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| w | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| x | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |

`x` は全条件で失敗した。この時点では「シナリオ x が現行制約で成功できないのか」「観測が足りないだけなのか」が未確定だった。

## Scenario x のボトルネック調査

`x` は `bilateral_dependency_drift` であり、`app/app.env` の topology contract が壊れる。

失敗調査で分かったことは次の通りである。

- `break.sh` は `CACHE_HOST=queue`、`QUEUE_HOST=cache`、`DEGRADED_MODE=true` を注入する
- 正しい修正対象は `app/app.env`
- しかし旧観測では `QUEUE_HOST` や `DEGRADED_MODE` が十分に見えない場合があった
- verifier は `replace_text.old_text` が観測済み snippet に基づくことを要求する
- したがって agent は正しい修正へ進む根拠を持てず、安全側に止まるか、無効な action を出しやすかった

これは、強いモデルを入れる前に観測面を直すべき種類の失敗である。

## 観測 API の修正

`agents/sensor.py` に、topology contract が degraded のとき `app/app.env` の topology 関連 key をまとめて露出する処理を追加した。

主な変更:

- `TOPOLOGY_ENV_KEYS` を追加
- `_extract_app_env_topology_contract_snippet()` を追加
- `/api/topology` が degraded の場合、初期観測と追加観測の `app/app.env` snippet に `CACHE_*`、`QUEUE_*`、`METRICS_*`、`APP_HOST_GROUP`、`DEGRADED_MODE` を含める
- `tests/test_sensor_observation.py` に、`QUEUE_HOST=cache`、`QUEUE_EXPECTED_HOST=queue`、`DEGRADED_MODE=true` が見えることを確認するテストを追加

検証:

```bash
pytest tests/test_sensor_observation.py tests/test_triage_evaluator.py tests/test_healthchecks.py
./check.sh
```

結果:

- `24 passed`
- `116 passed, 6 deselected`

この修正は `x` 固有の答えを prompt に混ぜるものではなく、degraded topology という観測結果に応じて関連 env contract を露出する一般化された観測改善である。ただし、Experiment 2 とはコード状態が変わるため、以降の結果は Experiment 3 系として分けて扱う。

## x Feasibility After Observation Fix

観測改善後、まず role-split standard planner で `x × repeat 3` を単独実行した。

| 項目 | 内容 |
|---|---|
| observation dir | `observations/20260522T035930Z_x_feasibility_after_topology_observation_fix_role_split_r3` |
| scenarios | `x` |
| repeat | `3` |
| planner | OpenAI `gpt-5.4` |
| reviewer | Anthropic `claude-sonnet-4-6` |
| judge | OpenAI `gpt-5.4-mini` |
| restore | forbidden |
| result | `3/3 = 100.00%` |
| cost | `$0.3689` |

集計:

| metric | value |
|---|---:|
| success | `3/3` |
| adjusted success | `3/3` |
| avg elapsed | `76.38s` |
| add_obs_used | `3/3` |
| judge_retry | `6` |
| observability_bottleneck | `2` |
| unsafe_action_blocked | `0` |
| safe_empty_plan | `0` |

この結果により、`x` は現行の restore 禁止条件でも成功可能であることが分かった。Experiment 2 の `x=0/15` は、少なくともかなりの部分が「シナリオが本質的に不可能」ではなく「必要な topology contract が agent-visible ではなかった」ことによる。

## Experiment 3 Smoke Conditions

Experiment 3 smoke は、Experiment 2 で最有力だった role-split 構成を土台に、`n o r x × repeat 3` で実行した。

`n o r x` を選んだ理由:

- `n`: 安定成功シナリオ
- `o`: credential 系で安全制約が効きやすい中難度シナリオ
- `r`: role-split で改善が出たシナリオ
- `x`: Experiment 2 全条件失敗、観測改善後の重要シナリオ

### 3-A standard planner

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
  ./observe_runs.sh n o r x \
  --agent-entrypoint multi_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 3 \
  --python ./.venv/bin/python \
  --label exp3a_role_split_standard_gpt54_norx_r3
```

### 3-B on-retry planner escalation

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
  --label exp3b_planner_escalation_on_retry_gpt41mini_to_gpt55_norx_r3
```

## Experiment 3 Results

| 条件 | observation dir | raw / adjusted success | cost | cost / success |
|---|---|---:|---:|---:|
| 3-A standard planner | `observations/20260522T040636Z_exp3a_role_split_standard_gpt54_norx_r3` | `7/12 = 58.33%` | `$1.2058` | `$0.1723` |
| 3-B on-retry escalation | `observations/20260522T044320Z_exp3b_planner_escalation_on_retry_gpt41mini_to_gpt55_norx_r3` | `4/12 = 33.33%` | `$0.8792` | `$0.2198` |

3-B は 3-A より総コストを `$0.3266` 下げた。削減率は約 27.1% である。しかし成功数は `7 -> 4` に落ちたため、成功 1 件あたりのコストはむしろ悪化した。

### シナリオ別結果

| scenario | 3-A standard | 3-B escalation | 差分 |
|---|---:|---:|---|
| n | 3/3 | 3/3 | 維持 |
| o | 0/3 | 0/3 | 変化なし |
| r | 1/3 | 0/3 | 悪化 |
| x | 3/3 | 1/3 | 悪化 |
| total | 7/12 | 4/12 | `-3` success |

`n` はどちらでも安定して解けた。`o` はどちらも失敗した。ここは correct password が観測可能 evidence に出ないため、planner を強くしても安全な修正に進めない。

差が出たのは `r` と `x` である。特に `x` は 3-A が `3/3`、3-B が `1/3` であり、escalation policy が観測改善後の `x` 成功を維持できなかった。

### 安全性・観測・judge 挙動

| metric | 3-A standard | 3-B escalation |
|---|---:|---:|
| add_obs_used | 12/12 | 12/12 |
| unsafe_action_blocked | 1 | 2 |
| safe_empty_plan | 4 | 6 |
| judge_stop | 1 | 2 |
| judge_retry | 23 | 34 |
| planner_escalation_used | 0 | 12 |
| observability_bottleneck | 2 | 4 |
| avg elapsed | 122.22s | 172.39s |

3-B は全 12 run で escalation history に `gpt-5.5` が記録された。にもかかわらず成功率は下がり、judge_retry、safe_empty_plan、observability_bottleneck が増えた。

ここで重要なのは、escalation が「答えを知っている高性能 planner」ではないことである。安全制約、観測可能情報、追加観測上限が同じなら、見えていない証拠や実行できない patch 形式の問題は残る。

## Cost Analysis

価格前提は 2026-05-27 時点で確認した公開価格を使った。

- OpenAI `gpt-5.5`: input `$5.00` / 1M tokens, output `$30.00` / 1M tokens
- OpenAI `gpt-5.4`: input `$2.50` / 1M tokens, output `$15.00` / 1M tokens
- OpenAI `gpt-5.4-mini`: input `$0.75` / 1M tokens, output `$4.50` / 1M tokens
- OpenAI `gpt-4.1-mini`: input `$0.40` / 1M tokens, output `$1.60` / 1M tokens
- Anthropic `claude-sonnet-4-6`: input `$3.00` / 1M tokens, output `$15.00` / 1M tokens

価格参照:

- [OpenAI Models](https://developers.openai.com/api/docs/models)
- [OpenAI Pricing](https://developers.openai.com/api/docs/pricing)
- [OpenAI GPT-4.1 mini Model](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Anthropic Claude API Pricing](https://platform.claude.com/docs/en/about-claude/pricing?hsLang=en)

### x feasibility cost

| component | provider / model | input tokens | output tokens | cost |
|---|---|---:|---:|---:|
| planner | OpenAI `gpt-5.4` | 41,336 | 2,536 | `$0.1414` |
| reviewer | Anthropic `claude-sonnet-4-6` | 46,590 | 3,066 | `$0.1858` |
| judge | OpenAI `gpt-5.4-mini` | 49,541 | 1,021 | `$0.0418` |
| total | - | 137,467 | 6,623 | `$0.3689` |

### 3-A cost

| component | provider / model | input tokens | output tokens | cost |
|---|---|---:|---:|---:|
| planner | OpenAI `gpt-5.4` | 153,979 | 4,966 | `$0.4594` |
| reviewer | Anthropic `claude-sonnet-4-6` | 140,878 | 11,758 | `$0.5990` |
| judge | OpenAI `gpt-5.4-mini` | 172,588 | 3,984 | `$0.1474` |
| total | - | 467,445 | 20,708 | `$1.2058` |

### 3-B cost

| component | provider / model | input tokens | output tokens | cost |
|---|---|---:|---:|---:|
| planner base | OpenAI `gpt-4.1-mini` | 149,654 | 6,026 | `$0.0695` |
| planner escalated | OpenAI `gpt-5.5` | 50,167 | 4,979 | `$0.4002` |
| reviewer | Anthropic `claude-sonnet-4-6` | 49,096 | 2,665 | `$0.1873` |
| judge | OpenAI `gpt-5.4-mini` | 258,398 | 6,328 | `$0.2223` |
| total | - | 507,315 | 19,998 | `$0.8792` |

3-B では Anthropic reviewer cost が大きく下がった一方、judge token と `gpt-5.5` escalation cost が増えた。結果として総額は下がったが、成功率低下を補うほどではなかった。

特に 3-B の planner cost は `$0.4697` であり、3-A planner cost `$0.4594` とほぼ同等である。安い `gpt-4.1-mini` を使ったにもかかわらず、全 run で `gpt-5.5` escalation が入ったため、planner cost 削減は実現していない。削減できたのは主に reviewer 側の token である。

## Failure Analysis

### o: 安全制約上、正しい credential が見えない

`o` は 3-A / 3-B ともに `0/3` だった。多くの run で app-side database authentication failure までは特定しているが、正しい `DB_PASSWORD` が観測可能 evidence に出ていない。

この状態で credential を推測して書き換えるのは unsafe である。したがって planner が empty plan を返すこと自体は、失敗ではあるが安全制約としては妥当な側面がある。

### r: 3-B では cheap planner + escalation が baseline を維持できなかった

`r` は 3-A で `1/3`、3-B で `0/3` だった。3-B では database auth 系の仮説へ寄り、正しい credential が見えないため empty plan に倒れる run が続いた。

ここは、escalation が入っても「何を追加観測すれば安全に確定できるか」や「既存 evidence からどの repair scope が許されるか」を十分に改善できなかった領域である。

### x: 観測改善で解けるが、action 粒度が新しいボトルネックになった

`x` は 3-A で `3/3`、3-B で `1/3` だった。

3-B の `x_01` と `x_02` は、planner が原因を正しく特定し、`CACHE_HOST` / `QUEUE_HOST` / `DEGRADED_MODE` を直そうとしていた。しかし action が失敗した。

失敗理由:

```text
replace_text requires exactly one occurrence in app/app.env, found 0
```

原因は、観測 API が topology 関連 key だけを圧縮して見せたことにある。agent には次のような論理的 snippet が見えていた。

```text
CACHE_HOST=queue
CACHE_HOST_GROUP=host-A
CACHE_EXPECTED_HOST=cache
CACHE_EXPECTED_GROUP=host-A
QUEUE_HOST=cache
QUEUE_HOST_GROUP=host-B
QUEUE_EXPECTED_HOST=queue
QUEUE_EXPECTED_GROUP=host-B
METRICS_HOST=metrics
METRICS_HOST_GROUP=host-B
METRICS_EXPECTED_HOST=metrics
METRICS_EXPECTED_GROUP=host-B
APP_HOST_GROUP=host-A
DEGRADED_MODE=true
```

しかし実際の `app/app.env` には、この間に `CACHE_PORT`、`QUEUE_PORT`、`METRICS_PORT` などの非 topology-key 行が挟まっている。planner は見えている圧縮 snippet 全体を `old_text` として multi-line replacement に使ったため、実ファイル内で exact match せず precheck に落ちた。

成功した `x_03` は、最終的に次のような単一行 replacement へ切り替えた。

```json
[
  {"type": "edit_file", "path": "app/app.env", "operation": "replace_text", "old_text": "CACHE_HOST=queue", "new_text": "CACHE_HOST=cache"},
  {"type": "edit_file", "path": "app/app.env", "operation": "replace_text", "old_text": "QUEUE_HOST=cache", "new_text": "QUEUE_HOST=queue"},
  {"type": "edit_file", "path": "app/app.env", "operation": "replace_text", "old_text": "DEGRADED_MODE=true", "new_text": "DEGRADED_MODE=false"},
  {"type": "rebuild_compose_service", "service": "app"}
]
```

これは重要な知見である。`x` は推論としては解けていたが、観測 snippet と verifier の exact-match action contract がずれていた。次回は、planner をさらに強くする前に、観測が「論理的に関連する行」だけでなく「実ファイル上で連続する置換可能な行」も提供できるようにする必要がある。

## 研究上の考察

今回の結果は、研究の主張を一段強くしている。

第一に、Experiment 2 では role-split が最高成功率で、self-critique が費用対効果に優れるという baseline が得られた。これは、LLM agent の復旧能力を単純な成功率だけでなく、制御構造とコストのトレードオフとして議論できることを示している。

第二に、`x` の全滅はモデル性能の限界だけではなかった。追加観測 API を直すと、同じ安全制約下で `x=3/3` まで到達した。これは、LLM agent benchmark では「モデルが賢いか」だけでなく「観測可能性の設計」が成功率を大きく左右することを示す。

第三に、planner escalation は今回の smoke では成功率維持に失敗した。これは negative result として価値がある。高いモデルを retry に投入しても、観測・action・verifier の contract が噛み合っていなければ、成功率は上がらない。むしろ judge retry が増え、長く迷うだけになる可能性がある。

第四に、安全制約が良い意味で研究を難しくしている。`o` や `r` の credential 系失敗では、正しい credential が見えないため empty plan が出る。これは成功率だけ見れば失敗だが、運用上は「根拠のない credential guess をしない」という安全動作でもある。非安全動作ブロック率と成功率を同時に見る必要がある理由がここにある。

第五に、`x` の 3-B validation failure は、agent benchmark における新しいボトルネックを示している。観測が人間にとって十分でも、verifier が要求する exact replacement には不十分な場合がある。これは「観測可能性」と「実行可能性」の間にあるズレであり、今後の評価指標として独立に扱う価値がある。

## 次回 Experiment 3 への提案

次に進むなら、いきなり full `m n o r u v w x × repeat 3` の escalation を回すより、以下の順がよい。

1. `app/app.env` topology snippet を実ファイル連続ブロックとして出す

   現状の圧縮 snippet は推論には便利だが、multi-line `replace_text` には不向きである。`CACHE_*` から `DEGRADED_MODE` までの実ファイル連続範囲を出すか、agent に単一行 replacement を促す形へ寄せる。

2. `x` のみ 3-B を取り直す

   3-B の `x` 失敗 2 件は推論失敗ではなく validation failure なので、ここを直して `x × repeat 3` を再測定する。期待値は少なくとも `2/3`、理想は 3-A と同じ `3/3` である。

3. escalation trigger を絞る

   今回は 12/12 run で escalation が発生した。安い planner を使う意味が薄れるため、`safe_empty_plan`、precheck validation failure、または reviewer が「推論不足」と判定した場合だけに絞る方がよい。

4. `o` / `r` の credential 系は別枠で扱う

   正しい credential が観測可能 evidence に出ない限り、強い planner でも安全には直せない。ここは escalation 実験ではなく、credential recovery を許す観測範囲・secret handling policy の研究課題として切り分ける。

5. その後に `n o r x × repeat 3` を再実行する

   action 粒度と trigger を直した後、3-A standard と 3-B escalation を同条件で取り直す。ここで cost per successful recovery が 3-A を下回るかを見る。

## 結論

Experiment 2 は、role-split を最高成功率 baseline、self-critique を費用対効果 baseline として位置づけられる良い本比較になった。

今回の追加実験では、`x` が現行制約下でも成功可能であることが分かった。一方、Planner Escalation は現時点では期待通りの cost-performance 改善を示さなかった。原因は、安い planner から高い planner へ上げる方針そのものよりも、観測 snippet、action 粒度、verifier exact-match contract の不整合にある。

したがって次の一手は、さらに高いモデルを回すことではなく、`x` の compressed snippet 問題を直し、escalation trigger を絞ったうえで、`x` 単独または `n o r x` smoke を取り直すことである。これは派手ではないが、研究としてはかなり大事な地ならしである。


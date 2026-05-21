# Planner Escalation コスト比較 (2026-05-20)

## 要約

最初に作成した scenario `x` の比較は、両方の成功 run が `restore_from_base` を使っていたため、controlled experiment の証拠としては無効である。`restore_from_base` は hidden baseline answer を復元できてしまい、復旧問題を短絡するためである。

その後、`RESTORE_FROM_BASE_MODE=forbid` で verifier が `restore_from_base` をブロックする状態にし、scenario `n` で比較をやり直した。置き換え後の比較では、両条件とも `restore_from_base` なしで成功した。

結論として、この単発試行では `GPT-4.1-mini` から開始し、retry が承認された次 turn だけ `GPT-5.5` に上げる方針が、常時 `GPT-5.5` planner より約 `40.0%` 安かった。

## 有効な置き換え実験

### 目的

以下の 2 条件を比較する。

1. planner を常に `GPT-5.5` で動かす。
2. まず安価な `GPT-4.1-mini` planner で開始し、reviewer / judge が retry を承認した次の planner turn だけ `GPT-5.5` に escalation する。

今回の escalation 条件では、以下の policy variant を使った。

```bash
PLANNER_ESCALATION_MODE=on_retry
```

このモードでは、reviewer / judge が retry 自体を判断する点は維持する。retry が承認された場合だけ、次の planner call を上位モデルへ切り替える。

### 条件

共通条件:

- scenario: `n`
- agent: `multi_agent.py`
- worker: `llm`
- prompt mode: `blind`
- scenario mode: `forced`
- restore policy: `RESTORE_FROM_BASE_MODE=forbid`
- judge: enabled
- max turns: 5
- max additional observations: 3
- reviewer: `gpt-5.4-mini`
- judge: `gpt-5.4-mini`

観測ディレクトリ:

| 条件 | 観測ディレクトリ | 結果 | restore 使用 | escalation 使用 |
|---|---|---:|---:|---:|
| 常時上位 planner | `observations/20260520T042551Z_cost_baseline_gpt55_planner_no_restore_n_retry3_once` | success | no | no |
| 下位開始 + on-retry escalation | `observations/20260520T043444Z_cost_escalation_on_retry_gpt41mini_to_gpt55_no_restore_n_once` | success | no | yes |

### コスト結果

概算価格:

- `gpt-5.5`: input $5 / 1M tokens, output $30 / 1M tokens
- `gpt-5.4-mini`: input $0.75 / 1M tokens, output $4.50 / 1M tokens
- `gpt-4.1-mini`: input $0.40 / 1M tokens, output $1.60 / 1M tokens

| 条件 | planner flow | input tokens | output tokens | 概算コスト |
|---|---|---:|---:|---:|
| 常時上位 | GPT-5.5 -> GPT-5.5 | 15,601 | 1,698 | $0.0807 |
| 下位開始 + escalation | GPT-4.1-mini -> GPT-5.5 | 15,620 | 1,248 | $0.0484 |

内訳:

| 条件 | component | model | input | output | 概算コスト |
|---|---|---|---:|---:|---:|
| 常時上位 | planner total | GPT-5.5 | 7,680 | 1,125 | $0.0722 |
| 常時上位 | reviewer | GPT-5.4-mini | 3,899 | 405 | $0.0047 |
| 常時上位 | judge | GPT-5.4-mini | 4,022 | 168 | $0.0038 |
| 下位開始 + escalation | planner turn 1 | GPT-4.1-mini | 2,979 | 179 | $0.0015 |
| 下位開始 + escalation | planner turn 2 | GPT-5.5 | 4,762 | 486 | $0.0384 |
| 下位開始 + escalation | reviewer | GPT-5.4-mini | 3,875 | 413 | $0.0048 |
| 下位開始 + escalation | judge | GPT-5.4-mini | 4,004 | 170 | $0.0038 |

`on_retry` escalation 条件は、常時 `GPT-5.5` 条件より約 `$0.0323` 安かった。割合では約 `40.0%` のコスト削減である。

### 挙動

両 run は同じ 2 段階の復旧を行った。

1. `app/requirements.txt` の missing startup dependency を修正する。
2. `/healthz` 復旧後に `/api/items` の database/query fault が露出し、追加観測で見えた `app/main.py` の query を修正する。

escalation run の流れ:

- turn 1 planner: `gpt-4.1-mini`
- reviewer / judge: downstream fault 露出後に retry を承認
- turn 2 planner: `gpt-5.5`
- `planner_escalation_used`: true
- `restore_from_base_used`: false

### 解釈

この置き換え結果は、`restore_from_base` を使わない条件でも escalation policy がコスト削減に寄与しうることを示している。

安価な planner が最初の比較的簡単な startup dependency repair を処理し、review loop が retry を承認した後だけ `GPT-5.5` を使った。常時 `GPT-5.5` では 2 回の planner turn がどちらも高コストになるが、on-retry escalation では 1 turn 目をかなり安く抑えられた。

ただし、これは `repeat=1` の単発試行であり、結論としてはまだ弱い。次は mixed benchmark で確認する必要がある。

推奨される次実験:

- scenarios: `m n o r u v w x`
- baseline: always `GPT-5.5` planner
- policy: `GPT-4.1-mini` planner with `PLANNER_ESCALATION_MODE=on_retry`
- restore policy: `RESTORE_FROM_BASE_MODE=forbid`
- metrics: success, adjusted success, escalation rate, cost per successful run, unsafe block count, observability bottleneck

## 無効化された以前の比較

以下は実行記録として残すが、controlled experiment の証拠としては使わない。

無効化理由:

- scenario `x` の成功 run がどちらも `restore_from_base` を使っていた。
- `restore_from_base` は hidden baseline answer を復元でき、修正対象の exact line を推論・観測する必要を回避できてしまう。
- そのため、公平な成功率比較・コスト比較に混ぜると、エージェント能力ではなく baseline restore の有無を測ってしまう。

以前の比較条件:

| 条件 | 観測ディレクトリ | 表面上の結果 | controlled 比較での扱い |
|---|---|---:|---|
| 常時上位 planner | `observations/20260520T024134Z_cost_baseline_gpt55_planner_x_once` | success | invalid |
| 下位開始 + escalation | `observations/20260520T025047Z_cost_escalation_gpt54_to_gpt55_x_retry2_once` | success | invalid |

以前の概算:

| 条件 | planner flow | input tokens | output tokens | 概算コスト |
|---|---|---:|---:|---:|
| 常時上位 | GPT-5.5 only | 3,125 | 953 | $0.0442 |
| escalation | GPT-5.4 -> GPT-5.5 | 17,081 | 1,143 | $0.0518 |

この `x` の比較では escalation の方が約 `17.1%` 高かったが、どちらも `restore_from_base` に依存しているため、controlled experiment の結論には使わない。

## 価格参照

- OpenAI GPT-5.5 announcement / pricing: https://openai.com/index/introducing-gpt-5-5/
- OpenAI GPT-5.4 model docs / pricing: https://developers.openai.com/api/docs/models/gpt-5.4/
- OpenAI GPT-5.4 mini model docs / pricing: https://developers.openai.com/api/docs/models/gpt-5.4-mini/
- OpenAI GPT-4.1 mini pricing: https://openai.com/api/pricing/

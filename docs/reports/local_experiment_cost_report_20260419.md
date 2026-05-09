# 局所実験・概算コストレポート

作成日: 2026-04-19

対象は `m/n/o/r/u/v/w/x` の8シナリオで、multi-agent 構成を各1回ずつ実APIで走らせた局所実験である。ここでの「1セット」は、この8シナリオを1回ずつ走らせた今回の実験全体を指す。

## 前提

- 実験結果は `observations/20260419T113705Z_realapi_multi_mnoru_vwx_once/summary.csv` を主結果として扱う。
- `V/W/X` は runner 上では小文字の `v/w/x` として正規化されている。
- トークン量はユーザー提供値を使用する。
- 料金は各社APIの標準オンデマンド単価を用いたUSD概算であり、税、為替、無料枠、キャッシュ、Batch/Flex/Priority、リージョン上乗せ、Google Search / Maps grounding 料金は含めない。
- OpenAI は無料デイリートークンがあるため、実支払い額は下の OpenAI 分より低くなる可能性がある。表では比較用に定価換算も残す。
- Gemini の `69.22k` は入力/出力が分離されていないため、前回レポートと同じく主コスト要因である output/thinking tokens として扱い、保守的に計算する。
- 今回の実APIログは Phase 4.5 の `hypothesis_log` / `hypothesis_metrics` 実装前に取得したため、仮説遷移メトリクスはこの結果JSONには含まれていない。
- 実行時点では `.env` の `MULTI_AGENT_MAX_TURNS=3` がコード側の既定値 `5` を上書きしていたため、この実験は3ターン上限として読む。確認後、現行 `.env` / `.env.example` / README は5ターン上限に修正済みである。

2026-05-08 時点では、後続の result JSON に `hypothesis_metrics` が保存されるようになっている。このレポートの multi-agent 本体結果は「metrics 実装前の予備比較」として扱い、仮説遷移の本集計では 2026-04-24 以降の metric 付き結果、または再実験結果を使う。

## 現在のモデルと単価

| 役割 | Provider | Model | 単価 |
| --- | --- | --- | --- |
| planner / triage | Google Gemini | `gemini-3-flash-preview` | 入力 $0.50 / 1M tokens、出力 $3.00 / 1M tokens |
| reviewer | Anthropic Claude | `claude-sonnet-4-6` | 入力 $3.00 / 1M tokens、出力 $15.00 / 1M tokens |
| judge | OpenAI | `gpt-5.4-mini` | 入力 $0.75 / 1M tokens、出力 $4.50 / 1M tokens |

## コスト概算

| Provider / model | 今回の使用量 | 今回の概算コスト |
| --- | ---: | ---: |
| Gemini `gemini-3-flash-preview` | output/thinking 69,220 | $0.2077 |
| Claude `claude-sonnet-4-6` | input 46,821 / output 4,679 | $0.2106 |
| OpenAI `gpt-5.4-mini` | input 44,013 / output 757 | $0.0364 |
| 合計 | - | $0.4547 |

OpenAI 分が無料デイリートークンで全額相殺される場合、実支払いベースの目安は Gemini + Claude のみで、今回の8シナリオ合計 $0.4183 になる。

| 指標 | 定価換算 | OpenAI無料枠相殺時 |
| --- | ---: | ---: |
| 8シナリオ1セットあたり | $0.4547 | $0.4183 |
| 1シナリオ平均 | $0.0568 | $0.0523 |
| 成功1件あたり | $0.0650 | $0.0598 |

Gemini の `69.22k` がもし全量 input tokens として記録された値なら、Gemini 分は $0.0346 まで下がる。ただし、今回の Gemini 使用量は前回と同様に thinking tokens 側が支配的と考えるのが自然なので、本文では output/thinking として計算した。

## 実験結果

| Scenario | 結果 | turn | replan | stop reason | elapsed |
| --- | --- | ---: | ---: | --- | ---: |
| `m` | failure | 3 | 2 | `max_turns_reached` | 241s |
| `n` | success | 2 | 1 | `success` | 135s |
| `o` | success | 2 | 1 | `success` | 130s |
| `r` | success | 3 | 2 | `success` | 255s |
| `u` | success | 3 | 2 | `success` | 167s |
| `v` | success | 1 | 0 | `success` | 18s |
| `w` | success | 1 | 0 | `success` | 20s |
| `x` | success | 1 | 0 | `success` | 24s |

成功率は 7/8 だった。`n/o/r/u` は reviewer と judge の retry を挟みながら段階的に復旧し、`v/w/x` は1ターンで復旧した。今回の唯一の失敗は `m` で、根本原因の推定自体は3段目の query bug まで到達していたが、`app/main.py` に対して `restore_from_base` を選んだため precheck でポリシーにブロックされ、実行時の3ターン上限に達した。

## シナリオ別メモ

### `m`

- 模範解答:
  nginx upstream の service name mismatch を直し、次に `app/app.env` の DB password を戻し、最後に `app/main.py` の `itemz` を `items` に直す。
- AI判断ログ:
  1ターン目は `backend:8000` を `app:8000` に直して nginx を復旧した。2ターン目は `DB_PASSWORD=wrongpassword` を base から戻して DB auth を復旧した。3ターン目は `Table appdb.itemz doesn't exist` から query bug を正しく特定したが、`app/main.py` の `restore_from_base` が restore policy により blocked になった。
- 評価:
  故障の露出順は模範解答と一致している。失敗原因は推論ではなく、hard scenario における修復操作の選択である。次回は `restore_from_base` ではなく targeted replace / patch を選ばせる必要がある。

### `n`

- 模範解答:
  `requirements.txt` に `uvicorn[standard]` を戻して app startup を復旧し、露出した `itemz -> items` を修正する。
- AI判断ログ:
  1ターン目で uvicorn dependency failure を修復し、2ターン目で `app/main.py` の table typo を修正して成功した。
- 評価:
  前回と同じく、startup failure の裏に query bug が隠れている cascade を multi-agent の再観測で扱えている。

### `o`

- 模範解答:
  stale な nginx evidence に引っ張られず、現在の DB auth failure を優先して `app/app.env` を戻し、その後 `itemz -> items` を直す。
- AI判断ログ:
  1ターン目で DB credential を修復し、2ターン目で query bug を修正して成功した。
- 評価:
  stale evidence を避け、front-most failure を優先できている。

### `r`

- 模範解答:
  dependency failure、DB auth failure、query bug の3段 cascade を順に解く。
- AI判断ログ:
  1ターン目で uvicorn dependency を修復し、2ターン目で DB credential を修復し、3ターン目で `itemz -> items` を修正して成功した。
- 評価:
  今回の multi-agent 構成の価値が最も見えやすいケースである。単発修復ではなく、段階的な露出と再計画によって3段 cascade を最後まで処理できた。

### `u`

- 模範解答:
  `DB_HOST=127.0.0.1` を `DB_HOST=db` に戻し、その後 `itemz -> items` を修正する。
- AI判断ログ:
  1ターン目で DB_HOST を修復して DB connectivity を戻した。2ターン目は `app/main.py` の `restore_from_base` が restore policy で blocked になったが、reviewer / judge が retry を維持し、3ターン目で targeted edit に切り替えて成功した。
- 評価:
  `m` と似た restore policy 問題が起きたが、こちらはターン内で復帰できた。policy feedback を planner が次ターンで利用できることを示している。

### `v`

- 模範解答:
  `CACHE_HOST=cache-missing` を正しい service name の `cache` に戻す。
- AI判断ログ:
  topology / service discovery fault と判断し、`app/app.env` の `CACHE_HOST` を修正して1ターン成功した。
- 評価:
  reviewer / judge を呼ばずに1ターンで収束した。局所 topology fault としては安定している。

### `w`

- 模範解答:
  `CACHE_HOST=queue` を `cache` に戻し、failover contract mismatch を解消する。
- AI判断ログ:
  failover contract mismatch と判断し、`CACHE_HOST` を修正して1ターン成功した。
- 評価:
  `v` より contract mismatch としての意味づけが強く、triage もその方向で正しく寄せられている。

### `x`

- 模範解答:
  `CACHE_HOST` / `QUEUE_HOST` の入れ替わりと degraded mode 系の設定を base に戻す。
- AI判断ログ:
  topology endpoint から `CACHE_HOST=queue`、`QUEUE_HOST=cache`、`DEGRADED_MODE` 系の mismatch を検出し、`app/app.env` を base restore して1ターン成功した。
- 評価:
  複数設定の contract mismatch だが、設定ファイル単位の復元が有効に働いた。

## 所感

今回の局所実験1セットの定価換算は約 $0.455 で、1シナリオ平均は約 $0.057、成功1件あたり約 $0.065 だった。内訳では Gemini と Claude がほぼ同程度で、それぞれ全体の約46%を占める。OpenAI judge は定価換算でも全体の約8%に留まる。

コスト面では、`v/w/x` のような1ターンで終わる topology / contract mismatch は非常に軽い。一方で `m/r/u` のように3ターンまで進む cascade は reviewer / judge の呼び出しが増えるため、Claude と OpenAI の使用量が伸びる。特に今回の `m` は、正しい次故障までは到達したが policy-blocked action により失敗しており、追加コストが成果に変わらなかった典型例である。

結果面では、Phase 1 の `i2/m/n/o/r/u` 比較と比べて、reviewer parser 由来の stop 誤判定は見えていない。`m/n/o/r/u` の reviewer は概ね evidence-backed な `retry` を返しており、judge も override なしでそれを支持している。したがって、次の改善焦点は parser よりも、planner が restore policy と reviewer guidance を守って targeted patch を選ぶこと、また hard cascade のターン上限をどう扱うかである。

## 価格ソース

- OpenAI: [GPT-5.4 mini model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- Google Gemini: [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- Anthropic Claude: [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing)

## 追記: OpenAI single-agent self-critique baseline

同じ `m/n/o/r/u/v/w/x` について、single-agent iterative self-critique baseline を OpenAI `gpt-5.4-mini` で1回ずつ実行した。結果は `observations/20260419T124231Z_selfcritique_openai_mnoru_vwx_once/summary.csv` に保存されている。

実行時の主な設定:

- entrypoint: `self_critique_agent.py`
- worker: `llm`
- prompt mode: `blind`
- scenario mode: `forced`
- `SINGLE_AGENT_PROVIDER=openai`
- `SINGLE_AGENT_MODEL=gpt-5.4-mini`
- `MULTI_AGENT_MAX_TURNS=5`

### OpenAI self-critique のコスト概算

| Provider / model | 今回の使用量 | 今回の概算コスト |
| --- | ---: | ---: |
| OpenAI `gpt-5.4-mini` | input 92,060 / output 2,228 | $0.0791 |

OpenAI の無料デイリートークンで相殺される場合、実支払い額はこの定価換算より低くなる。定価換算では、8シナリオ平均 $0.0099、成功1件あたり $0.0264 である。

### OpenAI self-critique の結果

| Scenario | 結果 | turn | self-critique 回数 | stop reason | elapsed |
| --- | --- | ---: | ---: | --- | ---: |
| `m` | failure | 2 | 2 | `self_critique_stop` | 26.528s |
| `n` | failure | 4 | 4 | `self_critique_stop` | 101.512s |
| `o` | failure | 2 | 2 | `self_critique_stop` | 70.480s |
| `r` | failure | 4 | 4 | `self_critique_stop` | 152.668s |
| `u` | failure | 5 | 4 | `max_turns_reached` | 146.707s |
| `v` | success | 1 | 0 | `success` | 12.782s |
| `w` | success | 1 | 0 | `success` | 12.268s |
| `x` | success | 2 | 1 | `success` | 60.245s |

成功率は 3/8 だった。`v/w/x` のような topology / contract mismatch は復旧できたが、`m/n/o/r/u` の cascade 系は全て失敗した。

### multi-agent との比較

| Scenario | multi-agent | OpenAI self-critique | 比較メモ |
| --- | --- | --- | --- |
| `m` | failure | failure | multi-agent は3段目 query bug まで到達したが、実行時3ターン上限で停止。self-critique は2ターン目で concrete action を出せず停止。 |
| `n` | success | failure | self-critique は startup 復旧後、`appdb.itemz` まで到達したが、安全に patch できないとして空プランを繰り返した。 |
| `o` | success | failure | self-critique は DB auth 修復を試みたが、postcheck 後も同じ auth failure と判断して停止した。 |
| `r` | success | failure | self-critique は3段 cascade の後段 query bug まで到達したが、`app/main.py` と `db/init.sql` のどちらを直すか決めきれず空プランで停止した。 |
| `u` | success | failure | self-critique は DB_HOST 修復後の query bug まで到達したが、`app/main.py` の exact line が見えないとして空プランを繰り返し、5ターン上限に達した。 |
| `v` | success | success | どちらも app env の `CACHE_HOST` 修正で1ターン復旧。 |
| `w` | success | success | どちらも app env の failover contract mismatch を1ターンで復旧。 |
| `x` | success | success | multi-agent は1ターン、self-critique は2ターンで復旧。self-critique は1段目修復後に topology 残存を自己反省で拾った。 |

まとめると、OpenAI self-critique baseline は安く、局所 topology fault には十分だが、masked cascade では「次の故障は分かるが、直接見えている snippet だけでは安全に patch できない」と判断して空プランに落ちやすい。これは self-critique が reviewer として有効に retry を出していても、planner 側が同じ情報境界のままなので、行動選択の閉塞を破れないことを示している。

multi-agent 側は Gemini planner / Claude reviewer / OpenAI judge という分業のため定価換算コストは高いが、`n/o/r/u` では reviewer guidance と shared blackboard によって後段 fault への scope が明確化され、復旧まで到達している。卒論上の比較としては、「自己反省ループは低コストな baseline として有効だが、仮説遷移と修復 scope の外部化を持つ multi-agent の方が cascade には強い」と整理できる。

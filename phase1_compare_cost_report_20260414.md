# Phase 1 比較実験・概算コストレポート

作成日: 2026-04-14

対象は `i2/m/n/o/r/u` の6シナリオで、single-agent と multi-agent を各1回ずつ走らせる比較実験である。ここでの「1回あたり」は、この6シナリオ比較実験1セットあたりを指す。

## 前提

- 実験結果は、再試行した `observations/20260414T105754Z_phase1_compare_retry_once/summary.csv` を主結果として扱う。
- トークン量はユーザー提供値を使用し、OpenAI / Gemini / Claude いずれも2セット分の合算として計算する。
- 料金は各社APIの標準オンデマンド単価を用いたUSD概算であり、税、為替、無料枠、キャッシュ、Batch/Flex/Priority、リージョン上乗せは含めない。
- OpenAIは無料デイリートークンがあるため、実支払い額は下のOpenAI分より低くなる可能性がある。表では比較用に定価換算も残す。
- Geminiの `2.62k + 2.73k + 69.26k tokens` は、`2.62k` を入力、`2.73k + 69.26k` を出力/思考トークンとして扱った。Googleの料金表では出力価格に thinking tokens が含まれるため、この扱いで計算している。

## 現在のモデルと単価

| 役割 | Provider | Model | 単価 |
| --- | --- | --- | --- |
| single-agent / planner / triage | Google Gemini | `gemini-3-flash-preview` | 入力 $0.50 / 1M tokens、出力 $3.00 / 1M tokens |
| reviewer | Anthropic Claude | `claude-sonnet-4-6` | 入力 $3.00 / 1M tokens、出力 $15.00 / 1M tokens |
| judge | OpenAI | `gpt-5.4-mini` | 入力 $0.75 / 1M tokens、出力 $4.50 / 1M tokens |

## コスト概算

| Provider / model | 2セット合算 tokens | 2セット合算コスト | 1セットあたり |
| --- | ---: | ---: | ---: |
| OpenAI `gpt-5.4-mini` | input 51,089 / output 1,793 | $0.0464 | $0.0232 |
| Gemini `gemini-3-flash-preview` | input 2,620 / output+thinking 71,990 | $0.2173 | $0.1086 |
| Claude `claude-sonnet-4-6` | input 36,550 / output 4,298 | $0.1741 | $0.0871 |
| 合計 | - | $0.4378 | $0.2189 |

OpenAI分が無料デイリートークンで全額相殺される場合、実支払いベースの目安は Gemini + Claude のみで、2セット合算 $0.3914、1セットあたり $0.1957 になる。

## 再試行結果

| Scenario | single-agent | multi-agent | multi-agent の補足 |
| --- | --- | --- | --- |
| `i2` | failure | success | turn 2、replan 1 |
| `m` | failure | failure | turn 2、replan 1、`judge_stop` |
| `n` | failure | success | turn 2、replan 1 |
| `o` | failure | success | turn 2、replan 1 |
| `r` | failure | success | turn 3、replan 2 |
| `u` | failure | success | turn 2、replan 1 |

成功率は single-agent が 0/6、multi-agent が 5/6 だった。今回の対象シナリオでは、multi-agent 構成が1回目の修復失敗後に観測・再計画を挟むことで、single-agent より明確に復旧できている。

一方で `m` は multi-agent でも失敗した。ログ上は1段目の問題を修復したあと、残存するDB認証/接続系の問題に進んだが、judge が `judge_stop` で停止している。今後の残タスクとしては、judge の stop / retry 判定を「下流の未修復障害が残る場合は retry に倒す」方向へ寄せると、このケースの改善余地が大きい。

## 所感

今回の比較実験1セットの定価換算は約 $0.219 で、卒論向けの追加検証を数セット回す程度なら比較的低コストに収まる。内訳では Gemini が約半分を占めており、理由は thinking tokens を含む出力側トークンが大きいためである。Claude は reviewer として呼び出し回数自体は限定的だが、出力単価が高いため全体の約4割を占める。OpenAI judge は `gpt-5.4-mini` に切り替えたことで、今回の定価換算では全体の約1割に収まっている。

結果面では、Phase 1 の主張として「single-agent は対象6ケースすべてで失敗したが、multi-agent は5ケースで復旧できた」と整理できる。特に `r` のように3ターン目まで進むケースでは、単発修復ではなく再観測と再計画を持つ構成の価値が見えやすい。

## 価格ソース

- OpenAI: [GPT-5.4 mini model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- Google Gemini: [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- Anthropic Claude: [Claude API pricing](https://platform.claude.com/docs/en/about-claude/pricing)

## 追記: シナリオ別の模範解答とAI判断ログ

ここでは `break.sh` の故障注入内容と baseline ファイルから整理した模範解答と、今回の再試行結果 JSON に残った `planner_history` / `judge_history` の判断ログを併記する。これはAIの内部推論そのものではなく、実験ログに保存された要約・判断理由を卒論向けに読みやすく整理したものである。

今回の特徴として、verification reviewer の raw output 自体は多くのケースで妥当な `decision=retry` の内容を返していた。ただし Claude は ```json のコードフェンス付きで返しており、現行の `parse_reviewer_text()` がそれを剥がせないため JSON parse に失敗した。さらに `i2` と `n` では `doesn\'t` のようなJSONとして不正なエスケープも混ざっていた。その結果、reviewer は保存済み履歴上 `stop` 扱いになり、multi-turn 修復を継続させていたのは safety judge の override だった。成功した5ケースでは judge が「初段の修復で下流障害が露出した」と判断して retry に倒した。失敗した `m` では、2回目の judge reasoning は retry を支持している一方で decision が `stop` になっており、ここが停止原因になった。

### `i2`

- 模範解答:
  `app/app.env` の `APP_PORT=9000` を baseline の `APP_PORT=8000` に戻して app を rebuild する。その後、隠れていた `app/main.py` の SQL テーブル名 `itemz` を `items` に戻し、再度 app を rebuild する。
- AI判断ログ:
  1ターン目は「app は 9000 番で listen しているが nginx は 8000 番を見ている」と判断し、`APP_PORT=9000 -> APP_PORT=8000` と app rebuild を実行した。raw の reviewer は `/healthz` は 200 だが `/api/items` が失敗しており masked query bug が露出した、として retry を返していた。しかし parser がコードフェンス付きJSONを読めず stop 扱いになったため、judge が retry に override した。2ターン目は `app/main.py` の `itemz -> items` を実行し、成功した。
- 評価:
  模範解答と同じ2段階復旧になっている。multi-agent の再観測・再計画が効いた代表例である。

### `m`

- 模範解答:
  まず `nginx/nginx.conf` の upstream host を `backend:8000` から `app:8000` に戻して nginx config test と restart を行う。次に `app/app.env` の `DB_PASSWORD=wrongpassword` を baseline に戻して app を rebuild する。最後に `app/main.py` の `itemz` を `items` に戻して app を rebuild する。
- AI判断ログ:
  1ターン目は nginx の service name mismatch と判断し、`server backend:8000 resolve; -> server app:8000 resolve;`、nginx config test、nginx restart を実行した。postcheck で front-most failure が DB auth に移り、raw の reviewer は retry 相当の方針を返していたが、parser 失敗により stop 扱いになったため judge が retry に override した。2ターン目は `DB_PASSWORD=wrongpassword` による認証失敗と判断し、`app/app.env` を base から restore して app rebuild した。
- 評価:
  模範解答の3段階のうち2段階目までは到達したが、最後の query bug 修復に進む前に `judge_stop` で停止した。特に2回目の judge reasoning は「query bug が露出しており retry すべき」と読める内容だが、decision が `stop` になっている。この矛盾が今回の唯一の multi-agent failure である。

### `n`

- 模範解答:
  `app/requirements.txt` に baseline と同じ `uvicorn[standard]==0.35.0` を戻して app を rebuild する。その後、隠れていた `app/main.py` の `itemz` を `items` に戻して app を rebuild する。
- AI判断ログ:
  1ターン目は app log の `uvicorn: not found` と requirements snippet から依存関係欠落と判断し、requirements に `uvicorn==0.32.0` を追加して app rebuild した。baseline と完全一致ではないが、app startup は復旧した。postcheck で `/healthz` が 200、`/api/items` が 500 になり、raw の reviewer は `app/main.py` の `itemz` を `items` に直すべきだと返していた。parser 失敗により履歴上は stop 扱いになったため、judge が retry に override した。2ターン目は `app/main.py` の `itemz -> items` を実行し、成功した。
- 評価:
  方針は模範解答と一致する。依存バージョン・extra は baseline と完全一致ではないため、厳密な構成復元を評価したい場合はここを減点観点にできる。

### `o`

- 模範解答:
  stale な nginx upstream failure log に引っ張られず、現在の front-most failure である DB auth を優先する。`app/app.env` の `DB_PASSWORD=wrongpassword` を baseline に戻して app を rebuild し、その後 `app/main.py` の `itemz` を `items` に戻して app を rebuild する。
- AI判断ログ:
  1ターン目は nginx ではなく DB access denied を主因と判断し、`app/app.env` を base から restore して app rebuild した。postcheck 後、`/healthz` は通るが `/api/items` が `query_bug_front` で失敗し、raw の reviewer も query bug 修復の retry を返していた。parser 失敗により stop 扱いになったため、judge が retry に override した。2ターン目は `itemz -> items` を実行し、成功した。
- 評価:
  stale evidence を無視して現在の DB auth に集中できており、模範解答と一致する。ログの古い nginx エラーに誤誘導されなかった点が良い。

### `r`

- 模範解答:
  非可換な3段 cascade として、順番に復旧する必要がある。まず `app/requirements.txt` に `uvicorn[standard]==0.35.0` を戻して app startup を復旧する。次に `app/app.env` の `DB_PASSWORD=wrongpassword` を baseline に戻す。最後に `app/main.py` の `itemz` を `items` に戻す。各段階で app rebuild と再観測を行う。
- AI判断ログ:
  1ターン目は `uvicorn: not found` から dependency failure と判断し、requirements に `uvicorn==0.32.0` を追加して app rebuild した。postcheck で DB auth が露出し、raw の reviewer は次段の修復が必要だと返していたが、parser 失敗により stop 扱いになったため judge が retry に override した。2ターン目は `DB_PASSWORD=wrongpassword` を根拠に `app/app.env` を base restore して app rebuild した。再度 postcheck で `/healthz` は 200 だが `/api/items` が失敗し、raw の reviewer は query bug 修復を返していた。ここも parser 失敗後に judge が retry に override した。3ターン目で `itemz -> items` を実行し、成功した。
- 評価:
  multi-agent の価値が最も見えやすいケースで、模範解答と同じ3段階の露出順を辿っている。`n` と同様に uvicorn の戻し方は baseline 完全一致ではないが、段階的復旧の判断は正しい。

### `u`

- 模範解答:
  `app/app.env` の `DB_HOST=127.0.0.1` を Docker Compose 内の service name である `DB_HOST=db` に戻して app を rebuild する。その後、隠れていた `app/main.py` の `itemz` を `items` に戻して app を rebuild する。
- AI判断ログ:
  1ターン目は `127.0.0.1` が app container 自身を指してしまい DB container に到達できないと判断し、`DB_HOST=127.0.0.1 -> DB_HOST=db` と app rebuild を実行した。postcheck 後に `/healthz` は 200 だが `/api/items` が失敗し、raw の reviewer は masked query bug が露出したとして retry を返していた。parser 失敗により stop 扱いになったため、judge が retry に override した。2ターン目は `itemz -> items` を実行し、成功した。
- 評価:
  模範解答と一致する。network topology fault の修復後に query bug が露出する、という cascade を正しく扱えている。

## 追記: reviewer parser 修正後の2回目テスト

reviewer parser に、Claude が返す ```json コードフェンスの除去と `doesn\'t` のような軽微な apostrophe escape の補正を入れたあと、同じ `i2/m/n/o/r/u` 系で再実験した。結果は `observations/20260414T233041Z_phase1_compare_after_reviewer_parser_fix_once/summary.csv` に保存されている。

なお、`r_single` は前回の中断時に途中まで動いていたため、重複してAPIを叩かない方針で再実行していない。そのため、この表では single-agent は5本、multi-agent は6本の結果として読む。

| Scenario | single-agent | multi-agent | multi-agent の補足 |
| --- | --- | --- | --- |
| `i2` | failure | success | turn 3、replan 2、reviewer `retry` |
| `m` | failure | success | turn 3、replan 2、reviewer `retry` |
| `n` | failure | success | turn 2、replan 1、reviewer `retry` |
| `o` | failure | failure | turn 3、replan 2、reviewer `retry`、`max_turns_reached` |
| `r` | not rerun | failure | turn 3、replan 2、reviewer `retry`、`max_turns_reached` |
| `u` | failure | failure | turn 3、replan 2、reviewer invocation failed、`max_turns_reached` |

この2回目テストでは、single-agent は確認済み5本すべて失敗、multi-agent は 3/6 成功だった。parser 修正により、`i2/m/n/o/r` では reviewer の `retry` が保存済み履歴にも正しく反映されるようになった。特に `m` は前回 `judge_stop` で止まっていたが、今回は reviewer の retry が効き、3ターン目まで進んで成功している。

一方で、multi-agent 全体の成功率は前回の 5/6 から 3/6 に下がった。これは parser 修正そのものの悪化というより、LLM planner の出力ぶれとターン上限の影響が大きい。`o` は reviewer が正しく `retry` を返していたが、planner が2ターン目で scope 外の `rebuild_compose_service` を含めたため precheck で弾かれ、3ターン目もDB auth修復に留まって `max_turns_reached` になった。`r` は3段 cascade の最後の query bug まで到達したが、3ターン上限内で成功判定まで届かなかった。`u` は reviewer 呼び出し自体が2回とも失敗し、judge が retry に override したものの、初期の network topology fault を正しく掴みきれず `max_turns_reached` になった。

まとめると、今回の修正で「reviewer が正しい retry を返しているのに parser が stop 扱いに落とす」問題は解消した。ただし Phase 2 前にさらに安定化するなら、次の焦点は parser ではなく、planner の scope 遵守、turn 上限、reviewer API invocation failure の扱いになる。

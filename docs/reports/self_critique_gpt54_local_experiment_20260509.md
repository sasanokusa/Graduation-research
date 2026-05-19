# GPT-5.4 self-critique 局所実験レポート

作成日: 2026-05-09

対象は `m/n/o/r/u/v/w/x` の8シナリオで、single-agent iterative self-critique baseline を OpenAI `gpt-5.4` で各1回ずつ走らせた局所実験である。目的は、前回の `gpt-5.4-mini` 実験で見えた「自己反省はするが、cascade 後段の query bug で安全な patch に踏み切れず空プラン化する」挙動が、より賢いモデルで改善するかを確認することである。

## 前提

- 実験結果は `observations/20260509T032704Z_selfcritique_openai_gpt54_mnoru_vwx_once/summary.csv` を主結果として扱う。
- 同時刻付近の `observations/20260509T032616Z_selfcritique_openai_gpt54_mnoru_vwx_once/` は Docker daemon に接続できず `reset.sh` で失敗した予備実行であり、本集計から除外する。
- 比較対象は `observations/20260419T124231Z_selfcritique_openai_mnoru_vwx_once/summary.csv` の `gpt-5.4-mini` self-critique 実験である。
- 実行時の `SINGLE_AGENT_PROVIDER` は `openai`、`SINGLE_AGENT_MODEL` は `gpt-5.4`、`MULTI_AGENT_MAX_TURNS` は `5` である。
- `prompt-mode` は `blind`、`scenario-mode` は `forced`、entrypoint は `self_critique_agent.py` である。
- 料金は OpenAI API の標準オンデマンド単価による概算であり、税、為替、無料枠、キャッシュ、Batch、Priority、リージョン上乗せは含めない。
- 2026-05-09 時点の OpenAI 公式モデルページでは、`gpt-5.4` は input $2.50 / 1M tokens、output $15.00 / 1M tokens、`gpt-5.4-mini` は input $0.75 / 1M tokens、output $4.50 / 1M tokens とされている。

実行コマンド:

```bash
env SINGLE_AGENT_PROVIDER=openai SINGLE_AGENT_MODEL=gpt-5.4 MULTI_AGENT_MAX_TURNS=5 \
  ./observe_runs.sh m n o r u v w x \
  --agent-entrypoint self_critique_agent.py \
  --worker llm \
  --prompt-mode blind \
  --scenario-mode forced \
  --repeat 1 \
  --python ./.venv/bin/python \
  --label selfcritique_openai_gpt54_mnoru_vwx_once
```

集計コマンド:

```bash
./.venv/bin/python aggregate_observations.py \
  observations/20260509T032704Z_selfcritique_openai_gpt54_mnoru_vwx_once/summary.csv \
  --group-by scenario \
  --show-overall \
  --show-failure-breakdown

./.venv/bin/python aggregate_hypothesis_metrics.py \
  observations/20260509T032704Z_selfcritique_openai_gpt54_mnoru_vwx_once/summary.csv \
  --output observations/20260509T032704Z_selfcritique_openai_gpt54_mnoru_vwx_once/hypothesis_metrics.csv
```

## 結果

| Scenario | 結果 | turn | self-critique 回数 | stop reason | detected fault | elapsed |
| --- | --- | ---: | ---: | --- | --- | ---: |
| `m` | failure | 4 | 4 | `self_critique_stop` | `query_bug_front` | 158.836s |
| `n` | failure | 3 | 3 | `self_critique_stop` | `application_query_or_schema_mismatch` | 110.271s |
| `o` | failure | 3 | 3 | `self_critique_stop` | `application_query_bug` | 100.781s |
| `r` | failure | 2 | 2 | `self_critique_stop` | `application_db_auth_misconfiguration` | 134.140s |
| `u` | failure | 3 | 3 | `self_critique_stop` | `application_query_bug` | 99.449s |
| `v` | success | 1 | 0 | `success` | `topology_or_service_discovery_fault` | 13.314s |
| `w` | success | 1 | 0 | `success` | `failover_contract_mismatch` | 13.309s |
| `x` | success | 1 | 0 | `success` | `failover_contract_mismatch` | 13.111s |

成功率は 3/8 だった。成功したのは `v/w/x` の topology / contract mismatch 系であり、`m/n/o/r/u` の cascade 系はすべて失敗した。

失敗内訳は次のとおりである。

| Bucket | 件数 | Scenario |
| --- | ---: | --- |
| `planner_reasoning_failure` | 4 | `m/n/o/u` |
| `postcheck_failure` | 1 | `r` |

`m/n/o/u` は、いずれも後段の `appdb.itemz` missing table evidence まで到達したが、`app/main.py` の exact substring が観測 payload に見えていないことを理由に空プランを返して停止した。`r` は依存修復後に DB auth drift まで進み、`app/app.env` の restore と app rebuild を実行したが、最終 postcheck は query bug 露出後に失敗した。

## コスト概算

今回の `gpt-5.4` self-critique 実験の token usage は以下である。

| Model | input tokens | output tokens | total tokens | 概算コスト |
| --- | ---: | ---: | ---: | ---: |
| `gpt-5.4` | 71,078 | 2,201 | 73,279 | $0.2107 |

| 指標 | 値 |
| --- | ---: |
| 8シナリオ1セットあたり | $0.2107 |
| 1シナリオ平均 | $0.0263 |
| 成功1件あたり | $0.0702 |

前回の `gpt-5.4-mini` self-critique 実験は input 92,060 / output 2,228 tokens で、当時と同じ定価換算では $0.0791 だった。今回の `gpt-5.4` は token 総量は 94,288 から 73,279 へ減ったが、単価差により概算コストは約 2.7 倍になった。

## `gpt-5.4-mini` との比較

| Scenario | `gpt-5.4-mini` | `gpt-5.4` | 比較メモ |
| --- | --- | --- | --- |
| `m` | failure | failure | `gpt-5.4` は nginx、DB auth、query bug まで段階的に進み、mini より深く到達した。ただし最終的には exact code snippet 不足で空プラン停止。 |
| `n` | failure | failure | 両者とも startup 復旧後の `appdb.itemz` で停止。`gpt-5.4` も安全な `replace_text` 対象が見えないとして空プラン化した。 |
| `o` | failure | failure | `gpt-5.4` は DB auth 修復後の query bug まで到達したが、mini と同様に code edit に踏み切れなかった。 |
| `r` | failure | failure | mini は query/schema mismatch まで到達して空プラン停止。`gpt-5.4` は今回 DB auth 修復 turn の postcheck failure で止まり、最後の code fix までは進まなかった。 |
| `u` | failure | failure | 両者とも DB_HOST / topology 修復後に query bug まで到達し、`app/main.py` の exact substring 不足で停止。 |
| `v` | success | success | どちらも `CACHE_HOST=cache-missing` を `cache` に戻して1ターン成功。 |
| `w` | success | success | どちらも `CACHE_HOST=queue` を `cache` に戻して1ターン成功。 |
| `x` | success | success | mini は2ターン、`gpt-5.4` は1ターンで成功。`gpt-5.4` は `app/app.env` の base restore を選び、bilateral drift を一括で解消した。 |

定量的には、成功率はどちらも 3/8 で変わらなかった。一方で、`m` では `gpt-5.4-mini` が初段 nginx 周辺で止まったのに対し、`gpt-5.4` は query bug まで到達したため、診断の深さは改善している。ただし、最終的な full recovery にはつながらなかった。

## シナリオ別メモ

### `m`

1ターン目で nginx upstream host mismatch を直し、2ターン目で DB auth drift を直し、3ターン目で `appdb.itemz` missing table まで到達した。self-critique は3ターン目で「この問題は in-scope であり app/main.py を直すべき」と retry を返している。しかし planner は `app/main.py` の exact faulty line が見えないことを理由に空プランを返し、4ターン目でも同じ空プランを繰り返したため self-critique が stop した。

評価としては、段階的な仮説遷移はかなり良い。失敗原因は root cause の見落としではなく、観測境界と action schema の制約下で、証拠不足を過度に安全側へ倒したことである。

### `n`

1ターン目で `uvicorn` 欠落を直し、app startup は復旧した。その後 `/api/items` の `appdb.itemz` missing table が露出したが、2ターン目以降は exact source snippet 不足を理由に空プラン化した。mini とほぼ同じ failure mode である。

### `o`

1ターン目で DB credential drift を修復し、`/healthz` は成功した。その後 `appdb.itemz` missing table が露出したが、`app/main.py` の actual SQL line が見えないため空プランで停止した。stale nginx evidence には引っ張られておらず、前面障害の見極めはできている。

### `r`

1ターン目で dependency failure を直し、2ターン目で DB auth drift を修復した。postcheck では `/healthz` が 200 になり、`/api/items` の query bug が露出したが、この時点で self-critique は「現在の validated scope では app/main.py が含まれない」と判断して stop した。`r` では multi-agent の reviewer / blackboard と比べ、次ターンの scope 拡張・再観測誘導が弱いことが見える。

### `u`

1ターン目で `DB_HOST=127.0.0.1` 系の topology fault を base restore で修復し、`/healthz` は成功した。その後 `appdb.itemz` missing table が露出したが、`m/n/o` と同じく `app/main.py` の exact substring 不足で空プラン停止した。

### `v`

`CACHE_HOST=cache-missing` と topology endpoint の `expected_host=cache` が直接見えていたため、`replace_text` で `CACHE_HOST=cache` に戻し、app rebuild で1ターン成功した。

### `w`

`CACHE_HOST=queue` が visible snippet と topology evidence の両方から確認でき、`CACHE_HOST=cache` への minimal patch で1ターン成功した。

### `x`

`CACHE_HOST=queue`、`QUEUE_HOST=cache`、`DEGRADED_MODE` 系の bilateral dependency drift を、`app/app.env` の `restore_from_base` と app rebuild で1ターン成功した。mini は2ターンだったため、ここは `gpt-5.4` の改善が見える。

## 所感

今回の結果は、「賢いモデルなら自己反省ループだけで cascade を解けるのではないか」という期待には否定的だった。`gpt-5.4` は mini より診断が深く、特に `m` では3層目の query bug まで到達した。しかし full recovery は増えず、成功率は前回と同じ 3/8 に留まった。

重要なのは、自己反省が無意味だったわけではない点である。self-critique は多くの turn で正しく retry を返し、前段修復によって新しい下流故障が露出したことを認識していた。問題は、その feedback を受けた planner が同じ情報境界の中で再び行動を選ぶため、`app/main.py` の exact line が見えない局面では「安全に patch できない」と判断して空プランに戻りやすいことである。

したがって、卒論上の整理としては次の主張が強い。

- `gpt-5.4` self-critique は mini より深い段階まで診断を進める場合がある
- しかし、自己反省だけでは action schema と観測境界による閉塞を破れない
- cascade 後段の full recovery には、追加観測、scope 更新、blackboard、外部 reviewer / judge のような制御構造が効く
- topology / contract mismatch のように fault と修復文字列が観測 payload に直接見えている場合は、self-critique 以前に single-agent でも十分解ける

結論として、`GPT-5.4` を使っても「頭のよさ」だけでは今回の self-critique baseline の弱点は解消しなかった。改善すべき対象はモデル単体ではなく、`app/main.py` の狭い追加観測を許可する設計、または reviewer guidance を planner の candidate scope / observation request に確実に反映する制御構造である。

## 価格ソース

- OpenAI: [GPT-5.4 model page](https://developers.openai.com/api/docs/models/gpt-5.4/)
- OpenAI: [GPT-5.4 mini model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini/)
- OpenAI: [API pricing](https://openai.com/api/pricing/)

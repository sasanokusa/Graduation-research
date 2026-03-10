# Safe Emergency Recovery Experiment Baseline

本リポジトリは、Docker Compose ベースの意図的に破壊可能な標的環境に対して、LLM が応急復旧を試みる研究評価基盤である。目的は本番運用ではなく、障害注入、観測、修復計画、検証、ロールバック、結果記録までを安全に反復実験することである。

今回の主系は、自由形式シェルコマンドをそのまま実行する PoC ではなく、構造化アクション、Verifier、Rollback を備えた単一エージェント版である。さらに現在は、内部ベンチマーク用の A-L シナリオ真値を保持しつつ、sensor / triage / planner 側は closed-set の scenario classifier ではなく、open-world の仮説生成器として動作する構成へ寄せている。

## 応急復旧の成功条件

本リポジトリにおける「応急復旧成功」は、元の構成を一字一句再現することではない。以下を満たし、かつ被害拡大を起こしていない状態を成功とみなす。

- シナリオごとに定義した主要ヘルスチェックが通る
- 主要 API が 200 を返す
- 許可されていないファイル変更や危険操作を行っていない
- 失敗時にロールバック可能な変更は自動で巻き戻される

シナリオごとの成功条件は [scenarios/definitions.yaml](/Users/ryoike/Documents/codex/scenarios/definitions.yaml) に定義している。

## 何を残したか

既存の標的環境と故障注入系は維持している。

- [docker-compose.yml](/Users/ryoike/Documents/codex/docker-compose.yml)
- [break.sh](/Users/ryoike/Documents/codex/break.sh)
- [reset.sh](/Users/ryoike/Documents/codex/reset.sh)
- [nginx/nginx.conf](/Users/ryoike/Documents/codex/nginx/nginx.conf)
- [app/main.py](/Users/ryoike/Documents/codex/app/main.py)
- [app/requirements.txt](/Users/ryoike/Documents/codex/app/requirements.txt)
- [app/app.env](/Users/ryoike/Documents/codex/app/app.env)

`break.sh` による A-L 障害注入と `reset.sh` による初期化手順は従来どおり利用できる。

## 現在の主系構成

```text
.
├── agent.py                      # 単一エージェント版の薄い入口
├── runners
│   └── run_single.py             # 構造化アクション方式の runner
├── agents
│   ├── mock_worker.py            # LLM 非依存の固定 plan
│   ├── sensor.py                 # 観測情報の収集
│   └── worker.py                 # Gemini による構造化アクション計画
├── core
│   ├── actions.py                # JSON プランの解析と整形
│   ├── executor.py               # whitelist 実行と rollback
│   ├── healthchecks.py           # docker / HTTP チェック
│   ├── policies.py               # 許可パスと許可アクション
│   ├── prompts.py                # prompt registry
│   ├── scenario_context.py       # internal -> worker-visible context の変換
│   ├── state.py                  # LangGraph state
│   ├── triage.py                 # auto mode の障害クラス推定と scope 提案
│   └── verifier.py               # pre/post check
├── scenarios
│   └── definitions.yaml          # シナリオ定義
├── results                       # 実験結果 JSON と backup
├── multi_agent.py                # 旧 PoC 系の参考実装
├── docker-compose.yml
├── break.sh
└── reset.sh
```

`multi_agent.py` は将来の拡張参考として残しているが、今回の安全な単一エージェント評価基盤の主系ではない。

## 現在のフロー

1. Sensor: `service_logs`, `http results`, `compose ps`, `relevant snippets`, `recent error excerpts`, `suspicious patterns`, `static observations` を収集する
2. Triage: 観測から抽象的な障害ドメイン仮説、confidence、evidence、candidate scope、missing evidence、recommended next observations を生成する
3. Additional Observation: triage が証拠不足を示した場合のみ、狭い log excerpt や file snippet を 1 回だけ追加取得する
4. Worker: true scenario ではなく triage の `suspected_domains` と `candidate_scope` を使って構造化アクションを計画する
5. Verifier: action の安全性と triage scope 逸脱を審査する
6. Executor / Postcheck / Rollback: 実行、段階的検証、必要時の巻き戻しを行う

## 許可アクション

LLM は自由なシェル文字列を返さない。代わりに、JSON で以下のアクション列を返す。

- `edit_file`
- `restart_compose_service`
- `rebuild_compose_service`
- `run_config_test`
- `run_health_check`

現在の単一ターン runner では `show_file` は許可していない。必要なファイル断片は Sensor が観測情報として先に収集し、Worker はそれを根拠に `replace_text` を組み立てる。
また、単一ターンの A シナリオでは `run_config_test` と `restart_compose_service` だけのプランは許可せず、snippet に誤設定行が見えている場合は `edit_file` を含むことを前提とする。

`edit_file` はさらに安全側へ限定している。

- 対象ファイルは `nginx/nginx.conf`, `app/main.py`, `app/requirements.txt`, `app/app.env` のみ
- 操作は `replace_text` または `restore_from_base`
- リポジトリ全体への一括置換は禁止
- `replace_text` は 1 箇所一致のみを許可する

## 禁止操作

Executor は構造化アクションを内部関数へ変換して実行する。任意シェル文字列は直接実行しない。

禁止対象の例:

- `rm`
- `sudo`
- `chmod`, `chown`
- `find`, `grep -rl`, `xargs` を使った横断編集
- ワイルドカードを用いた広域編集
- リポジトリ外パスの参照
- 任意の `shell=True` 実行

## Verifier の役割

Verifier は段階的検証を行う。

### Precheck

- candidate scope で許可されたファイルか
- candidate scope で許可されたアクションか
- triage が提案した `candidate_scope` を逸脱していないか
- シナリオで定義した `success_checks` 名が success-check registry に存在するか
- 変更差分が大きすぎないか
- `docker compose config` が通るか
- `nginx/nginx.conf` 編集時に自動 config test を差し込める前提か

Precheck 結果 JSON では以下を分離して保存する。

- `validated_actions`
- `validated_success_checks`
- `action_validation_errors`
- `scope_validation_errors`
- `success_check_validation_errors`
- `worker_normalization_errors`

### Postcheck

- `docker compose ps` によるサービス状態
- `http://localhost:8080/healthz`
- `http://localhost:8080/api/items`
- 直近ログの簡易確認
- シナリオごとの `success_checks`

`rebuild_compose_service app` を含む B/C/D/E/F/G 系では、コンテナ再作成直後にアプリケーションがまだ listen しておらず、一時的に 502 や connection refused が見えることがある。そのため postcheck は短い retry を伴う収束待ちを行ってから最終判定する。

## Rollback

`edit_file` 実行前には対象ファイルを `results/backups/` に退避する。以下のケースでロールバックが動作する。

- Executor 内のアクション実行で失敗した場合
- `nginx/nginx.conf` 編集後の自動 `nginx -t` に失敗した場合
- 実行は完了したが postcheck に失敗し、バックアップが残っている場合

ロールバック結果は結果 JSON に記録される。

## シナリオ定義

[scenarios/definitions.yaml](/Users/ryoike/Documents/codex/scenarios/definitions.yaml) には各シナリオの以下を記述している。

- `name`
- `description`
- `allowed_files`
- `allowed_actions`
- `success_checks`
- `failure_conditions`

現在は A-L の 11 シナリオを定義している。

## セットアップ

Python 3.12 を推奨する。Python 3.14 では LangChain 周辺の警告が出ることを確認している。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
export GOOGLE_API_KEY=YOUR_API_KEY
export GEMINI_MODEL=gemini-3-flash-preview
export GEMINI_PLANNER_TIMEOUT_SECONDS=75
export GEMINI_THINKING_LEVEL=low
```

既存の `.venv` が Python 3.14 系で作られている場合は、いったん削除して Python 3.12 で作り直す。

```bash
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
```

Gemini 3 Flash 系では planner timeout が起きうる。これは reasoning failure とは別であり、通信待ちや API 側の一時障害で落ちることがある。現行 baseline では以下の env を推奨する。

- `GEMINI_MODEL`: 既定は `gemini-3-flash-preview`
- `GEMINI_PLANNER_TIMEOUT_SECONDS`: 既定は `75`
- `GEMINI_THINKING_LEVEL`: 既定は `low`

`GEMINI_THINKING_LEVEL` は low-latency 用の簡易設定であり、`off`, `low`, `medium`, `high`, `default`、または thinking budget の整数値を受け付ける。

## Prompt Mode

単一エージェント worker の system prompt は実行時に切り替えられる。

- `blind`: 評価用のデフォルト。障害クラスやシナリオ名に寄ったヒントを system prompt に入れない
- `hinted`: 開発用。障害クラスに関する弱いヒントを system prompt に含める

管理は [core/prompts.py](/Users/ryoike/Documents/codex/core/prompts.py) の registry 経由で行う。将来 `strict`, `debug`, `fewshot` などを追加しやすい構造にしている。

## Auto Mode と Forced Mode

`agent.py` の `--scenario` は省略可能であり、デフォルトは `auto` である。

- `auto`:
  Sensor の次に TRIAGE を実行し、観測結果から抽象ドメイン仮説を生成する open-world mode である
- `a|b|c|d|e|f|g|h|i|k|l`:
  benchmark/debug 用の forced mode として evaluator 側の内部真値だけを固定する

TRIAGE の役割は、障害原因の真値を worker に直接渡すことではなく、観測から妥当と推定される障害ドメイン仮説と候補スコープを生成することである。true scenario の詳細説明は worker に渡さず、planner には triage が提案した抽象ドメイン、evidence、candidate scope だけを見せる。

TRIAGE の出力 schema は以下である。

- `suspected_domains`
  - `domain`
  - `confidence`
  - `evidence`
- `candidate_scope`
  - `files`
  - `services`
  - `allowed_actions`
- `missing_evidence`
- `recommended_next_observations`
- `ambiguity_level`
- `triage_summary`
- `current_state_evidence`
- `historical_evidence`

## Internal Definition と Worker-visible Context

内部評価に使うシナリオ定義と、worker に実際に見せる文脈は分離している。

- internal definition:
  [scenarios/definitions.yaml](/Users/ryoike/Documents/codex/scenarios/definitions.yaml) を source of truth とし、`description`, `success_checks`, `failure_conditions` などを verifier / evaluator が使う
- worker-visible context:
  [core/scenario_context.py](/Users/ryoike/Documents/codex/core/scenario_context.py) で triage output と観測情報から生成する

blind では worker に以下を見せる。

- `suspected_domains`
- `candidate_scope`
- `missing_evidence`
- `recommended_next_observations`
- `ambiguity_level`
- `triage_summary`
- `observation` の技術情報
  - `compose_ps`
  - `health_checks`
  - `file_snippets`
  - `relevant_log_excerpts`
  - `http_error_evidence`
  - `suspicious_patterns`
  - `static_observations`
  - `additional_observation`
  - `current_state_evidence`
  - `historical_evidence`
- 一般的な safety constraints

blind では worker に以下を渡さない。

- `description`
- `failure_conditions`
- `internal_scenario_id`
- benchmark-specific scenario A-L の意味づけ
- root cause を直接示す答え寄り説明文

hinted では internal definition をそのまま渡さず、worker-visible context に弱い運用ヒントだけを追加する。

Scenario C の blind 実行では、`app/app.env` の relevant snippet や app 側接続エラーの証拠が worker-visible context に出ていないと、安全に `edit_file` を提案しにくい。そのため current baseline は `DB_PASSWORD=...` の relevant snippet と、HTTP 500 応答本文や関連ログ断片を worker に渡し、正しい値が観測から直接分からない場合は `restore_from_base` を安全な復旧案として選べるようにしている。
また、Scenario C は env 修正だけでは不十分であり、修正後の `app` に設定を再読込させるため `rebuild_compose_service app` 相当の再作成が必要である。worker prompt でもこの一般則を明示し、executor 側も `app/app.env` 編集時には app の rebuild を自動追加または restart から upgrade する。
Scenario D/F/G では `app/main.py` の relevant snippet を worker-visible context に含め、局所コード障害や schema drift を evidence-backed に修正できるようにしている。Scenario E では `APP_PORT=...` と app log の listen port evidence を追加し、A と似た 502 でも competing repair choice が results JSON に残るようにしている。Scenario H では upstream block と location block の関係が見える nginx snippet と、`proxy_pass` 先が named upstream group でありうることを示す static observation を追加し、upstream group 名と Docker service 名の混同を減らしている。Scenario I では初段の port drift を優先的に見せつつ、追加観測や postcheck を通じて二段目の DB auth failure が露出しうる構成にしている。Scenario K では HTTP body を generic な `internal error` に抑え、追加観測で app log や狭い code snippet を取らないと真因が見えにくい。Scenario L では current-state evidence と historical evidence を分け、現在の app/query 障害と古い nginx upstream failure を区別して扱えるようにしている。

## 標的環境の起動と確認

```bash
docker compose up -d
curl http://localhost:8080/healthz
curl http://localhost:8080/api/items
```

## 故障注入

```bash
./break.sh a
./break.sh b
./break.sh c
./break.sh d
./break.sh e
./break.sh f
./break.sh g
./break.sh h
./break.sh i
./break.sh k
./break.sh l
```

内容:

- A: `nginx/nginx.conf` の upstream ポート誤設定
- B: `app/requirements.txt` から依存を削除
- C: `app/app.env` の DB パスワード誤設定
- D: `app/main.py` の items クエリを存在しないテーブル `itemz` へ変更
- E: `app/app.env` の `APP_PORT` を 9000 に変更し、nginx upstream と drift させる
- F: `app/main.py` の items クエリを存在しない列 `details` へ変更
- G: `app/main.py` の `/healthz` クエリだけを壊し、main API は生かす
- H: `nginx/nginx.conf` の upstream host 名を `backend` に壊す
- I: `app/app.env` の `APP_PORT` と `DB_PASSWORD` を同時に壊し、app 再作成で反映させる
- K: `app/main.py` を opaque 500 化し、HTTP body では真因を見えにくくする
- L: 一時的に nginx upstream failure を発生させて stale log を残した後、現在障害として `app/main.py` の query bug を残す

Scenario C は設定ファイルを書き換えるだけでは実行中プロセスに反映されない。そのため [break.sh](/Users/ryoike/Documents/codex/break.sh) は `app/app.env` を壊した後に `docker compose up -d --force-recreate app` を実行し、起動し直した app に誤設定を読み込ませる。さらに `/api/items` が失敗するまで短時間待機し、注入成功をログに出す。

Scenario C の注入確認を手動で見たい場合は以下を実行する。

```bash
./reset.sh
./break.sh c
curl http://localhost:8080/api/items
```

この `curl` は失敗する想定である。B/C/D/E/F/G/I/K/L のように app の再起動や再作成を伴う障害は、A よりも設定反映と収束待ちが重要になる。

## 追加シナリオ D-L

- D: `healthz_200` は通るが `api_items_200` だけ失敗する局所コード障害である。HTTP evidence に missing table が出る。
- E: nginx 側は 8000、app 側は 9000 を前提にしており、A に似た 502 でも port drift の切り分けが必要である。単一エージェントでは難しく、multi-agent 比較向けの難シナリオとして残している。
- F: `healthz_200` は通るが `api_items_200` だけ Unknown column で失敗する schema drift である。
- G: `api_items_200` は通るが `healthz_200` だけ失敗する partial failure である。
- H: port mismatch ではなく upstream host mismatch であり、nginx log に host resolution failure が出る。単一エージェントでは `backend` を upstream group 名と Docker service 名で混同しやすく、誤って `proxy_pass http://backend;` を書き換える failure mode がある。
- I: 二段階マスク障害であり、初期は upstream reachability failure が前面に出るが、port だけを戻すと DB auth failure が露出する。単一エージェントの一発修復では終わりにくい。
- K: opaque 500 であり、HTTP body だけでは root cause が弱く、app log や狭い code snippet の追加観測が必要になる。
- L: stale nginx upstream failure を recent logs に残しつつ、steady state の真因は app/query 側に置く。浅い triage は nginx に引っ張られやすい。

単一エージェントの mock worker では D/F/G/H/K/L は安定して復旧できる。E も mock では app 側の port restore で収束するが、LLM worker では competing repair choice がぶれやすい。I は意図的に部分修復で止まりやすく、single-turn planner の限界を観測するためのシナリオである。

open-world 単一エージェントの現状整理としては、A-G は比較的安定して解ける一方、H は文字列の多義性、I は partial repair 後の再計画、K は additional observation 必須、L は stale evidence 耐性が主な難所になる。

## 実験の回し方

### auto mode の最小例

```bash
docker compose up -d
./break.sh a
python agent.py --worker llm --prompt-mode blind
```

この形が default の運用であり、TRIAGE が open-world の障害ドメイン仮説を生成し、必要なら 1 回だけ追加観測を行ってから planner へ進む。

### forced mode の最小例

```bash
docker compose up -d
./break.sh a
python agent.py --scenario a --worker llm --prompt-mode blind
```

直接 runner を呼ぶ場合:

```bash
python runners/run_single.py --scenario auto --worker llm --prompt-mode blind
```

ヒントありで開発検証する場合:

```bash
python agent.py --worker llm --prompt-mode hinted
```

LLM 非依存で executor / verifier / rollback を検証したい場合:

```bash
./break.sh a
python agent.py --worker mock --prompt-mode blind
```

### 完全リセット

```bash
./reset.sh
```

## 結果記録

1 試行ごとに `results/` へ JSON を保存する。最低限、以下を記録する。

- `timestamp`
- `scenario`
- `requested_scenario`
- `scenario_source`
- `internal_scenario_id`
- `detected_fault_class`
- `detection_confidence`
- `detection_evidence`
- `triage_summary`
- `suspected_domains`
- `candidate_scope`
- `missing_evidence`
- `recommended_next_observations`
- `ambiguity_level`
- `additional_observation_used`
- `planner_input_scope`
- `worker_mode`
- `prompt_mode`
- `system_prompt_name`
- `planner_error_type`
- `planner_error_stage`
- `planner_retry_count`
- `planner_timeout_seconds`
- `planner_attempts`
- `planner_transport_failure`
- `planner_reasoning_failure`
- `planner_fallback_used`
- `planner_fallback_reason`
- `planner_fallback_type`
- `worker_context_mode`
- `worker_visible_context`
- `observation_additional`
- `observed_symptoms`
- `current_state_evidence`
- `historical_evidence`
- `triage_iterations`
- `triage_before_additional_observation`
- `triage_after_additional_observation`
- `worker_raw_output`
- `normalized_actions`
- `auto_appended_actions`
- `precheck_input_actions`
- `validated_actions`
- `validated_success_checks`
- `action_validation_errors`
- `success_check_validation_errors`
- `action_results`
- `readiness_wait_used`
- `readiness_attempts`
- `first_success_time_seconds`
- `verifier_precheck_result`
- `execution_result`
- `verifier_postcheck_result`
- `rollback_used`
- `rollback_result`
- `final_status`
- `elapsed_seconds`

`aggregate_observations.py` では open-world 向けに `domain_match_rate(%)` を集計する。これは injected scenario の内部真値を abstract domain へ写した期待値と、`detected_fault_class` の一致率である。旧来の scenario 文字との直接比較は `legacy_detect_match_rate(%)` として分離している。加えて `transport_failure_rate(%)` と `avg_planner_retries` を出し、planner transport failure を reasoning failure と分けて観測できる。

## 実装上の要点

- Sensor はログ丸投げではなく、`docker compose ps`、HTTP ヘルスチェック、サービス別ログ抜粋、`app/main.py` / `app/app.env` / `nginx/nginx.conf` の relevant snippet を構造化して Triage に渡す
- A シナリオでは `nginx/nginx.conf` の `server app:` 周辺断片も観測情報へ含め、Worker が `proxy_pass` を推測するのではなく実断片ベースで修正できるようにしている
- D/F/G では `app/main.py` の `cursor.execute(...)` 周辺、E では `APP_PORT=...` と app log の listen port evidence、H では upstream host resolution failure を観測情報へ含める
- worker-visible context は planner 安定性のために短く保ち、`compose ps` は要約、ログは relevant excerpt 中心、長い pip install ログは落とす
- TRIAGE は benchmark-specific scenario classifier ではなく、抽象ドメイン仮説生成器として振る舞う
- TRIAGE が証拠不足を返した場合のみ、追加観測ノードが狭い excerpt/snippet/config-test を 1 回だけ取得する
- worker は injected scenario の真値を知らず、`suspected_domains`, `candidate_scope`, `missing_evidence` だけを見る
- forced mode でも internal scenario label は evaluator 用にのみ保持し、worker-visible context には直接渡さない
- Sensor 時点ですでにシナリオ成功条件を満たしている場合は、worker を呼ばずにその場で成功として終了する
- app 再作成直後の一時的な 502/connection refused をそのまま planner に渡しにくくするため、sensor は短い stabilization wait を入れて再観測する
- `current_state_evidence` と `historical_evidence` を分けて保存し、L のような stale log 混入シナリオでは現在有効な症状と古いノイズを分離する
- K のような opaque 500 では triage が `missing_evidence` と `recommended_next_observations` を返し、追加観測で app log や狭い `app/main.py` snippet を補う
- I のような多段障害では、初段修復後に二段目の障害が露出しうることを postcheck と結果 JSON から追える
- H のような nginx 障害では、同じ文字列が upstream group 名と backend host/service 名の別レイヤで現れる可能性を prompt と観測に反映し、`proxy_pass` と upstream member を機械的に同一視しないようにしている
- Worker は Gemini を用いてシナリオ制約を含む JSON プランを返す
- Gemini 3 Flash 呼び出しは env で timeout / model / thinking level を調整でき、attempt ごとの elapsed time と exception を `planner_attempts` に記録する
- retry は transient transport failure に対してのみ行い、指数 backoff と jitter を使う
- `planner invocation failed` と `planner returned no executable actions` は別カテゴリで扱い、results JSON から transport failure と reasoning failure を区別できる
- 高信頼・低曖昧で snippet に直接 fault が見えている場合に限り、transport failure 時だけ strict fallback planner を使う
- fallback planner は shell を生成せず、既存の構造化 action だけを返す。通常経路では引き続き LLM を優先する
- `mock_worker.py` は A-L 向け固定 plan を返し、LLM なしで end-to-end を検証できる
- Executor は whitelist されたアクションのみ実行する
- `nginx/nginx.conf` を編集した場合、明示 action がなくても executor が自動で `nginx -t` を実行する
- Verifier は LLM を使わずルールベースで判定する
- Rollback は少なくとも `edit_file` 系で機能する

## 既知の制約

- 現状のシングルエージェントは 1 回の計画で復旧を試みる。自己反省ループはまだない
- `restore_from_base` はベースラインへ戻す単純操作であり、より細かいパッチ適用は未実装
- postcheck のログ判定は簡易的であり、履歴ログ由来のノイズを含むことがある
- `rebuild_compose_service` は現状 `docker compose up -d --force-recreate <service>` を指す
- Gemini API キー未設定時は安全側に倒して空プランとなり、precheck で停止する
- Gemini API timeout は推論失敗そのものではなく transport/invocation failure として別記録する。transient failure には retry をかけるが、恒久的障害やモデル側混雑時はなお失敗しうる
- strict fallback planner は高信頼・低曖昧・直接可視 fault というかなり狭い条件でのみ発動する。未知障害や曖昧ケースを解く一般解ではない
- mock worker は A-L の固定 plan を持つが、E は LLM で competing repair choice がぶれうる難シナリオとして残している
- auto mode の triage は open-world 前提で候補集合を広めに返すため、candidate scope は benchmark-specific optimum より広いことがある
- additional observation は 1 回までであり、それでも証拠が足りない場合は planner が empty plan を返すことがある

## 次にマルチエージェント化するときの拡張ポイント

- `agents/worker.py` を planner / fixer / reviewer に分割する
- `core/verifier.py` の postcheck 結果を reviewer エージェントへ渡す
- `scenarios/definitions.yaml` をより詳細なプレイブック記述へ拡張する
- `results/` の JSON を複数試行比較用に集計しやすい形式へ寄せる
- 既存の `multi_agent.py` は参考実装として置いているため、段階的に新 `core/` 系へ寄せていく

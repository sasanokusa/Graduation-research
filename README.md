# Safe Emergency Recovery Experiment Baseline

本リポジトリは、Docker Compose ベースの意図的に破壊可能な標的環境に対して、LLM が応急復旧を試みる研究評価基盤である。目的は本番運用ではなく、障害注入、観測、修復計画、検証、ロールバック、結果記録までを安全に反復実験することである。

今回の主系は、自由形式シェルコマンドをそのまま実行する PoC ではなく、構造化アクション、Verifier、Rollback を備えた単一エージェント版である。

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

`break.sh` による A/B/C 障害注入と `reset.sh` による初期化手順は従来どおり利用できる。

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

1. Sensor: `service_logs`, `http results`, `compose ps`, `relevant snippets`, `suspicious patterns` を収集する
2. Triage: 観測から `suspected_fault_class`, `confidence`, `evidence`, `proposed_scope`, `alternatives` を生成する
3. Worker: true scenario ではなく triage の `proposed_scope` を使って構造化アクションを計画する
4. Verifier: action の安全性と triage scope 逸脱を審査する
5. Executor / Postcheck / Rollback: 実行、段階的検証、必要時の巻き戻しを行う

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

- 対象ファイルは `nginx/nginx.conf`, `app/requirements.txt`, `app/app.env` のみ
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

- シナリオで許可されたファイルか
- シナリオで許可されたアクションか
- triage が提案した `proposed_scope` を逸脱していないか
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

`rebuild_compose_service app` を含む B/C 系では、コンテナ再作成直後にアプリケーションがまだ listen しておらず、一時的に 502 や connection refused が見えることがある。そのため postcheck は短い retry を伴う収束待ちを行ってから最終判定する。

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

現在は A/B/C の 3 シナリオを定義している。

## セットアップ

Python 3.12 を推奨する。Python 3.14 では LangChain 周辺の警告が出ることを確認している。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
export GOOGLE_API_KEY=YOUR_API_KEY
```

既存の `.venv` が Python 3.14 系で作られている場合は、いったん削除して Python 3.12 で作り直す。

```bash
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
```

## Prompt Mode

単一エージェント worker の system prompt は実行時に切り替えられる。

- `blind`: 評価用のデフォルト。障害クラスやシナリオ名に寄ったヒントを system prompt に入れない
- `hinted`: 開発用。障害クラスに関する弱いヒントを system prompt に含める

管理は [core/prompts.py](/Users/ryoike/Documents/codex/core/prompts.py) の registry 経由で行う。将来 `strict`, `debug`, `fewshot` などを追加しやすい構造にしている。

## Auto Mode と Forced Mode

`agent.py` の `--scenario` は省略可能であり、デフォルトは `auto` である。

- `auto`:
  Sensor の次に TRIAGE を実行し、観測結果から `a/b/c/unknown` をルールベースで推定する
- `a|b|c`:
  開発・デバッグ用の forced mode としてその scenario を強制する

TRIAGE の役割は、障害原因の真値を worker に直接渡すことではなく、観測から妥当と推定される fault class に基づいて、編集可能範囲と許可アクションを安全側に絞ることである。true scenario の詳細説明は worker に渡さず、planner には triage が提案した scope だけを見せる。

TRIAGE の出力 schema は以下である。

- `suspected_fault_class`
- `confidence`
- `evidence`
- `proposed_scope`
- `alternatives`

## Internal Definition と Worker-visible Context

内部評価に使うシナリオ定義と、worker に実際に見せる文脈は分離している。

- internal definition:
  [scenarios/definitions.yaml](/Users/ryoike/Documents/codex/scenarios/definitions.yaml) を source of truth とし、`description`, `success_checks`, `failure_conditions` などを verifier / evaluator が使う
- worker-visible context:
  [core/scenario_context.py](/Users/ryoike/Documents/codex/core/scenario_context.py) で triage output と観測情報から生成する

blind では worker に以下を見せる。

- `allowed_actions`
- `editable_files`
- `triage`
  - `suspected_fault_class`
  - `confidence`
  - `evidence`
  - `proposed_scope`
  - `alternatives`
- `observation` の技術情報
  - `compose_ps`
  - `service_logs`
  - `health_checks`
  - `file_snippets`
  - `relevant_log_excerpts`
  - `http_error_evidence`
  - `suspicious_patterns`
- 一般的な safety constraints

blind では worker に以下を渡さない。

- `description`
- `failure_conditions`
- scenario A/B/C の意味づけ
- root cause を直接示すラベルや説明文

hinted では internal definition をそのまま渡さず、worker-visible context に弱い運用ヒントだけを追加する。

Scenario C の blind 実行では、`app/app.env` の relevant snippet や app 側接続エラーの証拠が worker-visible context に出ていないと、安全に `edit_file` を提案しにくい。そのため current baseline は `DB_PASSWORD=...` の relevant snippet と、HTTP 500 応答本文や関連ログ断片を worker に渡し、正しい値が観測から直接分からない場合は `restore_from_base` を安全な復旧案として選べるようにしている。
また、Scenario C は env 修正だけでは不十分であり、修正後の `app` に設定を再読込させるため `rebuild_compose_service app` 相当の再作成が必要である。worker prompt でもこの一般則を明示し、executor 側も `app/app.env` 編集時には app の rebuild を自動追加または restart から upgrade する。

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
```

内容:

- A: `nginx/nginx.conf` の upstream ポート誤設定
- B: `app/requirements.txt` から依存を削除
- C: `app/app.env` の DB パスワード誤設定

Scenario C は設定ファイルを書き換えるだけでは実行中プロセスに反映されない。そのため [break.sh](/Users/ryoike/Documents/codex/break.sh) は `app/app.env` を壊した後に `docker compose up -d --force-recreate app` を実行し、起動し直した app に誤設定を読み込ませる。さらに `/api/items` が失敗するまで短時間待機し、注入成功をログに出す。

Scenario C の注入確認を手動で見たい場合は以下を実行する。

```bash
./reset.sh
./break.sh c
curl http://localhost:8080/api/items
```

この `curl` は失敗する想定である。B/C のように app の再起動や再作成を伴う障害は、A よりも設定反映と収束待ちが重要になる。

## 実験の回し方

### auto mode の最小例

```bash
docker compose up -d
./break.sh a
python agent.py --worker llm --prompt-mode blind
```

この形が default の運用であり、TRIAGE が A/B/C/unknown を自動推定して処理を進める。

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
- `detected_scenario`
- `detection_confidence`
- `detection_evidence`
- `proposed_scope`
- `alternative_candidates`
- `triage_policy`
- `worker_mode`
- `prompt_mode`
- `system_prompt_name`
- `worker_context_mode`
- `worker_visible_context`
- `observed_symptoms`
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

## 実装上の要点

- Sensor はログ丸投げではなく、`docker compose ps`、HTTP ヘルスチェック、サービス別ログ抜粋、許可ファイル一覧を構造化して Worker に渡す
- A シナリオでは `nginx/nginx.conf` の `server app:` 周辺断片も観測情報へ含め、Worker が `proxy_pass` を推測するのではなく実断片ベースで修正できるようにしている
- Sensor 時点ですでにシナリオ成功条件を満たしている場合は、worker を呼ばずにその場で成功として終了する
- Worker は Gemini を用いてシナリオ制約を含む JSON プランを返す
- Gemini 呼び出しにはタイムアウトと低い retry 上限を設定し、外部 API 待ちで長時間ハングしないようにしている
- `mock_worker.py` は A シナリオ向け固定 plan を返し、LLM なしで end-to-end を検証できる
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
- mock worker は現状 A シナリオのみ固定 plan を持つ

## 次にマルチエージェント化するときの拡張ポイント

- `agents/worker.py` を planner / fixer / reviewer に分割する
- `core/verifier.py` の postcheck 結果を reviewer エージェントへ渡す
- `scenarios/definitions.yaml` をより詳細なプレイブック記述へ拡張する
- `results/` の JSON を複数試行比較用に集計しやすい形式へ寄せる
- 既存の `multi_agent.py` は参考実装として置いているため、段階的に新 `core/` 系へ寄せていく

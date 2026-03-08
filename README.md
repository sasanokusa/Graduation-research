# LLM自律型インフラ自動修復システム用テスト環境

意図的に破壊できる Docker Compose ベースの標的環境と、それを外部から観測・修復する LangGraph ベースの単一エージェントを同居させた実験用リポジトリである。目的は本番運用ではなく、障害注入、ログ取得、LLM による修復コマンド提案、修復実行のベースラインを素早く検証することである。

## 構成

- フェーズ1: `nginx` `app` `db` の 3 コンテナからなる標的環境
- フェーズ2: `agent.py` による単一エージェントの一本道ワークフロー
- 破壊スクリプト: `break.sh`
- 復元スクリプト: `reset.sh`

## ディレクトリ構成

```text
.
├── agent.py
├── app
│   ├── app.env
│   ├── app.env.base
│   ├── main.py
│   ├── requirements.txt
│   └── requirements.txt.base
├── break.sh
├── db
│   ├── init.sql
│   └── mysql.env
├── docker-compose.yml
├── nginx
│   ├── nginx.conf
│   └── nginx.conf.base
├── requirements_agent.txt
└── reset.sh
```

## フェーズ1: 標的環境

### 概要

Nginx が FastAPI にリバースプロキシし、FastAPI が MySQL からデータを取得して JSON を返す。設定ファイルやアプリコードはホスト側からマウントしているため、外部 AI エージェントがホストOS上のファイルを直接修正できる。

### 起動

```bash
docker compose up -d
```

### 動作確認

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/api/items
```

正常時は `api/items` で初期データ 1 件を含む JSON が返る。

### 障害注入

ランダム注入:

```bash
./break.sh
```

パターン指定:

```bash
./break.sh a
./break.sh b
./break.sh c
```

故障パターン:

- A: `nginx/nginx.conf` の upstream ポートを `8000` から `8001` に変更し、`502 Bad Gateway` を発生させる
- B: `app/requirements.txt` から `uvicorn` を削除し、アプリ再作成時に起動エラーを発生させる
- C: `app/app.env` の `DB_PASSWORD` を誤値へ変更し、DB 接続エラーを発生させる

`break.sh` は実行前に `*.base` から設定を復元するため、障害の重ね掛けを避けられる。

### 初期状態への復元

完全リセット:

```bash
./reset.sh
```

`reset.sh` は以下をまとめて行う。

1. `nginx/nginx.conf`、`app/requirements.txt`、`app/app.env` を `*.base` から復元
2. `docker compose down -v` でコンテナ停止と MySQL ボリューム削除
3. `docker compose up -d` で再起動

手動で実施する場合:

```bash
cp nginx/nginx.conf.base nginx/nginx.conf
cp app/requirements.txt.base app/requirements.txt
cp app/app.env.base app/app.env
docker compose down -v
docker compose up -d
```

## フェーズ2: LangGraph 単一エージェント

### 概要

`agent.py` は以下の直線ワークフローを実装している。

1. `sensor_node`: `docker compose logs --tail=50 nginx app db` でログを取得
2. `worker_node`: Gemini にログを渡し、修復コマンドを 1 本だけ提案させる
3. `executor_node`: 提案コマンドをホストOS上で実行する

LLM には `langchain-google-genai` を介して Google Gemini を利用している。現在のモデル指定は `gemini-3-flash-preview` である。

### エージェントのセットアップ

Python 3.12 または 3.13 を推奨する。Python 3.14 では LangChain Core 由来の警告が出ることを確認している。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
export GOOGLE_API_KEY=YOUR_API_KEY
```

### エージェントの実行

標的環境を起動した状態で以下を実行する。

```bash
python agent.py
```

出力はフェーズごとに整形され、以下を順に確認できる。

- SENSOR NODE: 取得したログの末尾
- WORKER NODE: Gemini が提案したコマンド
- EXECUTOR NODE: 実行の成功/失敗と標準出力・標準エラー出力

### 現在の安全制約

`worker_node` のシステムプロンプトには、広域破壊を避けるために以下の制約を入れている。

- macOS 標準ツールと BSD 系 `sed` の構文を前提とする
- 修正対象は `./nginx/nginx.conf` のみとする
- `grep -rl` や `find` を使ったリポジトリ全体の横断書き換えを禁止する

このため、現時点のフェーズ2エージェントは主に故障パターン A の検証向けであり、パターン B/C の自律修復まではまだ対象にしていない。

## 実験向けメモ

- 外部エージェントが直接編集しやすい修復対象は `nginx/nginx.conf`、`app/requirements.txt`、`app/app.env`、`app/main.py` である
- DB の初期データは `db/init.sql` で投入され、`docker compose down -v` 後の再起動で再生成される
- MySQL の状態を完全に戻すには named volume を削除する必要があるため、完全リセットには `down -v` が必要である
- 現在の `agent.py` は安全のため修正範囲を `nginx/nginx.conf` に限定している

今後も完成し次第フェーズのアップデートを予定している

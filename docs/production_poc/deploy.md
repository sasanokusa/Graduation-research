# Production PoC 導入手順

## 1. 概要

この手順書は、既存の Docker ベース研究用 flow を壊さずに、Ubuntu Server へ隔離された production PoC を導入するためのものです。

## 2. 前提条件

- Ubuntu Server
- Python 3.12 以上
- `systemd`, `journalctl`, `ss`, `curl`, `df` が利用可能
- 対象 service log を読める権限
- Discord 通知を使う場合は webhook URL
- `infra-poc` のような専用 service account

## 3. リポジトリ配置

```bash
sudo mkdir -p /opt/infra-emergency-recovery
sudo chown "$USER":"$USER" /opt/infra-emergency-recovery
git clone <repo-url> /opt/infra-emergency-recovery
cd /opt/infra-emergency-recovery
```

## 4. 実行環境の準備

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
```

## 5. PoC 設定ファイルの作成

```bash
sudo mkdir -p /etc/infra-production-poc
sudo cp experimental/production_poc/config/production_poc.example.yaml /etc/infra-production-poc/production_poc.yaml
sudo cp experimental/production_poc/.env.example /etc/infra-production-poc/production_poc.env
sudo chmod 600 /etc/infra-production-poc/production_poc.env
```

`/etc/infra-production-poc/production_poc.yaml` は次を実ホストに合わせて修正してください。

- `services.web.service_name`
- `services.minecraft.service_name`
- Web health URL
- access log / error log path
- Minecraft log path
- 初回は `actions.mode: propose-only`
- 意図して provider key を入れるまで `llm.enabled: false`

`/etc/infra-production-poc/production_poc.env` では次を設定します。

- `DISCORD_WEBHOOK_URL=...`
- LLM を有効にする場合のみ `OPENAI_API_KEY=...` など

## 6. 状態保存ディレクトリ作成

```bash
sudo mkdir -p /var/lib/infra-production-poc
sudo chown -R infra-poc:infra-poc /var/lib/infra-production-poc
```

## 7. 初回 discovery 実行

timer を有効化する前に、まず discovery を手動実行します。

```bash
sudo -u infra-poc /opt/infra-emergency-recovery/.venv/bin/python \
  -m experimental.production_poc.runtime_prod.main \
  --config /etc/infra-production-poc/production_poc.yaml \
  --env-file /etc/infra-production-poc/production_poc.env \
  discover
```

設定した `state_dir` 以下に次が作られます。

- `latest_snapshot.json`
- `latest_snapshot.md`
- timestamp 付き snapshot archive

## 8. dry-run / propose-only 初回確認

初回は `actions.mode: propose-only` のまま 1 回監視を実行します。

```bash
sudo -u infra-poc /opt/infra-emergency-recovery/.venv/bin/python \
  -m experimental.production_poc.runtime_prod.main \
  --config /etc/infra-production-poc/production_poc.yaml \
  --env-file /etc/infra-production-poc/production_poc.env \
  monitor-once
```

確認ポイントは次です。

- Discord の起動通知、監視開始通知、異常通知が読みやすい
- 検出された Web service と Minecraft service が実環境と一致する
- 自動 restart が走らない
- 異常時だけ incident JSON が保存される

## 9. execute モード移行

propose-only の確認後にのみ execute へ進みます。

1. Keep `allowed_restart_services` small and explicit.
2. Change `actions.mode` to `execute`.
3. Re-run `monitor-once`.
4. Verify that only the intended service names can be restarted.

service 名に広い指定や wildcard は入れないでください。

## 10. systemd service / timer 化

まず次の雛形を実環境向けに見直します。

- `experimental/production_poc/deploy/production-poc-monitor.service`
- `experimental/production_poc/deploy/production-poc-monitor.timer`

その後、以下で配置します。

```bash
sudo cp experimental/production_poc/deploy/production-poc-monitor.service /etc/systemd/system/
sudo cp experimental/production_poc/deploy/production-poc-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now production-poc-monitor.timer
```

## 11. 停止方法

```bash
sudo systemctl stop production-poc-monitor.timer
sudo systemctl stop production-poc-monitor.service
```

## 12. ログの見方

- `journalctl -u production-poc-monitor.service -n 100 --no-pager`
- 設定した `state_dir`
- 相関 ID 付き Discord 通知
- 対象 service の journal:

```bash
journalctl -u nginx -n 100 --no-pager
journalctl -u minecraft -n 100 --no-pager
```

## 13. セキュリティ上の注意

- env file は管理者か専用 service account のみが読めるようにする
- 必要な log と command だけにアクセスできる専用 user を推奨
- `NoNewPrivileges=true` を維持する
- 明示した state directory 以外に書き込み権限を広げない

## 14. バックアップ未整備環境での注意

この PoC は、バックアップや snapshot が弱い、または未整備な環境を前提にしています。

- 既定は `propose-only` のままにする
- `execute` は明示的な実験モードとして扱う
- 実 snapshot 機構が入るまで、config edit、package 管理、file delete、host-wide change を allowlist に追加しない

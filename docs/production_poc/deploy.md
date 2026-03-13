# Production PoC 導入手順

## 1. 概要

この手順書は、既存の Docker ベース研究用 flow を壊さずに、Ubuntu Server へ隔離された production PoC を導入するためのものです。

## 2. 前提条件

- Ubuntu Server
- Python 3.12 以上
- `systemd`, `journalctl`, `ss`, `curl`, `df` が利用可能
- 対象 service log を読める権限
- Discord 通知を使う場合は webhook URL
- 監視実行用の専用 service account を作成するか、既存の安全な service account を 1 つ決めておく

## 3. 専用ユーザーの作成

`infra-poc` は例示名であり、Ubuntu に最初から存在するユーザーではありません。

新規に専用ユーザーを作る場合の例:

```bash
sudo useradd \
  --system \
  --create-home \
  --home-dir /var/lib/infra-production-poc \
  --shell /usr/sbin/nologin \
  --user-group \
  infra-poc
```

確認:

```bash
id infra-poc
getent passwd infra-poc
```

既存ユーザーを使う場合:

- この手順書中の `infra-poc` をそのユーザー名に置き換える
- `production-poc-monitor.service` の `User=` と `Group=` も同じ名前に修正する

## 4. リポジトリ配置

```bash
sudo mkdir -p /opt/infra-emergency-recovery
sudo chown "$USER":"$USER" /opt/infra-emergency-recovery
git clone <repo-url> /opt/infra-emergency-recovery
cd /opt/infra-emergency-recovery
```

注意:

- `.gitignore` により `.venv/` はリポジトリへ含まれません
- `.env`, `.env.*` も原則リポジトリに含まれません
- そのため、仮想環境と secrets を含む env file は配備先 Ubuntu Server 上で必ず手動作成してください

## 5. 実行環境の準備

この手順で `/opt/infra-emergency-recovery/.venv` を新規作成します。clone 直後のリポジトリには `.venv` は存在しません。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_agent.txt
```

作成確認:

```bash
test -x /opt/infra-emergency-recovery/.venv/bin/python
```

モジュール起動時の注意:

- `experimental.production_poc...` はリポジトリ直下を Python import path に含める必要があります
- 手動実行では、`cd /opt/infra-emergency-recovery` してから起動するか、`PYTHONPATH=/opt/infra-emergency-recovery` を付けて実行してください

## 6. PoC 設定ファイルの作成

```bash
sudo mkdir -p /etc/infra-production-poc
sudo cp experimental/production_poc/config/production_poc.example.yaml /etc/infra-production-poc/production_poc.yaml
sudo cp experimental/production_poc/.env.example /etc/infra-production-poc/production_poc.env
sudo chown root:infra-poc /etc/infra-production-poc/production_poc.yaml
sudo chmod 640 /etc/infra-production-poc/production_poc.yaml
sudo chown root:infra-poc /etc/infra-production-poc/production_poc.env
sudo chmod 640 /etc/infra-production-poc/production_poc.env
```

`infra-poc` を使わない場合は、ここも実際に使う service account のグループ名へ置き換えてください。

重要:

- `production_poc.env` は監視実行ユーザーが読める必要があります
- `chmod 600` のままだと root 以外は読めず、`PermissionError` になります
- 推奨は `root:<service-account-group>` と `640` です

`/etc/infra-production-poc/production_poc.yaml` は次を実ホストに合わせて修正してください。

- `services.web.service_name`
- `services.minecraft.management_mode`
- `services.minecraft.service_name`
- `services.minecraft.working_directory`
- `services.minecraft.startup_script_path`
- Web health URL
- access log / error log path
- Minecraft log path
- 初回は `actions.mode: propose-only`
- 意図して provider key を入れるまで `llm.enabled: false`

Minecraft が `tmux` や `start-server.sh` で動いている場合は、次のように設定してください。

- `services.minecraft.management_mode: shell_script` または `tmux`
- `services.minecraft.service_name: ""`
- `services.minecraft.working_directory` にサーバーディレクトリを入れる
- `services.minecraft.startup_script_path` に `start-server.sh` を入れる

この PoC は安全上の理由から、`shell script` / `tmux` 管理の Minecraft を自動起動しません。
この情報は Discord 通知や手動復旧時の参照情報として使われます。

`actions.allowed_restart_services` には、`systemd` で安全に再起動できる service だけを入れてください。
`tmux` や `shell script` 管理の Minecraft をここへ入れても自動実行対象にはしないでください。

`/etc/infra-production-poc/production_poc.env` では次を設定します。

- `DISCORD_WEBHOOK_URL=...`
- LLM を有効にする場合のみ `OPENAI_API_KEY=...` など

## 7. 状態保存ディレクトリ作成

```bash
sudo mkdir -p /var/lib/infra-production-poc
sudo chown -R infra-poc:infra-poc /var/lib/infra-production-poc
```

`infra-poc` を使わない場合は、この `chown` のユーザー名とグループ名も実際に使う値へ置き換えてください。

## 8. 初回 discovery 実行

timer を有効化する前に、まず discovery を手動実行します。

```bash
cd /opt/infra-emergency-recovery
sudo -u infra-poc env PYTHONPATH=/opt/infra-emergency-recovery \
  /opt/infra-emergency-recovery/.venv/bin/python \
  -m experimental.production_poc.runtime_prod.main \
  --config /etc/infra-production-poc/production_poc.yaml \
  --env-file /etc/infra-production-poc/production_poc.env \
  discover
```

既存ユーザーを使う場合は、`sudo -u infra-poc` もそのユーザー名へ置き換えてください。

設定した `state_dir` 以下に次が作られます。

- `latest_snapshot.json`
- `latest_snapshot.md`
- timestamp 付き snapshot archive

## 9. dry-run / propose-only 初回確認

初回は `actions.mode: propose-only` のまま 1 回監視を実行します。

```bash
cd /opt/infra-emergency-recovery
sudo -u infra-poc env PYTHONPATH=/opt/infra-emergency-recovery \
  /opt/infra-emergency-recovery/.venv/bin/python \
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

## 10. execute モード移行

propose-only の確認後にのみ execute へ進みます。

1. `allowed_restart_services` を小さく明示的に保つ
2. `actions.mode` を `execute` に変更する
3. `monitor-once` を再実行する
4. 想定した service 名だけが restart 対象になることを確認する

service 名に広い指定や wildcard は入れないでください。

## 11. systemd service / timer 化

まず次の雛形を実環境向けに見直します。

- `experimental/production_poc/deploy/production-poc-monitor.service`
- `experimental/production_poc/deploy/production-poc-monitor.timer`

重要:

- サーバー上のリポジトリ内ファイル `experimental/production_poc/deploy/production-poc-monitor.service` を直接編集し続けないでください
- ここを編集すると、将来 `git pull` したときにローカル変更として衝突します
- 追跡対象ではない `/etc/systemd/system/production-poc-monitor.service` 側を編集対象にしてください
- API key や webhook URL は unit ファイルに書かず、`/etc/infra-production-poc/production_poc.env` に置いてください

特に `production-poc-monitor.service` では次を確認してください。

- `User=infra-poc`
- `Group=infra-poc`
- `Environment=PYTHONPATH=/opt/infra-emergency-recovery`
- `ExecStart=/opt/infra-emergency-recovery/.venv/bin/python ...`

もし別 path に仮想環境を作った場合や、別ユーザーを使う場合は、それぞれ実環境の値へ書き換えてから `/etc/systemd/system/` へ配置してください。

その後、以下で配置します。

```bash
sudo cp experimental/production_poc/deploy/production-poc-monitor.service /etc/systemd/system/
sudo cp experimental/production_poc/deploy/production-poc-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now production-poc-monitor.timer
```

配置後の修正は、原則として `/etc/systemd/system/production-poc-monitor.service` 側だけに行ってください。

## 12. `git pull` が local changes で止まったとき

すでにサーバー上の追跡ファイルを編集してしまった場合は、次の流れで復旧できます。

1. 現在のローカル変更を退避する
2. `/etc/systemd/system/production-poc-monitor.service` へ必要な変更を移す
3. リポジトリ内の追跡ファイルを元に戻す
4. `git pull` する

例:

```bash
cd /opt/infra-emergency-recovery
cp experimental/production_poc/deploy/production-poc-monitor.service /tmp/production-poc-monitor.service.local
sudo cp /tmp/production-poc-monitor.service.local /etc/systemd/system/production-poc-monitor.service
git restore experimental/production_poc/deploy/production-poc-monitor.service
git pull
sudo systemctl daemon-reload
```

もし `/etc/systemd/system/production-poc-monitor.service` を直接編集したい場合は:

```bash
sudoedit /etc/systemd/system/production-poc-monitor.service
```

あるいは override を使う方法でも構いません。

```bash
sudo systemctl edit production-poc-monitor.service
```

## 13. 停止方法

```bash
sudo systemctl stop production-poc-monitor.timer
sudo systemctl stop production-poc-monitor.service
```

## 14. ログの見方

- `journalctl -u production-poc-monitor.service -n 100 --no-pager`
- 設定した `state_dir`
- 相関 ID 付き Discord 通知
- 対象 service の log / journal:

```bash
journalctl -u nginx -n 100 --no-pager
journalctl -u minecraft -n 100 --no-pager   # systemd 管理時のみ
tail -n 100 /path/to/minecraft/logs/latest.log
```

## 15. セキュリティ上の注意

- env file は管理者か専用 service account のみが読めるようにする
- 必要な log と command だけにアクセスできる専用 user を推奨
- `NoNewPrivileges=true` を維持する
- 明示した state directory 以外に書き込み権限を広げない
- API key、Discord webhook URL、token 類は Git 管理下のファイルへ書かない

## 16. バックアップ未整備環境での注意

この PoC は、バックアップや snapshot が弱い、または未整備な環境を前提にしています。

- 既定は `propose-only` のままにする
- `execute` は明示的な実験モードとして扱う
- 実 snapshot 機構が入るまで、config edit、package 管理、file delete、host-wide change を allowlist に追加しない

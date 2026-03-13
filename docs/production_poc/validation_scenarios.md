# Production PoC 実機検証シナリオ

本番影響が小さい時間帯に実施し、最初は必ず `propose-only` で始めてください。

## シナリオ 1: Web service を停止して検知

1. `sudo systemctl stop nginx`
2. `monitor-once` を実行
3. 次を確認
   - `web_service_inactive`
   - `web_http_failed`
   - Discord 障害通知
4. service は手動復旧するか、restart allowlist を確認済みの場合のみ `execute` で再試験

## シナリオ 2: Minecraft 停止を検知

`systemd` 管理か、`tmux` / `shell script` 管理かで手順を分けてください。

### 2-A. systemd 管理の Minecraft

1. `sudo systemctl stop minecraft`
2. `monitor-once` を実行
3. 次を確認
   - `minecraft_process_missing` または `minecraft_port_failed`
   - Discord 障害通知
   - `execute` でも allowlist 外なら自動再起動されない

### 2-B. tmux / shell script 管理の Minecraft

1. 安全な時間帯に、Minecraft Java process を停止するか、tmux session を明示的に落とす
2. `monitor-once` を実行
3. 次を確認
   - `minecraft_process_missing` または `minecraft_port_failed`
   - `systemctl is-active minecraft` のような誤判定が出ない
   - Discord では「手動復旧が必要」という趣旨の通知になる

## シナリオ 3: localhost health check を失敗させる

1. config の Web health URL を一時的に `http://127.0.0.1:9/healthz` のような失敗先へ向ける
2. `monitor-once` を実行
3. 次を確認
   - `web_http_failed`
   - `propose-only` では危険操作が実行されない

## シナリオ 4: dummy failed unit でエスカレーション確認

1. 無害な test unit を failed 状態にする
2. `monitor-once` を実行
3. 次を確認
   - `systemd_failed`
   - 安全な自動操作が無い場合、Discord にエスカレーション文面が出る

## シナリオ 5: execute モードで restart と検証を確認

1. `allowed_restart_services` を既知の安全 service 1 つに絞る
2. `actions.mode: execute` に変更
3. 対象 service を停止
4. `monitor-once` を実行
5. 次を確認
   - restart 試行が 1 回だけ記録される
   - 直後に検証が走る
   - 検証失敗時に連鎖自動操作が走らない

# Production PoC アーキテクチャ

## 目的

- 既存の Docker Compose ベース evaluation flow を変更しない
- Ubuntu 実ホスト向け PoC を隔離追加し、観測、異常検知、安全な提案、低リスク初動だけを扱う
- 常時コストを抑えるため、平常時はルールベース監視、異常時のみ LLM を使う

## ディレクトリ構成

```text
experimental/production_poc/
  runtime_prod/
    config.py
    controller.py
    main.py
    models.py
    persistence.py
  adapters/
    action_guard.py
    backup_provider.py
    command_runner.py
    host_observer.py
    llm_analyzer.py
    service_probes.py
  notifications/
    discord.py
  config/
    production_poc.example.yaml
  deploy/
    production-poc-monitor.service
    production-poc-monitor.timer
```

## 実行フロー

1. `discover` でホスト構成を収集し、JSON スナップショット、Markdown サマリ、軽量 LLM context を保存する
2. `monitor-once` で Web、Minecraft、ホスト資源を軽量ルールベースで確認する
3. 異常時のみ、controller が関連ログと probe 結果を追加収集する
4. analyzer が短い状況要約、原因候補、安全な構造化アクション案を返す
5. `ActionGuard` が risk を `read-only` / `low` / `medium` / `blocked` に分類し、allowlist 外や危険操作を遮断する
6. `execute` モードでも、自動実行は allowlist 済み低リスク操作を最大 1 回に制限する
7. medium-risk action は snapshot provider が ready で、かつ approval file が存在する場合だけ実行可能にする
8. 実行後は対象 probe を再実行して検証し、検証失敗時は設定済み rollback runbook を 1 段だけ試す
9. Discord には相関 ID 付きで要約通知と必要時の詳細通知を送る

## 安全境界

- 既定モードは `propose-only`
- 受け付けるのは構造化アクションのみ。任意 shell、package upgrade、file edit、delete、chmod/chown、firewall 変更、reboot は拒否
- `restart_service` は `allowed_restart_services` に登録された service のみ許可
- restart 以外の修復は `allowed_runbooks` に登録された固定 argv だけを実行する
- low-risk runbook は `execute` モードで自動実行できるが、medium-risk runbook は fresh snapshot と file approval が揃うまで実行されない
- `service_failover`、`config_toggle_rollback`、`dependency_rollback` は runbook-backed action として扱い、runbook allowlist なしでは拒否する
- 検証失敗時は自動連鎖操作を止め、必ずエスカレーション
- backup provider は既定 `none` のほか、local snapshot marker の存在と鮮度を確認する `local-snapshot` を使える

## 低コスト化

- `monitor-once` を systemd timer から定期起動する前提で、常駐 loop を避ける
- discovery snapshot は長めの周期で再収集する
- ログは通知前、LLM 入力前の両方で切り詰める
- サンプル設定では LLM を既定で無効化している

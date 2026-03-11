# Codex システム設計レビュー・改善提案

卒業研究用検証環境 (Safe Emergency Recovery Experiment Baseline) の全ソースコードを精読した上での、設計上の弱点・潜在バグ・改善提案をまとめる。

---

## 🔴 バグ・設計上の問題点

### 1. [_service_running](file:///Users/ryoike/Documents/codex/core/healthchecks.py#54-66) 関数の重複定義

[healthchecks.py](file:///Users/ryoike/Documents/codex/core/healthchecks.py) と [verifier.py](file:///Users/ryoike/Documents/codex/core/verifier.py) の両方に [_service_running](file:///Users/ryoike/Documents/codex/core/healthchecks.py#54-66) が独立実装されている。ロジックは同一だが、片方だけ修正すると不整合が生じる。

- [healthchecks.py:L54-65](file:///Users/ryoike/Documents/codex/core/healthchecks.py#L54-L65)
- [verifier.py:L207-218](file:///Users/ryoike/Documents/codex/core/verifier.py#L207-L218)

> [!WARNING]
> 片方だけ変更すると判定結果が分岐し、サイレント不整合を引き起こす。[healthchecks.py](file:///Users/ryoike/Documents/codex/core/healthchecks.py) 側へ統一すべき。

---

### 2. シナリオ定義と実行パスの不一致

[definitions.yaml](file:///Users/ryoike/Documents/codex/scenarios/definitions.yaml) には **i2, m, n, o** のシナリオが定義されているが：
- [break.sh](file:///Users/ryoike/Documents/codex/break.sh) には i2/m/n/o の注入ロジックが存在しない
- [agent.py](file:///Users/ryoike/Documents/codex/agent.py) / [run_single.py](file:///Users/ryoike/Documents/codex/runners/run_single.py) の `--scenario` の choices に i2/m/n/o がない
- [mock_worker.py](file:///Users/ryoike/Documents/codex/agents/mock_worker.py) にも i2/m/n/o の固定 plan がない
- [triage.py](file:///Users/ryoike/Documents/codex/core/triage.py) の [_rank_internal_scenarios](file:///Users/ryoike/Documents/codex/core/triage.py#131-222) にも i2/m/n/o のルールがない

> [!IMPORTANT]
> 定義だけ存在して実行できないシナリオは、YAML 検証で拾えずに実験結果の解釈を混乱させる可能性がある。使わないなら明示的にコメントアウトするか、実装が追いついたら break 側も揃えるべき。

---

### 3. Rollback 後のサービス再起動が欠落

[executor.py:L135](file:///Users/ryoike/Documents/codex/core/executor.py#L134-L136) でファイルのロールバック ([rollback_files](file:///Users/ryoike/Documents/codex/core/executor.py#20-30)) を実行するが、**ロールバック後にサービスの restart/rebuild を行わない**。例えば [app/main.py](file:///Users/ryoike/Documents/codex/app/main.py) をロールバックしても、実行中のコンテナは壊れたコードのままである。

```
rollback_result = rollback_files(backups) if backups else ...
# ← この後 docker compose restart/rebuild がない
```

> [!CAUTION]
> ファイルだけ戻しても running なコンテナは古い状態のままで、ロールバックの意味が半減する。

---

### 4. [postcheck_node](file:///Users/ryoike/Documents/codex/runners/run_single.py#190-210) 後のロールバックでもサービス再起動がない

[run_single.py:L218-227](file:///Users/ryoike/Documents/codex/runners/run_single.py#L218-L227) の [rollback_node](file:///Users/ryoike/Documents/codex/runners/run_single.py#218-228) でも同様に、ファイルを復元するだけで compose restart/rebuild しない。

---

### 5. [normalize_repo_path](file:///Users/ryoike/Documents/codex/core/policies.py#36-45) のパストラバーサル検証が不完全

[policies.py:L36-44](file:///Users/ryoike/Documents/codex/core/policies.py#L36-L44) で `../` を弾いているが、symlink 経由のエスケープはチェックしていない。[resolve_repo_path](file:///Users/ryoike/Documents/codex/core/policies.py#47-53) 側で [resolve()](file:///Users/ryoike/Documents/codex/core/policies.py#47-53) 後の親チェックはしている（L49-51）ので実害は小さいが、[normalize_repo_path](file:///Users/ryoike/Documents/codex/core/policies.py#36-45) 単体で信頼するコードがあると穴になりうる。

---

### 6. `show_file` が executor 内に残っている

[executor.py:L123-131](file:///Users/ryoike/Documents/codex/core/executor.py#L123-L131) で `show_file` の実行パスが残っている。README とプロンプトでは「単一ターンでは show_file は許可しない」と明記されているが、executor 自体は実行可能。許可制御は [actions.py](file:///Users/ryoike/Documents/codex/core/actions.py) の `forbidden_action_types` に依存しており、呼び方次第でバイパスされる設計。

---

### 7. [mock_worker_node](file:///Users/ryoike/Documents/codex/agents/mock_worker.py#203-227) で planner 関連フィールドが不完全に初期化

[mock_worker.py:L214-226](file:///Users/ryoike/Documents/codex/agents/mock_worker.py#L213-L226) で `planner_error_stage`, `planner_attempts`, `planner_transport_failure`, `planner_reasoning_failure`, `planner_fallback_used`, `planner_fallback_reason`, `planner_fallback_type` が設定されていない。[save_result](file:///Users/ryoike/Documents/codex/runners/run_single.py#230-323) 時に `state[key]` で初期値が使われるため大事には至らないが、明示設定がない点は脆弱。

---

## 🟡 設計上の甘さ

### 8. Triage がハードコードされた文字列パターンマッチに依存

[triage.py](file:///Users/ryoike/Documents/codex/core/triage.py) の [_rank_domains](file:///Users/ryoike/Documents/codex/core/triage.py#224-430) と [_rank_internal_scenarios](file:///Users/ryoike/Documents/codex/core/triage.py#131-222) は、`"server app:8001"`, `"FROM itemz ORDER BY id"`, `"DB_PASSWORD=wrongpassword"` 等の **リテラル文字列** に対する単純な [in](file:///Users/ryoike/Documents/codex/aggregate_observations.py#275-378) 演算をスコアリングに使っている。

- **問題**: 故障注入パターンが少しでも変われば（例: ポートが 8002 になる）、triage が全く機能しなくなる
- **改善案**: パターンを正規表現化するか、[definitions.yaml](file:///Users/ryoike/Documents/codex/scenarios/definitions.yaml) に triage 用のシグネチャを定義して data-driven にする

---

### 9. [_hidden_benchmark_evidence](file:///Users/ryoike/Documents/codex/core/triage.py#111-117) がファイルを直接読んでいる

[triage.py:L111-116](file:///Users/ryoike/Documents/codex/core/triage.py#L111-L116) で [app/app.env](file:///Users/ryoike/Documents/codex/app/app.env), [app/main.py](file:///Users/ryoike/Documents/codex/app/main.py), [nginx/nginx.conf](file:///Users/ryoike/Documents/codex/nginx/nginx.conf) を **直接読み込んで** I/K シナリオの判定に使っている。これは triage が「観測から推定する」という設計方針と矛盾し、チート的に正解を見ている。

> [!WARNING]
> open-world triage の公平な評価を行うなら、[_rank_internal_scenarios](file:///Users/ryoike/Documents/codex/core/triage.py#131-222) は evaluator 専用であることを明確にし、triage のドメイン推定（[_rank_domains](file:///Users/ryoike/Documents/codex/core/triage.py#224-430)）とは完全に分離すべき。

---

### 10. 追加観測が 1 回限り・固定的

追加観測（[additional_observation_node](file:///Users/ryoike/Documents/codex/agents/sensor.py#462-541)）は 1 回しか許可されず、取得する項目も `recommended_next_observations` の固定文字列マッチで決まる。

- **問題**: 不十分だった場合の再試行パスがない。K シナリオのように追加観測が必須のケースで、1 回目で十分な情報が得られなかった場合に対応できない。
- **改善案**: 最大 N 回まで iterative に追加観測を許す設定を入れ、信頼度が閾値を超えるまでループできるようにする。

---

### 11. Postcheck の retry 判定条件が曖昧

[verifier.py:L285-295](file:///Users/ryoike/Documents/codex/core/verifier.py#L285-L295) の postcheck ループは `readiness_wait_used=True` でないと即座に break する。しかし、`readiness_wait_used` は executor が `readiness_wait_requested` を返した場合にしか True にならない。

- **問題**: nginx.conf だけ編集→nginx restart の場合、`readiness_wait_requested` は True になるが、restart 直後の一瞬の不通でも postcheck が最初の 1 回で失敗判定される可能性がある。
- **改善案**: restart/rebuild を含む全ケースで短い retry を入れるか、サービスの ready 判定を別の仕組みで行う。

---

### 12. [expand_execution_actions](file:///Users/ryoike/Documents/codex/core/actions.py#183-282) の app rebuild 自動挿入が複雑すぎる

[actions.py:L183-281](file:///Users/ryoike/Documents/codex/core/actions.py#L183-L281) の自動 action 展開ロジックが約 100 行あり、restart→rebuild のアップグレード、nginx config test の自動挿入、app rebuild の自動追加が同一関数に詰め込まれている。エッジケースのテストが難しい。

- **改善案**: 各展開ルール（nginx test 挿入、restart→rebuild 昇格、app rebuild 追加）を個別の小関数に分割し、単体テスト可能にする。

---

### 13. 結果 JSON 内のフィールド重複

[run_single.py:L230-320](file:///Users/ryoike/Documents/codex/runners/run_single.py#L230-L320) の [save_result](file:///Users/ryoike/Documents/codex/runners/run_single.py#230-323) で、同じ情報が異なるキー名で二重に格納されている：

| 重複 | キー1 | キー2 |
|------|-------|-------|
| アクション | `normalized_actions` | `proposed_actions` |
| 生出力 | `planner_output_raw` | `worker_raw_output` |
| ファイルスニペット | `worker_visible_file_snippets` | `worker_visible_context.observation.file_snippets` |

データサイズが膨張し、分析時に混乱を招く。

---

### 14. エラーハンドリングの一貫性不足

- [healthchecks.py](file:///Users/ryoike/Documents/codex/core/healthchecks.py) の [http_check](file:///Users/ryoike/Documents/codex/core/healthchecks.py#68-86) は `urllib` の例外を [str(exc)](file:///Users/ryoike/Documents/codex/core/actions.py#15-21) で丸めて返すが、タイムアウトとコネクション拒否の区別がつかない
- [run_fixed_command](file:///Users/ryoike/Documents/codex/core/healthchecks.py#10-23) はタイムアウトを設定していないため、Docker デーモンが応答しない場合にハングする可能性がある

---

## 🟢 改善提案（より良い結果を得るために）

### 15. Multi-turn 修復ループの導入

現在は「1 回の計画で復旧を試みる」設計であり、I のような多段障害には対応しにくい。postcheck の失敗結果を feedback として worker に戻し、**最大 N ターンの self-correction ループ** を入れることで、「初段の修復で新たに露出した障害を検出・修復」できるようになる。

---

### 16. 信頼度スコアの動的更新

triage の confidence はルールベースの固定値。追加観測や postcheck の結果を踏まえた **Bayesian 的な信頼度更新** を行えば、曖昧ケースでの判定精度が向上する可能性がある。

---

### 17. テストスイートの欠如

プロジェクト全体に **ユニットテストがない**。特に以下はテストが強く必要：

- [normalize_action](file:///Users/ryoike/Documents/codex/core/actions.py#23-113) / [normalize_actions](file:///Users/ryoike/Documents/codex/core/actions.py#115-141) のエッジケース（空文字列、不正型、ネスト構造）
- [expand_execution_actions](file:///Users/ryoike/Documents/codex/core/actions.py#183-282) の自動挿入ロジック
- [_rank_domains](file:///Users/ryoike/Documents/codex/core/triage.py#224-430) / [_rank_internal_scenarios](file:///Users/ryoike/Documents/codex/core/triage.py#131-222) のスコアリング
- `replace_text` の 1 回一致制約

テストがないと、新シナリオ追加時のリグレッションを検知できない。

---

### 18. Sensor の観測タイミング制御の改良

`OBSERVATION_STABILIZATION_SECONDS = 2` で最大 2 回まで安定化待機するが、app コンテナの起動が遅い場合（pip install を含む）にはこれでは足りない場合がある。動的に起動シーケンスの完了を待つ（例: `docker compose wait` や healthcheck の利用）方がロバスト。

---

### 19. Prompt Engineering の版管理

[core/prompts.py](file:///Users/ryoike/Documents/codex/core/prompts.py) では `single_agent_blind_v7` のようにバージョン番号を手動管理しているが、実際にどのプロンプトでどの結果が出たかの追跡可能性が弱い。プロンプトテキスト自体のハッシュを結果 JSON に含めると、再現性が向上する。

---

### 20. `restore_from_base` のみに頼る安全策のリスク

[app/app.env](file:///Users/ryoike/Documents/codex/app/app.env) 等で正解値が分からない場合に `restore_from_base` をフォールバックにしているが、base ファイルが正規の標的環境で実際に存在する前提。本番想定では base ファイルが無いケースも考慮し、**構成管理バックアップとの差分適用** といった代替戦略の検討が望ましい。

---

## まとめ

| カテゴリ | 件数 | 深刻度 |
|---------|------|-------|
| バグ・実装上の問題 | 7 件 | 🔴 高 |
| 設計上の甘さ | 7 件 | 🟡 中 |
| より良い結果のための改善提案 | 6 件 | 🟢 提案 |

特に **ロールバック後のサービス再起動欠落**（#3, #4）と **ユニットテスト未整備**（#17）は、卒論として提出するシステムとしては対処優先度が高い。Triage のハードコーディング（#8, #9）は研究成果としての汎用性に関わる論点となりうる。

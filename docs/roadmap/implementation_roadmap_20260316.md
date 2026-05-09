# 実装ロードマップ

作成日: 2026-03-16  
基礎資料: [`../reports/repository_assessment_20260316.md`](../reports/repository_assessment_20260316.md)

> 2026-05-08 注記: このロードマップは初期計画であり、現在は Phase 2 以降の改訂版と現在地メモを優先する。最新の進捗判断は [../current_status_20260508.md](../current_status_20260508.md)、計画の更新版は [implementation_roadmap_revised_20260415.md](implementation_roadmap_revised_20260415.md) を参照する。

## 1. 目的

本ロードマップの目的は、現状の

- 安全な LLM 応急復旧実験基盤
- minimal な multi-agent ループ
- 実ホスト向け low-risk PoC

を、卒業研究案である **「LLMマルチエージェント協調を用いたDCインフラ応急修復システム」** により近い形へ段階的に発展させることである。

特に重要なのは、単に機能を増やすことではなく、**卒論として説得力のある比較実験と主張** を成立させる順番で実装を進めることである。

## 2. 基本方針

以下の 4 原則で進める。

1. **評価可能性を先に固める**  
   機能追加より前に、シナリオ・観測・集計・テストの整合を取る。

2. **hard scenario で multi-agent の価値を示す**  
   `i2/m/n/o/r/u` のような多段障害で single-agent を上回ることを主目標にする。

3. **DCらしさは「段階的に」増やす**  
   いきなり大規模 DC を目指すのではなく、multi-service / multi-host / topology-aware な方向へ広げる。

4. **本番PoCは安全性を崩さず拡張する**  
   `restart` 一辺倒から広げるが、人間承認・バックアップ・段階的 rollback を伴わせる。

## 3. 優先順位

### 最優先 (`P0`)

- 評価パイプラインの整合
- 実験環境の安定化
- hard scenario 向け multi-agent 強化

### 高優先 (`P1`)

- shared state を持つ本格 multi-agent orchestration
- DCライクなベンチマーク拡張
- 比較実験の設計と自動集計

### 中優先 (`P2`)

- production PoC の action 拡張
- backup provider / approval gate の実装

### 低優先 (`P3`)

- 実運用向け UI/通知の洗練
- 長期運用向け監査・可視化ダッシュボード

## 4. フェーズ別計画

## Phase 0: 評価基盤の整合と実験環境の安定化

### 目的

「何を評価しているのか」が曖昧にならないように、シナリオ定義、観測スイープ、集計、README、テストを同期させる。

### 実装項目

1. `observe_runs.sh` のデフォルト sweep を見直す  
   - `p/q/r` を含める  
   - 必要なら `A-U` を網羅する標準 sweep と短縮 sweep を分ける

2. `aggregate_observations.py` を `s/t/u` まで対応させる  
   - `EXPECTED_DOMAINS_BY_SCENARIO` を更新する
   - multi-agent 向けメトリクスを追加しやすい形へ整理する

3. `README.md` のシナリオ記述を `A-U` 基準に更新する  
   - `A-R` など古い記述を修正する
   - stale link を整理する

4. `reset.sh` / Docker 実験環境を安定化する  
   - `/target-db` 競合の原因を特定する
   - cleanup をより確実にする
   - multi-agent end-to-end test が安定して回る状態にする

5. テスト実行の標準手順を固定する  
   - `./.venv/bin/python -m pytest -q` を公式手順にする
   - 可能なら CI か `check.sh` を追加する

### 完了条件

- シナリオ、観測、集計、README の対象範囲が一致している
- multi-agent mock テストが環境要因で落ちない
- 再現手順が第三者に説明できる

### 卒論上の価値

このフェーズを終えると、「評価設計が整理されている」こと自体が研究の信頼性になる。

## Phase 1: multi-agent orchestration の本格化

### 目的

現状の `planner -> reviewer -> judge` 直列ループを、**明確な役割分担を持つ multi-agent 協調** に進化させる。

### 実装項目

1. shared incident state / blackboard の導入  
   - 観測、仮説、候補修復、検証結果、失敗履歴を agent 間で共有する

2. agent の役割を明確化する  
   - `observer agent`
   - `triage agent`
   - `repair planner agent`
   - `verification reviewer agent`
   - `safety judge agent`

3. 追加観測を 1 回制限から複数回へ拡張する  
   - confidence や ambiguity に応じて追加観測を継続する
   - 無限ループ防止の上限を入れる

4. reviewer の提案を実際に次ターンへ強く反映する  
   - 推奨 scope
   - 推奨次観測
   - 残存ドメイン仮説

5. hard scenario 専用の multi-turn 戦略を入れる  
   - `i2`: port 修復後に query bug へ移る
   - `m`: nginx -> DB auth -> query bug の三段階
   - `n`: dependency -> query bug
   - `o`: stale evidence を無視して DB auth -> query bug
   - `r/u`: マスク障害の解除後に再観測

### 完了条件

- multi-agent の役割分担がコード上でも説明上でも明確である
- `i2/m/n/o` で mock multi-agent が安定成功する
- LLM multi-agent が single-agent より hard scenario で改善する

### 卒論上の価値

このフェーズが最重要である。  
卒論の核は「multi-agent にする意味」を hard scenario で示せるかどうかにある。

## Phase 2: DCライクなベンチマークへの拡張

### 目的

現状の `nginx -> app -> db` から一歩進めて、**DC インフラに近い複雑性** を持つ評価環境へ拡張する。

### 実装項目

1. 対象構成を multi-service 化する  
   - cache
   - worker
   - queue
   - metrics / monitoring service

2. topology-aware な fault を追加する  
   - name resolution 失敗
   - network partition 風の障害
   - failover 先不一致
   - 複数設定の bilateral drift

3. multi-host 的な抽象化を導入する  
   - `host-A`, `host-B` を模した service group
   - 依存先切替や route 切替をシナリオ化する

4. semantic success check を強化する  
   - 単に 200 を返すだけでなく
   - expected topology
   - expected contract
   - degraded mode でないこと
   を確認する

5. シナリオを fault class ごとに整理し直す  
   - service-local fault
   - dependency fault
   - topology fault
   - ambiguous/noisy fault
   - masked cascade

### 完了条件

- ベンチマーク対象が単一アプリ修復から一段広がる
- 「DCインフラらしさ」を本文で説明できる
- 少なくとも 1 つは topology-aware な multi-step scenario を用意できる

### 卒論上の価値

題目の `DCインフラ` の説得力を上げるフェーズである。  
ここで対象を広げないと、「Web アプリ復旧研究」に見えやすい。

## Phase 3: 安全な修復アクションの拡張

### 目的

修復能力を広げつつ、安全性の主張を崩さない。

### 実装項目

1. action vocabulary を段階的に増やす  
   候補:
   - allowlisted runbook execution
   - service failover switch
   - config toggle rollback
   - dependency rollback
   - read-only diagnosis actions の拡充

2. `ActionGuard` / verifier の risk model を強化する  
   - read-only
   - low-risk
   - medium-risk
   - blocked
   をより明確に分ける

3. backup provider を本実装する  
   - snapshot availability の確認
   - risky action 前の guard
   - rollback 失敗時の escalation

4. human approval gate を導入する  
   - medium-risk 以上は approve 必須
   - Discord / file / CLI ベースでもよいので形にする

5. rollback を段階的にする  
   - file rollback だけでなく
   - service refresh
   - verification after rollback
   - 必要なら fallback safe mode

### 完了条件

- production PoC で restart 以外の低リスク修復を 1 つ以上安全に扱える
- backup / approval / rollback の流れを説明できる

### 卒論上の価値

「安全に実行できる multi-agent repair system」という主張の厚みが増す。

## Phase 4: production PoC の強化

### 目的

`monitoring + propose-only` から、**human-in-the-loop な応急修復支援システム** へ進める。

### 実装項目

1. analyzer の提案品質を上げる  
   - host-level issue の分類を詳細化
   - read-only diagnostics を提案させる
   - escalation reason を構造化する

2. live-run artifact を残す  
   - 実機での monitor log
   - incident JSON
   - verification log
   - manual validation record

3. 実機向け validation scenario を増やす  
   - restart だけで直るケース
   - read-only diagnosis だけで人間判断へ渡すケース
   - approval 後に限定修復するケース

4. notification を研究向けに整える  
   - 相関 ID
   - decision trace
   - why executed / why blocked

### 完了条件

- production PoC が「監視ツール」ではなく「安全な応急修復支援 PoC」と呼べる
- 少数でも live-run artifact を卒論に載せられる

## Phase 5: 比較実験と卒論向け成果整理

### 目的

実装を研究成果へ変換する。

### 実装項目

1. 比較対象を固定する  
   - single-agent
   - multi-agent minimal
   - improved multi-agent

2. 比較指標を固定する  
   - success rate
   - hard scenario success rate
   - number of turns
   - unsafe action rejection rate
   - rollback rate
   - recovery time
   - semantic success rate

3. アブレーションを行う  
   - reviewer なし
   - judge なし
   - additional observation なし
   - backup/approval なし

4. production PoC の位置づけを明確にする  
   - full automation ではなく
   - low-risk remediation support PoC
   として整理する

5. 論文用の図表を作る  
   - アーキテクチャ図
   - フロー図
   - 成功率比較表
   - hard scenario の turn-by-turn 事例

### 完了条件

- 卒論の実験章がそのまま書ける
- `multi-agent にする意義` を数値で示せる

## 5. まず着手すべき具体タスク

次に実装するべきものを、実際の着手順で並べる。

1. `observe_runs.sh`, `aggregate_observations.py`, `README.md` を `A-U` 基準で同期する
2. `reset.sh` の Docker cleanup 問題を直し、multi-agent mock テストを安定化する
3. reviewer / judge / triage の state 受け渡しを整理し、shared incident state を入れる
4. additional observation を複数回ループ可能にする
5. `i2/m/n/o/r/u` を対象に improved multi-agent の成功率を上げる
6. `DCライク` な topology scenario を 1 系統追加する
7. production PoC に approval + backup provider + 低リスク追加アクションを入れる

## 6. 各フェーズの成果物

### Phase 0 の成果物

- 整合した README
- 安定した sweep / aggregate
- 安定した Docker テスト環境

### Phase 1 の成果物

- improved multi-agent orchestration
- hard scenario success 改善
- turn-by-turn trace

### Phase 2 の成果物

- DCライク benchmark scenario 群
- topology-aware success checks

### Phase 3-4 の成果物

- backup provider
- approval gate
- expanded production PoC

### Phase 5 の成果物

- 比較表
- 成功率グラフ
- 卒論用図表

## 7. リスクと対策

### リスク 1: 実装を広げすぎて比較実験が薄くなる

対策:

- まず hard scenario の改善を最優先にする
- production PoC の機能追加は後段に回す

### リスク 2: `DCインフラ` を広げすぎて安全性が崩れる

対策:

- action は allowlist 方式のまま広げる
- backup / approval を先に入れる

### リスク 3: 題目に対して成果が散漫になる

対策:

- 卒論の主張を「安全制約下での multi-agent repair effectiveness」に集中させる
- production PoC は補強材料として位置づける

## 8. 推奨する最終的な研究ストーリー

最も通しやすい研究ストーリーは次の形である。

1. 安全な単一エージェント応急復旧基盤を構築した
2. hard scenario では single-agent が部分修復で止まりやすいことを示した
3. multi-agent orchestration を導入し、再観測・再計画・再評価を可能にした
4. その結果、masked cascade や ambiguous scenario で復旧性能が改善した
5. さらに実ホスト向け PoC を通じて、本番適用時の安全制約と human-in-the-loop の必要性を示した

この流れなら、現状のリポジトリ資産を最大限活かしつつ、題目との整合も取りやすい。

## 9. 結論

今後の実装は、**機能を増やす順番** が重要である。  
最初にやるべきことは「評価の整合」と「hard scenario に対する multi-agent の改善」であり、その後に `DCらしさ` と `production PoC` を拡張するのが最も効率的である。

したがって、推奨順序は以下である。

1. 評価基盤整備
2. multi-agent 強化
3. DCライク benchmark 拡張
4. 安全な action / backup / approval 実装
5. production PoC 強化
6. 比較実験と卒論整理

この順で進めれば、現在のリポジトリを **「安全な応急復旧評価基盤」から「卒論として主張可能な multi-agent DCライク修復システム」へ発展させやすい**。

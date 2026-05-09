# 実装ロードマップ（Phase 2 完了前提・改訂版）

作成日: 2026-04-15  
更新メモ: 2026-05-08
前提: **Phase 0〜2 は完了している**ものとして、以降の進め方を再設計する。  
基礎資料: [`implementation_roadmap_20260316.md`](implementation_roadmap_20260316.md), [`../reports/phase1_compare_cost_report_20260414.md`](../reports/phase1_compare_cost_report_20260414.md), [`../current_status_20260508.md`](../current_status_20260508.md)

---

## 0. 2026-05-08 時点の読み替え

このロードマップは 2026-04-15 時点では「Phase 2 完了後に何を作るか」を整理したものだった。2026-05-08 時点では、機能面の中核はさらに進み、次の状態として読む。

- Phase 3 の安全 action 拡張は、production PoC 側で allowlist restart / runbook / backup / approval gate / rollback runbook まで要素実装済み
- Phase 4 の production PoC は、本番自動修復システムというより、提案・低リスク初動・human-in-the-loop を示す補助成果として扱う
- Phase 4.5 の self-critique baseline と hypothesis log / metrics は実装済みで、少数の result JSON に保存されている
- Phase 5 は未完了であり、反復実験、集計、図表化、ケーススタディ、卒論本文化が現在の主作業である

したがって、今後の優先順位は「新機能を足す」から「実験と卒論成果物へ変換する」へ移っている。詳細な現在地は [../current_status_20260508.md](../current_status_20260508.md) を優先して参照する。

### 現在の次タスク

1. 比較条件を固定する
2. `i2/m/n/o/r/u` と `v/w/x` を中心に反復実験を回す
3. `hypothesis_metrics` を条件間で揃える
4. 成功率、turn、stop reason、コスト、仮説固執を表にする
5. 中間発表用には予備結果までを出し、詳細比較は卒論向けに残す
6. 卒論用の図表と case study を作る

---

## 1. 改訂の目的

本改訂版の目的は、既存ロードマップをそのまま延長するのではなく、
**Phase 2 までの実装が終わった後に、卒論として最も通しやすい順番へ再構成すること**である。

特に今回の改訂では、以下を重視する。

1. **Phase 5 の比較実験設計を強化する**  
   単純な single-agent vs multi-agent 比較ではなく、
   **single-agent self-critique** や **planner diversity** を含む、より強い比較に変える。

2. **Phase 4 と Phase 5 の間に、新しい評価準備フェーズを挿入する**  
   今後の主張の核は、成功率そのものだけでなく、
   **仮説変更・固執・批判後の方針転換** をどう示すかにある。

3. **production PoC の拡張より先に、研究としての説明力を固める**  
   ここから先は「できることを増やす」より、
   **何が効いているのかを比較可能な形にすること**を優先する。

---

## 2. 現在地（Phase 2 完了前提）

現時点では、次の土台が整っているものとする。

- Phase 1: multi-agent orchestration の本格化が完了している
- Phase 2: DCライク benchmark と topology-aware scenario が導入済みである
- hard scenario 群 (`i2/m/n/o/r/u`) に対して multi-turn repair を試せる
- semantic success check まで含めて評価基盤が動作している

ただし、ここからの核心は **「multi-agent が効いたか」ではなく「なぜ効いたのか」** である。

そのため、今後は次の問いを中心に据える。

- self-critique を持つ single-agent は hard scenario でどこまで改善するか
- explicit multi-agent criticism は仮説更新をどこまで促進するか
- planner diversity は仮説固執を減らすか

---

## 3. 改訂後の優先順位

### 最優先 (`P0`)

- 強い single-agent baseline の導入
- 仮説遷移ログの整備
- hard scenario に対する比較実験の成立

### 高優先 (`P1`)

- Phase 3 の安全な action 拡張
- Phase 4.5 の評価準備フェーズ完遂
- Phase 5 の比較・図表化

### 中優先 (`P2`)

- production PoC の live-run artifact 拡充
- planner diversity / dual-planner の実験導入

### 低優先 (`P3`)

- 通知・監査・UI の洗練
- 長期運用向けの可視化やダッシュボード

---

## 4. フェーズ別計画（改訂版）

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

「安全に実行できる multi-agent repair system」という主張の厚みを保つフェーズである。

---

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

### 卒論上の価値

本番適用時の human-in-the-loop と安全制約の必要性を示す補強材料になる。

---

## Phase 4.5: 仮説遷移評価と強ベースライン整備

### 目的

Phase 5 の比較実験を成立させるために、
**「何が効いたのか」を説明できるログ・ベースライン・比較条件を先に整備する。**

このフェーズでは、成功率だけでなく、
**仮説変更・仮説固執・批判後の方針転換** を研究の中心指標として扱える状態を作る。

### 実装項目

1. **single-agent iterative self-critique baseline** を実装する  
   - one-shot single-agent とは別条件で運用する
   - 観測 → 仮説 → 修復 → 自己批判 → 再計画 を multi-turn で回せるようにする
   - multi-agent と同じ turn 上限・同等の観測条件に揃える

2. **仮説ログの構造化** を行う  
   各ターンで最低限以下を保存する。
   - `primary_hypothesis`
   - `secondary_hypotheses`
   - `confidence`
   - `evidence_summary`
   - `proposed_action`
   - `reviewer_feedback_category`
   - `judge_decision`
   - `hypothesis_changed`
   - `changed_after_critique`

3. **仮説ラベルの正規化** を行う  
   例:
   - `nginx_upstream_mismatch`
   - `db_auth_failure`
   - `db_host_topology_mismatch`
   - `dependency_missing`
   - `query_bug`
   - `stale_evidence_mislead`
   - `unknown`

4. **reviewer / judge 指摘のカテゴリ化** を行う  
   例:
   - `insufficient_evidence`
   - `masked_failure_exposed`
   - `wrong_scope`
   - `unsafe_action`
   - `retry_needed`
   - `stop_due_to_no_progress`

5. **仮説遷移メトリクス** を定義する  
   最低限以下を保存・集計する。
   - Top-1 仮説変更回数
   - 仮説集合更新回数
   - 批判後の仮説変化率
   - 誤仮説固着長
   - first-fix success と full recovery の差
   - 再観測回数とその効果

6. **比較条件を固定** する  
   最低構成は以下とする。
   - single-agent one-shot
   - single-agent iterative self-critique
   - multi-agent single-planner
   - improved multi-agent

   余力があれば以下も入れる。
   - multi-agent dual-planner
   - planner diversity 強化版

7. **公平な実験条件** を固定する  
   - turn 上限を統一する
   - 利用できる観測情報を揃える
   - action allowlist / verifier 条件を共通にする
   - hard / easy scenario を分けて集計する

8. **hard scenario 向けの分析テンプレート** を整える  
   `i2/m/n/o/r/u` を対象に、
   - 初期仮説
   - 露出した下流障害
   - 仮説転換の契機
   - 最終復旧結果
   を追跡できるフォーマットを作る。

### 完了条件

- self-critique single-agent が hard scenario 群で安定して実行できる
- 仮説遷移ログが JSON / CSV などで後処理可能な形で保存される
- 仮説変更回数・誤仮説固着長・批判後の仮説変化率を集計できる
- 「改善の本体が reflection なのか、explicit decomposition なのか」を比較可能になる

### 卒論上の価値

このフェーズを挟むことで、
卒論の主張を単なる「multi-agent のほうが強い」から、
**「hard scenario において、どの制御構造が仮説固執を減らし、方針転換を促したか」**
という一段深い比較へ引き上げられる。

---

## Phase 5: 比較実験と卒論向け成果整理（改訂版）

### 目的

実装を研究成果へ変換する。  
ただし本フェーズでは、単なる成功率比較に留まらず、
**強いベースラインを含めた比較と、仮説遷移の説明可能性** を主軸にする。

### 実装項目

1. **比較対象を固定する**  
   基本構成:
   - single-agent one-shot
   - single-agent iterative self-critique
   - multi-agent single-planner
   - improved multi-agent

   余力があれば追加:
   - multi-agent dual-planner
   - planner diversity 強化版

2. **比較指標を固定する**  
   従来指標:
   - success rate
   - hard scenario success rate
   - number of turns
   - unsafe action rejection rate
   - rollback rate
   - recovery time
   - semantic success rate

   今回追加する中心指標:
   - Top-1 仮説変更回数
   - 誤仮説固着長
   - 批判後の仮説変化率
   - first-fix success rate
   - full recovery rate
   - re-observation benefit
   - cost / token per successful recovery

3. **hard / easy / fault class ごとの集計** を行う  
   少なくとも以下で分けて見る。
   - easy scenario
   - hard scenario
   - service-local fault
   - dependency fault
   - topology fault
   - ambiguous / noisy fault
   - masked cascade

4. **アブレーションを行う**  
   基本:
   - reviewer なし
   - judge なし
   - additional observation なし
   - self-critique なし

   余力があれば:
   - blackboard/shared state なし
   - planner diversity なし
   - backup/approval なし

5. **失敗の型を整理する**  
   例:
   - 初期仮説への固執
   - 再観測不足
   - scope violation
   - judge stop の誤作動
   - max turns reached
   - reviewer invocation failure
   - verifier blocked

6. **代表事例の case study** を作る  
   最低 1〜2 本、以下を図示する。
   - ターンごとの観測
   - 主仮説の変化
   - 批判内容
   - 採択アクション
   - 露出した下流障害
   - 最終結果

7. **production PoC の位置づけを明確にする**  
   - full automation ではなく
   - low-risk remediation support PoC
   として整理する

8. **論文用の図表を作る**  
   必須:
   - アーキテクチャ図
   - フロー図
   - 成功率比較表
   - 仮説変更回数の比較図
   - hard scenario の仮説遷移図
   - turn-by-turn 事例図

### 完了条件

- 卒論の実験章がそのまま書ける
- 強い single-agent baseline を入れたうえで比較が成立している
- `multi-agent にする意義` または `single-agent reflection で十分な範囲` を数値で示せる
- 「何が効いたのか」を仮説遷移と失敗分類で説明できる

### 卒論上の価値

このフェーズにより、研究の中心が
**multi-agent の有無** から
**仮説固執を減らす制御構造の比較** へ進化する。

どの方式が勝っても、
- multi-agent の有効条件
- self-critique の到達限界
- planner diversity の効きどころ
を定量的に示せるようになる。

---

## 5. まず着手すべき具体タスク（Phase 2 完了前提）

次に着手するべきものを、現実的な順番で並べる。

2026-05-08 時点では、以下は当初タスク一覧ではなく進捗表として読む。

| 当初タスク | 現在の状態 |
| --- | --- |
| single-agent iterative self-critique baseline を実装する | 完了。`self_critique_agent.py` と `runners/run_self_critique.py` で実行可能 |
| 仮説ログ schema を決め、構造化保存する | 完了。`hypothesis_log` / `hypothesis_metrics` / `self_critique_history` を保存可能 |
| `i2/m/n/o/r/u` の同条件比較を回す | 予備実験は実施済み。本実験としては反復数を増やす |
| 仮説変更・固執メトリクスを集計する | 実装済み。条件間比較に使う CSV 整備が残り |
| hard / easy / fault class ごとの集計を整える | これから優先 |
| Phase 3 の安全 action 拡張 | production PoC 側で要素実装済み。卒論では補助成果扱い |
| production PoC の live-run artifact | これから必要最小限を確保 |
| dual-planner / planner diversity | 余力枠。中間発表・卒論本線では必須にしない |

当初の順序:

1. single-agent iterative self-critique baseline を実装する
2. 仮説ログ schema を決め、planner / reviewer / judge 出力を構造化保存する
3. `i2/m/n/o/r/u` を対象に、one-shot / self-critique / multi-agent の同条件比較を回す
4. 仮説変更回数・誤仮説固着長・批判後の仮説変化率を集計できるようにする
5. hard / easy / fault class ごとの集計スクリプトを整える
6. Phase 3 の安全 action 拡張を進める
7. production PoC の live-run artifact を最低限確保する
8. 余力があれば dual-planner / planner diversity 比較を入れる

---

## 6. 各フェーズの成果物（改訂版）

### Phase 3 の成果物

- expanded action vocabulary
- risk-aware verifier / guard
- backup / approval / rollback フロー

### Phase 4 の成果物

- production PoC の live-run artifact
- monitor / incident / verification ログ
- human-in-the-loop validation 事例

### Phase 4.5 の成果物

- self-critique single-agent baseline
- 構造化された hypothesis transition log
- 仮説変更・固執メトリクス
- hard scenario 向け分析テンプレート

### Phase 5 の成果物

- 強ベースライン込みの比較表
- 成功率・仮説変更回数・固執長のグラフ
- 仮説遷移図
- hard scenario case study
- 卒論用図表一式

---

## 7. リスクと対策（改訂版）

### リスク 1: self-critique single-agent が強すぎて multi-agent の差が小さくなる

**対策:**
- 研究の問いを「multi-agent が勝つか」から、
  「reflection と explicit decomposition のどちらが hard scenario に効くか」へ再定義する
- hard scenario 限定で差を確認する
- 仮説固執・仮説変更を中心に比較する

### リスク 2: planner diversity を入れすぎて比較軸が散漫になる

**対策:**
- 本線は self-critique vs multi-agent に置く
- dual-planner は余力がある場合の追加比較に留める

### リスク 3: ログが自然文のままで後から比較できなくなる

**対策:**
- 仮説ラベルと reviewer feedback をカテゴリ化する
- 早い段階で schema を固定する

### リスク 4: production PoC を広げすぎて本丸の比較実験が薄くなる

**対策:**
- production PoC は補強材料に留める
- Phase 4.5 と Phase 5 の完了を優先する

---

## 8. 推奨する最終的な研究ストーリー（改訂版）

最も通しやすい研究ストーリーは次の形である。

1. 安全制約付きの single-agent 応急復旧基盤を構築した
2. そこに DCライク benchmark と topology-aware scenario を追加した
3. 強い baseline として self-critique single-agent を導入した
4. explicit multi-agent criticism と仮説共有により、hard scenario で仮説固執が減るかを比較した
5. 必要に応じて planner diversity の効果も追加比較した
6. その結果、どの制御構造が仮説更新と full recovery に有利かを示した
7. さらに production PoC により、本番適用時の human-in-the-loop と安全制約の必要性を示した

この流れなら、たとえ self-critique single-agent がかなり強くても研究は崩れない。  
むしろ、**multi-agent の有効条件を限定付きで示す研究**として成立しやすい。

---

## 9. 結論

Phase 2 まで完了している前提では、今後の鍵は **新機能の追加量ではなく、比較実験の質** である。  
ここから先は、Phase 3 と Phase 4 を補強しつつも、
本当に優先すべきなのは **Phase 4.5 と改訂版 Phase 5** である。

したがって、推奨順序は以下になる。

1. self-critique single-agent baseline の導入
2. 仮説遷移ログの構造化
3. hard scenario 比較実験の実施
4. 仮説変更・固執メトリクスの集計
5. Phase 3 の安全 action 拡張
6. Phase 4 の production PoC 補強
7. 余力があれば planner diversity 比較
8. 卒論用図表・文章への変換

この順で進めれば、現在の資産を活かしたまま、
**「安全な応急復旧評価基盤」から「仮説遷移まで説明できる比較研究」へ発展させやすい。**

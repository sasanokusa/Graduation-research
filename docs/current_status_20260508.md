# 研究現在地メモ

作成日: 2026-05-08

このメモは、実装・実験ログ・既存ドキュメントを見直したうえで、卒業研究としての現在地と次に優先する作業を整理したものである。古い調査レポートは当時のスナップショットとして残し、今後はこのメモと README を入口にして進捗を読む。

## 要約

現時点では、機能開発として卒論に必要な核はおおむね揃っている。今後の主作業は、新機能を増やすことではなく、比較実験、集計、図表化、ケーススタディ、卒論本文への変換である。

全体進捗の目安は 65〜70% 程度と見る。実装基盤はかなり進んでいる一方で、卒論提出物としての実験章・図表・本文はまだ整備途中である。

| 項目 | 目安 | 状態 |
| --- | ---: | --- |
| 研究テーマ・問題設定 | 75% | 安全な LLM 応急復旧と仮説固執の比較に寄せる方針が固まっている |
| 実装基盤 | 85% | 構造化アクション、Verifier、Rollback、A-X シナリオ、multi-agent loop が揃っている |
| 比較基盤 | 75% | one-shot / self-critique / multi-agent を走らせられる |
| 実験ログ・初期結果 | 65% | 予備比較と局所実験はあるが、反復実験と統計整理はこれから |
| 図表・ケーススタディ | 35% | 材料はあるが、発表・論文用の図表には未変換 |
| 卒論本文 | 25% | レポート断片は多いが、卒論原稿としては未統合 |

## 既に出せる成果

- Docker Compose ベースの破壊可能な評価環境がある
- A-X の 24 シナリオを定義済み
- single-agent one-shot、single-agent iterative self-critique、multi-agent orchestration を比較できる
- LLM には任意 shell を実行させず、構造化アクションだけを許可している
- Verifier が scope、許可ファイル、restore policy、success checks を検証する
- 失敗時の rollback は service refresh と short postcheck まで含む
- current-state evidence と historical evidence を分け、stale log 混入を扱える
- `incident_blackboard`、reviewer、judge、hypothesis log により multi-turn の判断履歴を保存できる
- production PoC は propose-only を基本に、allowlist restart / runbook / backup / approval gate を扱える

現時点のローカル実績:

- `results/` の結果 JSON: 200 件
- `observations/*/summary.csv`: 9 本、合計 98 試行行
- `hypothesis_metrics` 入り result JSON: 13 件
- pytest テスト関数: 102 件
- `./check.sh`: 99 passed, 6 deselected

## 代表的な予備結果

中間発表や卒論の導入実験としては、次の結果が使いやすい。

| 実験 | 結果 | 位置づけ |
| --- | --- | --- |
| 2026-04-14 hard scenario 予備比較 | single-agent one-shot 0/6、multi-agent 5/6 | multi-turn 再観測・再計画の有効性を示す初期結果 |
| 2026-04-19 multi-agent 局所実験 | `m/n/o/r/u/v/w/x` で 7/8 成功 | cascade と topology / contract mismatch をまとめて扱えた結果 |
| 2026-04-19 OpenAI self-critique baseline | 同 8 シナリオで 3/8 成功 | self-critique は安いが masked cascade で空プランに落ちやすい比較材料 |
| 2026-04-24 hypothesis metrics 付き試行 | `i2` / `n` などで success result を保存 | Phase 4.5 の仮説遷移ログが動いている証拠 |

これらはまだ単発・少数回の予備結果であり、最終的な定量評価としては反復数を増やす必要がある。

## 中間発表で出す範囲

中間発表では、現在あるものを全部出さず、次の切り方にすると卒論までの余白が自然に残る。

> 安全制約付き LLM 応急復旧基盤を実装し、単発 LLM では難しい多段障害に対して、multi-agent の再観測・再計画が有効そうだと分かった。

出すもの:

- 背景: LLM に自由な shell を実行させる危険性
- 提案方針: 構造化アクション、Verifier、Rollback
- 評価環境: Docker Compose の `nginx -> app -> db` と障害注入
- シナリオ: A-X 24 件、特に masked cascade
- 実装: single-agent、multi-agent、reviewer / judge、blackboard
- 予備結果: hard scenario で single-agent one-shot より multi-agent が良い傾向
- 今後: self-critique baseline を含む反復実験、仮説遷移分析、卒論用図表化

温存するもの:

- self-critique との詳細比較
- hypothesis metrics の細かい指標設計
- production PoC の詳細
- 全シナリオの網羅的成功率表
- API コスト比較の細部

## これから優先する作業

1. 比較条件を固定する
   - single-agent one-shot
   - single-agent iterative self-critique
   - multi-agent single-planner
   - 必要なら improved multi-agent

2. 反復実験を回す
   - `i2/m/n/o/r/u` を hard scenario セットにする
   - `v/w/x` を topology / contract mismatch セットにする
   - 各条件で複数回実行し、成功率、turn、stop reason、cost を揃える

3. 仮説遷移メトリクスを揃える
   - Top-1 仮説変更回数
   - 誤仮説固着長
   - 批判後の仮説変化率
   - first-fix success と full recovery
   - re-observation benefit

4. 図表を作る
   - アーキテクチャ図
   - 実行フロー図
   - 成功率比較表
   - hard scenario の turn-by-turn case study
   - 仮説遷移図

5. 卒論本文へ変換する
   - 既存レポートは本文の材料として再利用する
   - 古い進捗評価や既に解決済みのバグ指摘は、本文ではそのまま使わない

## 機能追加の扱い

ここから大きな新機能を増やす優先度は低い。入れるとしても、比較実験の安定性や卒論の説明力に直結するものに限る。

優先してよいもの:

- 実験を壊す parser / invocation / scope 遵守の修正
- 集計スクリプトや CSV 出力の整備
- 図表生成補助
- ログ schema の小さな補正

後回しでよいもの:

- 並列 multi-agent
- dual-planner / planner diversity の本格実装
- UI / dashboard
- production PoC の長期運用機能
- 自動修復アクションの大幅拡張

## 現時点の研究ストーリー

卒論では、次の流れが最も通しやすい。

1. LLM による応急復旧は有望だが、自由な実行は危険である
2. そこで、構造化アクション、Verifier、Rollback を備えた安全な評価基盤を作った
3. 単純故障だけでなく、stale evidence、masked cascade、topology contract mismatch を含む A-X シナリオを用意した
4. 単発の single-agent では、多段障害の初段で止まりやすい
5. multi-agent の reviewer / judge / blackboard を使うと、再観測と再計画によって後段故障に進みやすい
6. self-critique baseline も比較し、自己反省だけで足りる範囲と、外部化された批判・共有状態が効く範囲を整理する
7. 最終的に、どの制御構造が仮説固執を減らし、full recovery に寄与するかを示す

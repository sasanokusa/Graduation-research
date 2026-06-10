# docs/

リポジトリ内ドキュメントの置き場所。Markdown はカテゴリ別に整理し、HTML 化された読みやすい Wiki も同梱する。

## 読み順

最新の進捗判断は、リポジトリルートの [`README.md`](../README.md)(研究ステータス節)→ [`roadmap/next_steps_20260521.md`](roadmap/next_steps_20260521.md)(現行計画)→ [`current_status_20260508.md`](current_status_20260508.md)(前回ベースライン)の順で読む。実験の運用手順と公平性ルールはルートの [`AGENTS.md`](../AGENTS.md)。

## ディレクトリ

- [`current_status_20260508.md`](current_status_20260508.md) — 2026-05-08 時点の研究現在地メモ(スナップショット)
- [`roadmap/`](roadmap/) — 計画(時系列)
  - [`roadmap/next_steps_20260521.md`](roadmap/next_steps_20260521.md) — **現行計画。Experiment 2 / 3 の設計と中間発表までのスケジュール**
  - [`implementation_roadmap_revised_20260415.md`](roadmap/implementation_roadmap_revised_20260415.md) — 改訂版(2026-04-15、historical)
  - [`implementation_roadmap_20260316.md`](roadmap/implementation_roadmap_20260316.md) — 初版(2026-03-16、historical)
- [`reports/`](reports/) — 実験レポート・調査・コスト・予算
  - [`experiment2_baseline_comparison_20260521.md`](reports/experiment2_baseline_comparison_20260521.md) — **Experiment 2 本比較(5 条件 × repeat 3)の結果**
  - [`experiment2_3_escalation_comparison_20260527.md`](reports/experiment2_3_escalation_comparison_20260527.md) — **x 観測改善と Experiment 3 escalation smoke の結果**
  - [`related_work_survey_20260610.md`](reports/related_work_survey_20260610.md) — **関連研究サーベイ(URL 検証済み)**
  - [`token_reduction_validation_20260610.md`](reports/token_reduction_validation_20260610.md) — **トークン削減検証 + 5/22 実験汚染・r credential 交絡の発見**
  - [`controlled_gpt54_fairness_experiment_20260520.md`](reports/controlled_gpt54_fairness_experiment_20260520.md) — Experiment 1 公平化予備比較
  - [`safety_metrics_report.md`](reports/safety_metrics_report.md) — 安全性メトリクスの定義と集計
  - [`planner_escalation_cost_comparison_20260520.md`](reports/planner_escalation_cost_comparison_20260520.md) — escalation コスト予備比較
  - [`agent_prompt_and_scenario_surface_20260521.md`](reports/agent_prompt_and_scenario_surface_20260521.md) — prompt / scenario surface の棚卸し
  - [`self_critique_gpt54_local_experiment_20260509.md`](reports/self_critique_gpt54_local_experiment_20260509.md) — self-critique 局所実験
  - [`budget_estimate_2026.md`](reports/budget_estimate_2026.md) — 卒研予算概算と支払い方法(申請用, 2026-05-29)
  - [`local_experiment_cost_report_20260419.md`](reports/local_experiment_cost_report_20260419.md) / [`phase1_compare_cost_report_20260414.md`](reports/phase1_compare_cost_report_20260414.md) — 初期コストレポート(historical)
  - [`analysis_report.md`](reports/analysis_report.md) / [`repository_assessment_20260316.md`](reports/repository_assessment_20260316.md) — 初期調査(historical)
- [`hypothesis_transition_evaluation.md`](hypothesis_transition_evaluation.md) — 仮説遷移評価 (Phase 4.5)
- [`production_poc/`](production_poc/) — Ubuntu 実ホスト向け Production PoC ドキュメント群
- [`scenarios/`](scenarios/) — 個別シナリオ資料
  - [`ictsc_5023.md`](scenarios/ictsc_5023.md) — ICTSC 5023「今夜の IRC」
- [`wiki/`](wiki/) — 上記を一通り HTML 化した Wiki
- [`AGENTS.md`](AGENTS.md) — Wiki の更新手順(エージェント向け)

## Wiki を開く

```sh
open docs/wiki/index.html      # macOS
xdg-open docs/wiki/index.html  # Linux
```

ブラウザでサイドバーから各ページに辿れる。各ページの末尾には対応する Markdown ソースへのリンクがある。

## Wiki を再生成する

ソース Markdown を編集したら以下を実行する。pandoc が必要。

```sh
docs/wiki/_build.sh
```

ビルドスクリプトは `docs/wiki/_template.html` をテンプレートに、`docs/wiki/_link_map.sed` でドキュメント間リンクを Wiki ページに書き換えてから pandoc を呼ぶ。新しい Markdown を Wiki に追加するときは、`_build.sh` にエントリを足し、`_template.html` と `index.html` のサイドバー／カードに項目を追加する。

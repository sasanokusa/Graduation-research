# docs/

リポジトリ内ドキュメントの置き場所。Markdown はカテゴリ別に整理し、HTML 化された読みやすい Wiki も同梱する。

## ディレクトリ

- [`roadmap/`](roadmap/) — 実装ロードマップ（時系列）
  - [`implementation_roadmap_20260316.md`](roadmap/implementation_roadmap_20260316.md) — 初版（2026-03-16）
  - [`implementation_roadmap_revised_20260415.md`](roadmap/implementation_roadmap_revised_20260415.md) — 改訂版（2026-04-15）。**現在の指針はこちら。**
- [`reports/`](reports/) — 調査レポート・コストレポート・設計レビュー
  - [`repository_assessment_20260316.md`](reports/repository_assessment_20260316.md)
  - [`analysis_report.md`](reports/analysis_report.md)
  - [`phase1_compare_cost_report_20260414.md`](reports/phase1_compare_cost_report_20260414.md)
  - [`local_experiment_cost_report_20260419.md`](reports/local_experiment_cost_report_20260419.md)
- [`hypothesis_transition_evaluation.md`](hypothesis_transition_evaluation.md) — 仮説遷移評価 (Phase 4.5)
- [`production_poc/`](production_poc/) — Ubuntu 実ホスト向け Production PoC ドキュメント群
- [`scenarios/`](scenarios/) — 個別シナリオ資料
  - [`ictsc_5023.md`](scenarios/ictsc_5023.md) — ICTSC 5023「今夜の IRC」
- [`wiki/`](wiki/) — 上記を一通り HTML 化した Wiki

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

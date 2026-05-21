#!/usr/bin/env bash
# Wiki build script. Runs pandoc against markdown sources to produce flat HTML
# pages under docs/wiki/, using _template.html for layout and _link_map.sed
# to rewrite inter-document links to their wiki targets.
set -euo pipefail

cd "$(dirname "$0")"
WIKI_DIR="$(pwd)"
ROOT_DIR="$(cd ../.. && pwd)"
TEMPLATE="$WIKI_DIR/_template.html"
LINK_MAP="$WIKI_DIR/_link_map.sed"

build() {
  local src="$1"        # path relative to ROOT_DIR
  local out="$2"        # output filename inside wiki/
  local title="$3"
  local breadcrumb="$4"
  local source_link="$5"

  local tmp
  tmp="$(mktemp -t wiki_src.XXXXXX).md"
  sed -E -f "$LINK_MAP" "$ROOT_DIR/$src" > "$tmp"

  pandoc "$tmp" \
    --from gfm \
    --to html5 \
    --standalone \
    --template "$TEMPLATE" \
    --metadata title="$title" \
    --variable breadcrumb="$breadcrumb" \
    --metadata source="$source_link" \
    -o "$WIKI_DIR/$out"

  rm -f "$tmp"
  echo "  built $out"
}

echo "Building wiki..."

build "README.md" "overview.html" \
  "プロジェクト概要" \
  '<a href="index.html">Wiki</a> / 概要' \
  "../../README.md"

build "docs/current_status_20260508.md" "current-status.html" \
  "研究現在地メモ (2026-05-08)" \
  '<a href="index.html">Wiki</a> / 現在地' \
  "../current_status_20260508.md"

build "docs/roadmap/implementation_roadmap_20260316.md" "roadmap-initial.html" \
  "初版ロードマップ (2026-03-16)" \
  '<a href="index.html">Wiki</a> / ロードマップ / 初版' \
  "../roadmap/implementation_roadmap_20260316.md"

build "docs/roadmap/implementation_roadmap_revised_20260415.md" "roadmap-revised.html" \
  "改訂版ロードマップ (2026-04-15)" \
  '<a href="index.html">Wiki</a> / ロードマップ / 改訂版' \
  "../roadmap/implementation_roadmap_revised_20260415.md"

build "docs/roadmap/next_steps_20260521.md" "roadmap-next-steps.html" \
  "次のステップ計画 (2026-05-21)" \
  '<a href="index.html">Wiki</a> / ロードマップ / 次のステップ' \
  "../roadmap/next_steps_20260521.md"

build "docs/reports/repository_assessment_20260316.md" "report-repository-assessment.html" \
  "リポジトリ調査レポート" \
  '<a href="index.html">Wiki</a> / レポート / リポジトリ調査' \
  "../reports/repository_assessment_20260316.md"

build "docs/reports/analysis_report.md" "report-analysis.html" \
  "設計レビュー・改善提案" \
  '<a href="index.html">Wiki</a> / レポート / 設計レビュー' \
  "../reports/analysis_report.md"

build "docs/reports/phase1_compare_cost_report_20260414.md" "report-phase1-cost.html" \
  "Phase 1 比較実験コスト" \
  '<a href="index.html">Wiki</a> / レポート / Phase 1 比較コスト' \
  "../reports/phase1_compare_cost_report_20260414.md"

build "docs/reports/local_experiment_cost_report_20260419.md" "report-local-experiment-cost.html" \
  "局所実験コスト" \
  '<a href="index.html">Wiki</a> / レポート / 局所実験コスト' \
  "../reports/local_experiment_cost_report_20260419.md"

build "docs/reports/self_critique_gpt54_local_experiment_20260509.md" "report-selfcritique-gpt54-local.html" \
  "GPT-5.4 self-critique 局所実験" \
  '<a href="index.html">Wiki</a> / レポート / GPT-5.4 self-critique 局所実験' \
  "../reports/self_critique_gpt54_local_experiment_20260509.md"

build "docs/reports/safety_metrics_report.md" "report-safety-metrics.html" \
  "安全性メトリクス・Judge介入分析レポート" \
  '<a href="index.html">Wiki</a> / レポート / 安全性メトリクス・Judge介入' \
  "../reports/safety_metrics_report.md"

build "docs/reports/controlled_gpt54_fairness_experiment_20260520.md" "report-controlled-gpt54-fairness.html" \
  "GPT-5.4 公平条件比較実験" \
  '<a href="index.html">Wiki</a> / レポート / GPT-5.4 公平条件比較実験' \
  "../reports/controlled_gpt54_fairness_experiment_20260520.md"

build "docs/reports/planner_escalation_cost_comparison_20260520.md" "report-planner-escalation-cost.html" \
  "Planner Escalation コスト比較" \
  '<a href="index.html">Wiki</a> / レポート / Planner Escalation コスト比較' \
  "../reports/planner_escalation_cost_comparison_20260520.md"

build "docs/hypothesis_transition_evaluation.md" "evaluation-hypothesis-transition.html" \
  "仮説遷移評価 (Phase 4.5)" \
  '<a href="index.html">Wiki</a> / 評価 / 仮説遷移' \
  "../hypothesis_transition_evaluation.md"

build "docs/production_poc/architecture.md" "poc-architecture.html" \
  "Production PoC アーキテクチャ" \
  '<a href="index.html">Wiki</a> / Production PoC / アーキテクチャ' \
  "../production_poc/architecture.md"

build "docs/production_poc/deploy.md" "poc-deploy.html" \
  "Production PoC 導入手順" \
  '<a href="index.html">Wiki</a> / Production PoC / 導入手順' \
  "../production_poc/deploy.md"

build "docs/production_poc/validation_scenarios.md" "poc-validation-scenarios.html" \
  "Production PoC 実機検証シナリオ" \
  '<a href="index.html">Wiki</a> / Production PoC / 実機検証' \
  "../production_poc/validation_scenarios.md"

build "docs/scenarios/ictsc_5023.md" "scenario-ictsc5023.html" \
  "ICTSC 5023" \
  '<a href="index.html">Wiki</a> / シナリオ / ICTSC 5023' \
  "../scenarios/ictsc_5023.md"

echo "Wiki build complete."

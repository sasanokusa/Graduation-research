# Rewrite inter-document markdown links so they point at the flat wiki pages
# rather than the .md sources. Applied to each source file before pandoc.
s|\.\./reports/repository_assessment_20260316\.md|report-repository-assessment.html|g
s|\.\./reports/analysis_report\.md|report-analysis.html|g
s|\.\./reports/phase1_compare_cost_report_20260414\.md|report-phase1-cost.html|g
s|\.\./reports/local_experiment_cost_report_20260419\.md|report-local-experiment-cost.html|g
s|\.\./reports/self_critique_gpt54_local_experiment_20260509\.md|report-selfcritique-gpt54-local.html|g
s|\.\./reports/safety_metrics_report\.md|report-safety-metrics.html|g
s|docs/reports/safety_metrics_report\.md|report-safety-metrics.html|g
s|\.\./reports/controlled_gpt54_fairness_experiment_20260520\.md|report-controlled-gpt54-fairness.html|g
s|docs/reports/controlled_gpt54_fairness_experiment_20260520\.md|report-controlled-gpt54-fairness.html|g
s|\.\./reports/planner_escalation_cost_comparison_20260520\.md|report-planner-escalation-cost.html|g
s|docs/reports/planner_escalation_cost_comparison_20260520\.md|report-planner-escalation-cost.html|g
s|implementation_roadmap_20260316\.md|roadmap-initial.html|g
s|implementation_roadmap_revised_20260415\.md|roadmap-revised.html|g
s|hypothesis_transition_evaluation\.md|evaluation-hypothesis-transition.html|g
s|production_poc/architecture\.md|poc-architecture.html|g
s|production_poc/deploy\.md|poc-deploy.html|g
s|production_poc/validation_scenarios\.md|poc-validation-scenarios.html|g
s|scenarios/ictsc_5023\.md|scenario-ictsc5023.html|g
s|\.\./current_status_20260508\.md|current-status.html|g
s|docs/current_status_20260508\.md|current-status.html|g
s|current_status_20260508\.md|current-status.html|g

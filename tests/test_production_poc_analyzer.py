from experimental.production_poc.adapters.llm_analyzer import RuleBasedIncidentAnalyzer


def test_rule_based_analyzer_dedupes_identical_restart_actions_and_causes() -> None:
    analyzer = RuleBasedIncidentAnalyzer()

    outcome = analyzer.analyze(
        {
            "snapshot_context": {
                "detected_web": {"service_name": "apache2"},
                "detected_minecraft": {"service_name": "", "management_mode": "shell_script"},
            },
            "findings": [
                {
                    "id": "web_service_inactive",
                    "title": "Web service is not active",
                    "summary": "The detected web service is not active under systemd.",
                    "evidence": ["inactive"],
                },
                {
                    "id": "web_http_failed",
                    "title": "HTTP health check failed",
                    "summary": "The inferred web health endpoint failed.",
                    "evidence": ["status=None"],
                },
                {
                    "id": "web_listen_missing",
                    "title": "Web listener is missing",
                    "summary": "The expected web listener could not be found.",
                    "evidence": ["port=80"],
                },
            ],
        }
    )

    assert len(outcome.proposed_actions) == 1
    assert outcome.proposed_actions[0].kind == "restart_service"
    assert outcome.proposed_actions[0].service == "apache2"
    assert len(outcome.likely_causes) == 1

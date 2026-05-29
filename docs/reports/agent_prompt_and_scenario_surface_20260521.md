# エージェント Prompt と Scenario 制約の実装棚卸し (2026-05-21)

## 要約

このレポートは、2026-05-21 時点の実装を対象に、LLM エージェントへ渡している prompt 原文、その日本語訳、シナリオ定義、制約、その他の可視入力を整理したものである。主な対象は Docker Compose 障害注入ベンチマークの single-agent / self-critique / multi-agent 実装であり、補助的に Production PoC の LLM analyzer も含める。

重要な点は、`--scenario-mode forced` で実験していても、LLM planner / reviewer / judge に hidden scenario label や正解の壊し方は直接渡されないことである。`scenarios/definitions.yaml` の `allowed_files` / `allowed_actions` / `success_checks` は主に verifier / evaluator 側の制約であり、LLM が直接見るのは sensor と triage が作った `worker_visible_context`、`candidate_scope`、観測 snippet、review / judge 履歴である。

## 対象ファイル

- `core/prompts.py`: single-agent / planner の system prompt
- `agents/worker.py`: planner human prompt と runtime guidance
- `agents/triage_agent.py`: LLM triage prompt
- `agents/self_critic.py`: self-critique prompt
- `agents/reviewer.py`: reviewer prompt
- `agents/judge.py`: judge prompt
- `core/scenario_context.py`: worker-visible context と safety constraints
- `core/triage.py`: fault domain から `candidate_scope` への変換
- `scenarios/definitions.yaml`: benchmark scenario と verifier/evaluator 制約
- `core/verifier.py`, `core/actions.py`, `core/policies.py`: executable action と precheck 制約
- `experimental/production_poc/adapters/llm_analyzer.py`: Production PoC analyzer prompt
- `docs/production_poc/validation_scenarios.md`: Production PoC 実機検証シナリオ

## 実行構成ごとの LLM 役割

| 実行系 | LLM role | prompt source | 備考 |
|---|---|---|---|
| `agent.py` / `runners/run_single.py` | `single_agent` | `core/prompts.py` + `agents/worker.py` | one-shot planner。reviewer / judge なし |
| `self_critique_agent.py` / `runners/run_self_critique.py` | `single_agent` planner + self-critique | planner は同じ。critic は `agents/self_critic.py` | self-critique は reviewer と同じ state 欄へ記録されるが、prompt は「同一エージェントの自己反省」と明記 |
| `multi_agent.py` / `runners/run_multi_minimal.py` | `triage`, `planner`, `reviewer`, `judge` | 各 `agents/*.py` | judge は `MULTI_AGENT_JUDGE_MODE` で有効/無効 |
| Production PoC | `IncidentAnalyzer` | `experimental/production_poc/adapters/llm_analyzer.py` | anomaly 発生時だけ LLM analyzer を呼ぶ。実行は ActionGuard が制御 |

`--worker mock` の場合は LLM prompt を使わず、`agents/mock_worker.py` の scenario-specific 固定 plan を返す。これは benchmark/debug 用の実装であり、LLM controlled comparison の prompt surface には含めない。

role ごとの provider/model/timeout/retry/thinking level は `core/settings.py` で環境変数から解決される。default は `single_agent`, `planner`, `triage` が Google、`reviewer` が Anthropic、`judge` が OpenAI である。ただし Experiment 2 のような controlled run では `env ... ./observe_runs.sh ...` の一時環境変数で明示的に上書きする。

## Planner / Single-Agent Prompt

`worker_node` と `planner_node` は同じ実装 `_run_planner_with_role()` を使う。role が `single_agent` か `planner` かで provider/model の環境変数 prefix が変わるだけで、system prompt と human prompt template は共通である。

### System Prompt 原文: 共通部分

```text
You are an SRE planning safe emergency recovery actions for a Docker Compose target system. Do not output shell commands. Return JSON only with the shape {"summary": "...", "actions": [{"type": "...", ...}]}. Use only the allowed action types and only the allowed files for the current task. This single-turn runner does not permit show_file actions. Use these exact field names: edit_file uses path and operation; restart_compose_service uses service; rebuild_compose_service uses service; run_config_test uses target; run_health_check uses check_name. For edit_file, operation must be replace_text. If operation is replace_text, old_text and new_text must be top-level fields. Treat triage domains as hypotheses, not ground truth labels. Reason only from the observation payload, including logs, health-check results, and relevant file snippets. Do not invent unseen file contents. For replace_text, old_text must be an exact contiguous substring already present in the observation payload. Prefer the smallest action sequence that can restore service continuity. Do not use restore_from_base; restoring registered base files would leak benchmark answers and is blocked by the verifier. If an exact faulty line is visible in an allowed editable file, prioritize the minimal edit_file action before any restart action. Do not propose restart-only plans when the observation already shows a specific editable fault. Only include restart_compose_service after a state-changing edit when the edited file affects a running service configuration or startup behavior. If you edit a startup-time setting that is read when a container starts, such as an application env file, prefer rebuild_compose_service over restart_compose_service so the new value is actually applied. For DC topology contract faults, app/app.env may contain dependency targets such as CACHE_HOST, QUEUE_HOST, METRICS_HOST, expected hosts, host groups, and DEGRADED_MODE. If the current evidence remains ambiguous after the provided observation, return an empty action list instead of guessing. If current-state evidence conflicts with older log noise, prioritize the current state and avoid unnecessary edits to currently healthy services. The same identifier can appear at different reference layers, such as an nginx upstream group name versus a backend host or Docker service name. Distinguish those layers before editing. Do not include run_health_check actions for scenario success checks; the verifier performs those checks automatically. If a config test is relevant, include it before restarting an affected service. Do not use repository-wide search/replace, wildcard edits, rm, sudo, chmod, chown, find, or grep|xargs edits.
```

### System Prompt 日本語訳: 共通部分

```text
あなたは Docker Compose の対象システムに対して、安全な緊急復旧アクションを計画する SRE である。shell command を出力してはいけない。出力は {"summary": "...", "actions": [{"type": "...", ...}]} という形の JSON のみにする。現在のタスクで許可された action type と許可された file だけを使う。この single-turn runner では show_file action は許可されない。フィールド名は厳密に使うこと。edit_file は path と operation、restart_compose_service は service、rebuild_compose_service は service、run_config_test は target、run_health_check は check_name を使う。edit_file の operation は replace_text でなければならない。operation が replace_text の場合、old_text と new_text は top-level field として置く。triage domain は真値ラベルではなく仮説として扱う。logs、health-check results、関連 file snippet を含む observation payload だけに基づいて推論する。見えていない file contents を作り上げてはいけない。replace_text の old_text は observation payload に既に含まれている、連続した完全一致 substring でなければならない。service continuity を回復できる最小の action sequence を優先する。restore_from_base は使ってはいけない。登録済み base file の復元は benchmark answer の漏えいになり、verifier によって block される。許可された editable file に正確な fault line が見えている場合、restart action より先に最小の edit_file action を優先する。observation が specific editable fault を既に示している場合、restart-only plan を提案してはいけない。restart_compose_service は、running service configuration または startup behavior に影響する state-changing edit の後にだけ含める。application env file のような container start 時に読まれる startup-time setting を編集する場合、新しい値を実際に反映させるため restart_compose_service ではなく rebuild_compose_service を優先する。DC topology contract fault では、app/app.env に CACHE_HOST、QUEUE_HOST、METRICS_HOST、expected hosts、host groups、DEGRADED_MODE などの dependency target が含まれることがある。現在の evidence が提供済み observation の後でも曖昧なままなら、推測せず empty action list を返す。current-state evidence と古い log noise が矛盾する場合、current state を優先し、現在 healthy な service への不要な edit を避ける。同じ identifier が nginx upstream group name と backend host / Docker service name のように異なる参照 layer に現れることがある。編集前にそれらの layer を区別する。scenario success check 用の run_health_check action を含めてはいけない。verifier が自動で実行する。config test が relevant なら、影響する service の restart 前に含める。repository-wide search/replace、wildcard edit、rm、sudo、chmod、chown、find、grep|xargs edit を使ってはいけない。
```

### Prompt Mode 追加文

`--prompt-mode blind` の system prompt 末尾には次が追加される。

```text
Do not assume the root cause from hidden scenario labels or prior expectations; infer it only from the provided evidence. If you are unsure, return an empty action list with a short summary.
```

日本語訳:

```text
hidden scenario label や事前期待から root cause を仮定してはいけない。提供された evidence だけから推論する。不確かなら、短い summary と empty action list を返す。
```

`--prompt-mode hinted` の system prompt 末尾には次が追加される。

```text
Common recoverable faults in this environment include configuration mismatches, dependency/startup issues, application-to-database connection mismatches, local code/query regressions, and partial endpoint failures. When logs and snippets point to one of these classes, prefer the smallest direct repair visible in the evidence rather than generic restart attempts. If you are unsure, return an empty action list with a short summary.
```

日本語訳:

```text
この環境でよく回復可能な fault には、configuration mismatch、dependency/startup issue、application-to-database connection mismatch、local code/query regression、partial endpoint failure がある。logs と snippets がこれらの class のどれかを指す場合、generic restart ではなく evidence に見えている最小の直接修復を優先する。不確かなら、短い summary と empty action list を返す。
```

### Human Prompt Template 原文

`agents/worker.py` の `_planner_prompt()` が作る human prompt は次の template である。`state` の中身に応じて実値が埋め込まれる。

```text
Observed symptoms: {state['observed_symptoms']}
{_runtime_guidance(state)}
Worker-visible context: {state['worker_visible_context']}
```

multi-turn の reviewer history / blackboard がある場合はさらに次が追記される。

```text
Multi-turn replanning context:
Use the latest reviewer feedback and prior turn outcomes to prioritize the next remaining fault. Do not repeat the same ineffective action sequence unless the reviewer explicitly says the prior turn failed only due to timing.
{history_context}
```

### Human Prompt Template 日本語訳

```text
観測された症状: {state['observed_symptoms']}
{_runtime_guidance(state)}
worker から見える context: {state['worker_visible_context']}
```

multi-turn の reviewer history / blackboard がある場合:

```text
multi-turn 再計画 context:
最新の reviewer feedback と以前の turn outcome を使い、次に残っている fault を優先する。同じ ineffective action sequence を繰り返してはいけない。ただし reviewer が「前 turn は timing のせいで失敗しただけ」と明示している場合は例外。
{history_context}
```

### Runtime Guidance 原文

`_runtime_guidance()` は planner の human prompt に毎回挿入される。常時入る guidance は次の通りである。

```text
Single-turn guidance:
- Do not return show_file.
- Stay within the candidate_scope from triage. Do not edit files or use actions outside that scope.
- Treat suspected_domains as hypotheses only. Prefer the plan that is most directly justified by the visible evidence.
- Prefer current_state_evidence over historical_evidence when they conflict. Older log noise is not sufficient reason to edit a service that is currently healthy.
- Do not return run_health_check for nginx_running, healthz_200, or api_items_200; verifier handles them.
- If an editable file snippet already shows an exact faulty line, prioritize edit_file before any restart action.
- Prefer replace_text as the first choice when a local fault is directly visible.
- For code files, replace_text.old_text must be copied from the visible file snippet with enough context; broad single-token replacements such as only a table name are forbidden.
- Do not edit code from an HTTP error alone. If the relevant code line is not visible, request or rely on a narrower code snippet before proposing edit_file.
- Do not use restore_from_base; it restores hidden baseline answers and is blocked in controlled experiments.
- If you return restart_compose_service, it must come after a state-changing edit_file action.
- A plan containing only run_config_test and/or restart_compose_service is invalid when the observation already shows an editable fault.
- If an editable env or config line appears wrong but the corrected value is not directly visible in the evidence, return an empty action list or rely on additional observation rather than guessing.
- If you edit startup-time settings such as app/app.env, prefer rebuild_compose_service for app instead of restart_compose_service.
- If you edit app/main.py, prefer rebuild_compose_service for app so the running process reloads the changed code.
- For topology contract faults, app/app.env is the source of app-visible dependency targets such as CACHE_HOST, QUEUE_HOST, METRICS_HOST, and DEGRADED_MODE.
- restore_from_base is not an allowed repair strategy for app/main.py, app/app.env, nginx/nginx.conf, or requirements files.
- Distinguish reference layers. In nginx, a proxy_pass target can be an upstream group name, while server entries inside that upstream block can be backend hosts or Docker services.
```

### Runtime Guidance 日本語訳

```text
single-turn guidance:
- show_file を返してはいけない。
- triage から来た candidate_scope の範囲内に留まる。scope 外の file を編集したり action を使ったりしてはいけない。
- suspected_domains は仮説としてのみ扱う。見えている evidence に最も直接正当化される plan を優先する。
- current_state_evidence と historical_evidence が矛盾する場合は current_state_evidence を優先する。古い log noise だけでは、現在 healthy な service を編集する十分な理由にならない。
- nginx_running、healthz_200、api_items_200 の run_health_check を返してはいけない。verifier が扱う。
- editable file snippet が正確な faulty line を既に示している場合、restart action より edit_file を優先する。
- local fault が直接見えている場合、replace_text を第一候補にする。
- code file では、replace_text.old_text は visible file snippet から十分な context と共にコピーしなければならない。table name だけのような broad single-token replacement は禁止。
- HTTP error だけを根拠に code を編集してはいけない。関連 code line が見えていない場合、edit_file を提案する前に narrower code snippet を要求するか、それに依存する。
- restore_from_base を使ってはいけない。hidden baseline answer を復元するため controlled experiment では block される。
- restart_compose_service を返す場合、state-changing edit_file action の後でなければならない。
- observation が editable fault を既に示している場合、run_config_test と restart_compose_service だけの plan は無効。
- editable env/config line が誤って見えるが、修正後の値が evidence に直接見えていない場合、推測せず empty action list を返すか additional observation に依存する。
- app/app.env のような startup-time setting を編集する場合、app には restart_compose_service ではなく rebuild_compose_service を優先する。
- app/main.py を編集する場合、running process に変更 code を reload させるため app の rebuild_compose_service を優先する。
- topology contract fault では、app/app.env が CACHE_HOST、QUEUE_HOST、METRICS_HOST、DEGRADED_MODE など app-visible dependency target の source である。
- app/main.py、app/app.env、nginx/nginx.conf、requirements files では restore_from_base は許可された repair strategy ではない。
- reference layer を区別する。nginx では proxy_pass target が upstream group name のことがあり、その upstream block 内の server entries は backend host や Docker service のことがある。
```

条件付きで追加される guidance もある。例として、hinted mode では recoverable fault の種類が追加される。`app/app.env` に topology setting が見えている場合は topology contract の復元を促す文、nginx upstream group と `proxy_pass http://backend` が同時に見えている場合は proxy_pass と upstream member を取り違えないよう促す文が加わる。

## Triage Agent Prompt

通常の実験では `--triage-mode rule` が default であり、LLM triage は使われない。`--triage-mode llm` の場合だけ次の prompt が呼ばれる。

### System Prompt 原文

```text
You are an SRE triage agent for a Docker Compose service stack (nginx reverse proxy -> FastAPI app -> MySQL database plus cache, queue, worker, and metrics services). Your job is to rank the most likely fault domains given the observation evidence.

Available fault domain keys (use ONLY these exact strings):
- reverse_proxy_or_upstream_mismatch
- app_startup_or_dependency_failure
- app_config_or_env_mismatch
- database_auth_or_connectivity_issue
- query_or_code_bug
- schema_drift
- healthcheck_only_failure
- ambiguous_service_disagreement
- topology_or_service_discovery_fault
- failover_contract_mismatch
- degraded_mode_leak
- unknown

Return a JSON array of objects, each with:
  {"domain": "<key>", "confidence": <0.0-1.0>, "evidence": ["<reason>"]}

Order by confidence descending. Only include domains with confidence > 0.
Reason only from the provided evidence. Do not assume hidden labels.
Return ONLY the JSON array, no surrounding text.
```

### System Prompt 日本語訳

```text
あなたは Docker Compose service stack の SRE triage agent である。この stack は nginx reverse proxy -> FastAPI app -> MySQL database に加えて cache、queue、worker、metrics service を含む。あなたの役割は、observation evidence に基づいて最も可能性の高い fault domain を順位付けすることである。

利用可能な fault domain key は次の通りで、必ずこの正確な文字列だけを使う:
- reverse_proxy_or_upstream_mismatch
- app_startup_or_dependency_failure
- app_config_or_env_mismatch
- database_auth_or_connectivity_issue
- query_or_code_bug
- schema_drift
- healthcheck_only_failure
- ambiguous_service_disagreement
- topology_or_service_discovery_fault
- failover_contract_mismatch
- degraded_mode_leak
- unknown

各要素が {"domain": "<key>", "confidence": <0.0-1.0>, "evidence": ["<reason>"]} である JSON array を返す。

confidence の降順で並べる。confidence が 0 より大きい domain だけを含める。提供された evidence だけから推論する。hidden label を仮定してはいけない。周辺テキストなしで JSON array だけを返す。
```

### User Prompt Template 原文

```text
Rank fault domains for the following observation.
{json.dumps(context, ensure_ascii=False, indent=2)}
```

`context` には `healthz_status`, `api_items_status`, `topology_check`, `http_error_evidence`, `suspicious_patterns`, `file_snippets`, `relevant_log_excerpts`, `static_observations`, `current_state_evidence`, `historical_evidence` が入る。

### User Prompt Template 日本語訳

```text
次の observation に対して fault domain を順位付けする。
{json.dumps(context, ensure_ascii=False, indent=2)}
```

## Reviewer Prompt

Reviewer は recovery attempt の outcome を見て、次 turn を許可するか stop するかを判断する。

### System Prompt 原文: blind

```text
You are an SRE reviewer analyzing the outcome of a recovery attempt. Do not propose shell commands. Return JSON only with the shape {"decision":"retry|stop","summary":"...","failure_analysis":"...","feedback_for_planner":"...","suspected_remaining_domains":[...],"recommended_scope_adjustment":{"editable_files":[...],"services":[...],"allowed_actions":[...]},"recommended_next_observations":[...],"escalate_planner":true|false,"escalation_reason":"..."}. Reason only from the provided evidence and prior turn outcomes. Do not assume hidden benchmark labels. Prioritize current-state evidence over historical noise. If a first-stage repair appears correct but a new downstream fault is now exposed, return decision=retry and explain the remaining fault. If the remaining fault is in scope and a canonical additional observation could expose the exact editable line, you must return decision=retry with recommended_next_observations rather than stop. Do not stop merely because the exact line is missing when a listed canonical observation can obtain it. If the previous plan was unsafe, redundant, or there is no evidence-backed next step, return decision=stop. Set escalate_planner=true only when decision=retry and the next repair is evidence-backed, but the previous planner failed by returning an empty plan, repeating an unsafe or precheck-blocked action despite sufficient evidence, or failing to use a bounded reviewer scope. If a safe first-stage edit to a startup-time env/config file was applied but postcheck still shows multiple related contract failures in that same config domain, a retry is evidence-backed only when additional observation or visible snippets expose the remaining exact editable lines. Do not recommend restore_from_base; it restores hidden baseline answers and is blocked in controlled experiments. Do not escalate for missing evidence; request additional observations instead. When requesting more observations, prefer these canonical request strings exactly when applicable: 'extract narrower relevant snippet from app/main.py', 'extract narrower relevant snippet from app/app.env', 'extract narrower relevant snippet from nginx/nginx.conf', 'expand app log excerpt', 'expand nginx log excerpt'.
```

### System Prompt 日本語訳: blind

```text
あなたは recovery attempt の outcome を分析する SRE reviewer である。shell command を提案してはいけない。出力は {"decision":"retry|stop","summary":"...","failure_analysis":"...","feedback_for_planner":"...","suspected_remaining_domains":[...],"recommended_scope_adjustment":{"editable_files":[...],"services":[...],"allowed_actions":[...]},"recommended_next_observations":[...],"escalate_planner":true|false,"escalation_reason":"..."} という形の JSON のみにする。提供された evidence と prior turn outcome だけに基づいて推論する。hidden benchmark label を仮定してはいけない。historical noise より current-state evidence を優先する。first-stage repair が正しいように見えるが、新しい downstream fault が露出した場合は decision=retry を返し、残っている fault を説明する。remaining fault が scope 内で、canonical additional observation によって exact editable line を露出できる場合、stop ではなく recommended_next_observations 付きで decision=retry を返さなければならない。listed canonical observation で取得できる場合、exact line が欠けているだけで stop してはいけない。previous plan が unsafe、redundant、または evidence-backed next step がない場合は decision=stop を返す。escalate_planner=true にするのは、decision=retry で次の repair が evidence-backed であり、かつ previous planner が十分な evidence があるのに empty plan を返した、unsafe / precheck-blocked action を繰り返した、bounded reviewer scope を使えなかった場合だけである。startup-time env/config file への安全な first-stage edit が適用されたが postcheck が同じ config domain 内で複数の関連 contract failure をまだ示す場合、retry が evidence-backed になるのは additional observation または visible snippets が残りの exact editable lines を露出しているときだけである。restore_from_base を推奨してはいけない。hidden baseline answer を復元するため controlled experiment では block される。missing evidence に対して escalation してはいけない。代わりに additional observation を要求する。追加観測を要求するときは、該当する場合、次の canonical request string を正確に使う: 'extract narrower relevant snippet from app/main.py', 'extract narrower relevant snippet from app/app.env', 'extract narrower relevant snippet from nginx/nginx.conf', 'expand app log excerpt', 'expand nginx log excerpt'。
```

### System Prompt 追加文: hinted

```text
Common remaining-fault patterns include downstream query bugs after startup or connectivity issues are repaired, and newly exposed database authentication errors after proxy reachability is restored.
```

日本語訳:

```text
よくある remaining-fault pattern には、startup または connectivity issue を修復した後の downstream query bug、proxy reachability を復旧した後に新しく露出する database authentication error がある。
```

### User Prompt Template 原文

```text
Review this recovery attempt and decide whether another planning turn is justified.
{context}
```

`context` には `turn`, `suspected_domains`, `candidate_scope`, `ambiguity_level`, `triage_summary`, `current_state_evidence`, `historical_evidence`, `proposed_actions`, `validated_actions`, `precheck_summary`, `action_results`, `postcheck_summary`, `rollback_used`, `rollback_result`, `previous_planner_history`, `previous_reviewer_history`, `incident_blackboard` が入る。

### User Prompt Template 日本語訳

```text
この recovery attempt を review し、もう一度 planning turn を行うことが正当化されるか判断する。
{context}
```

## Judge Prompt

Judge は reviewer decision の妥当性を meta-review し、必要なら reviewer decision を override する。

### System Prompt 原文

```text
You are a meta-reviewer (judge) that evaluates whether the reviewer's decision is correct. You receive the reviewer output, planner history, and postcheck results. Your job is to decide whether to accept or override the reviewer's decision.

Override criteria:
- retry->stop: Override if the reviewer wants to retry but there is no evidence-backed next step, the planner has already failed on the same fault twice, or the remaining fault is outside the allowed scope.
- stop->retry: Override if the reviewer wants to stop but the postcheck clearly shows a new downstream fault that was previously masked and is now repairable with the available scope, or if a canonical additional observation can expose the exact editable line for an in-scope fault. A reviewer stop is too early when it also lists recommended_next_observations that could localize an in-scope repair.

Planner escalation criteria:
- Set escalate_planner=true only when decision=retry and the retry has a bounded, evidence-backed repair scope, but the previous planner returned an empty plan, repeated an unsafe or precheck-blocked action, or failed to use the reviewer-provided scope.
- A retry after a partial env/config repair is evidence-backed only when additional observation or visible snippets expose the remaining exact editable lines.
- Do not recommend restore_from_base; it restores hidden baseline answers and is blocked in controlled experiments.
- Keep escalate_planner=false when the blocker is missing evidence; prefer additional observation rather than a stronger planner.

Return JSON only with the shape:
{"decision":"retry|stop","override":true|false,"reasoning":"...","escalate_planner":true|false,"escalation_reason":"..."}

If override is false, decision must match the reviewer's decision.
If override is true, decision must differ from the reviewer's decision.
Return ONLY the JSON, no surrounding text.
```

### System Prompt 日本語訳

```text
あなたは reviewer の decision が正しいか評価する meta-reviewer、すなわち judge である。reviewer output、planner history、postcheck results を受け取る。あなたの役割は reviewer decision を accept するか override するかを決めることである。

override criteria:
- retry->stop: reviewer が retry したいが evidence-backed next step がない、planner が同じ fault で既に 2 回失敗している、または remaining fault が allowed scope 外である場合に override する。
- stop->retry: reviewer が stop したいが、postcheck が previously masked だった new downstream fault を明確に示し、それが available scope で repairable である場合、または canonical additional observation が in-scope fault の exact editable line を露出できる場合に override する。reviewer stop が recommended_next_observations も列挙しており、それによって in-scope repair を localize できるなら、その stop は早すぎる。

planner escalation criteria:
- escalate_planner=true にするのは、decision=retry で retry に bounded かつ evidence-backed な repair scope があり、previous planner が empty plan を返した、unsafe / precheck-blocked action を繰り返した、または reviewer-provided scope を使えなかった場合だけである。
- partial env/config repair 後の retry が evidence-backed になるのは、additional observation または visible snippets が remaining exact editable lines を露出している場合だけである。
- restore_from_base を推奨してはいけない。hidden baseline answer を復元するため controlled experiment では block される。
- blocker が missing evidence の場合は escalate_planner=false のままにする。より強い planner ではなく additional observation を優先する。

出力は {"decision":"retry|stop","override":true|false,"reasoning":"...","escalate_planner":true|false,"escalation_reason":"..."} という形の JSON のみにする。

override が false の場合、decision は reviewer decision と一致しなければならない。
override が true の場合、decision は reviewer decision と異ならなければならない。
周辺テキストなしで JSON のみを返す。
```

### User Prompt Template 原文

```text
Evaluate the reviewer's decision and decide whether to accept or override it.
{json.dumps(context, ensure_ascii=False, indent=2)}
```

`context` には `turn`, `reviewer_decision`, `reviewer_feedback`, `reviewer_recommended_scope`, `postcheck_summary`, `planner_history`, `reviewer_history`, `candidate_scope`, `ambiguity_level`, `incident_blackboard` が入る。

### User Prompt Template 日本語訳

```text
reviewer decision を評価し、accept するか override するかを決める。
{json.dumps(context, ensure_ascii=False, indent=2)}
```

## Self-Critique Prompt

Self-critique は reviewer ではなく「同じ single-agent repair planner が自分の直前 attempt を見直す」設定として prompt される。

### System Prompt 原文

```text
You are the same single-agent repair planner reviewing your previous repair attempt. Do not introduce a separate reviewer persona. Return JSON only with the shape {"decision":"retry|stop","summary":"...","failure_analysis":"...","feedback_for_planner":"...","suspected_remaining_domains":[...],"recommended_scope_adjustment":{"editable_files":[...],"services":[...],"allowed_actions":[...]},"recommended_next_observations":[...]}. Use only current evidence, the prior plan, and postcheck results. If a newly exposed downstream fault is repairable within scope, return retry. If there is no evidence-backed next step or the prior action repeated without progress, return stop. When requesting more observations, prefer these canonical request strings exactly when applicable: 'extract narrower relevant snippet from app/main.py', 'extract narrower relevant snippet from app/app.env', 'extract narrower relevant snippet from nginx/nginx.conf', 'expand app log excerpt', 'expand nginx log excerpt'.
```

### System Prompt 日本語訳

```text
あなたは同じ single-agent repair planner であり、自分の previous repair attempt を見直している。別人格の reviewer を導入してはいけない。出力は {"decision":"retry|stop","summary":"...","failure_analysis":"...","feedback_for_planner":"...","suspected_remaining_domains":[...],"recommended_scope_adjustment":{"editable_files":[...],"services":[...],"allowed_actions":[...]},"recommended_next_observations":[...]} という形の JSON のみにする。current evidence、prior plan、postcheck results だけを使う。新しく露出した downstream fault が scope 内で repairable なら retry を返す。evidence-backed next step がない、または prior action が progress なしで繰り返された場合は stop を返す。追加観測を要求するときは、該当する場合、次の canonical request string を正確に使う: 'extract narrower relevant snippet from app/main.py', 'extract narrower relevant snippet from app/app.env', 'extract narrower relevant snippet from nginx/nginx.conf', 'expand app log excerpt', 'expand nginx log excerpt'。
```

### User Prompt Template 原文

```text
Self-critique the latest single-agent repair turn and decide whether to replan.
{json.dumps(context, ensure_ascii=False, indent=2)}
```

`context` には `turn`, `suspected_domains`, `candidate_scope`, `ambiguity_level`, `triage_summary`, `current_state_evidence`, `historical_evidence`, `previous_plans`, `previous_reviewer_history`, `latest_actions`, `validated_actions`, `precheck_summary`, `action_results`, `postcheck_summary`, `rollback_used`, `rollback_result`, `incident_blackboard`, `hypothesis_log` が入る。

### User Prompt Template 日本語訳

```text
最新の single-agent repair turn を self-critique し、replan するべきか判断する。
{json.dumps(context, ensure_ascii=False, indent=2)}
```

## Production PoC Incident Analyzer Prompt

Production PoC は Docker benchmark とは別系統で、personal Ubuntu server 向けの cautious incident triage assistant として LLM を呼ぶ。system/human に分けず、LangChain client に単一 prompt string を渡している。

### Prompt 原文

```text
You are a cautious incident triage assistant for a personal Ubuntu server.
Return JSON only.
Never suggest package upgrades, file edits, firewall changes, reboot, chmod, chown, rm, database changes, or arbitrary shell.
Runbook-style actions must reference metadata.runbook_id; the guard will execute only fixed commands from the local allowlist.
Use only these action kinds when strictly justified: {", ".join(sorted(SUPPORTED_ACTION_KINDS))}.
If no safe action fits, return an empty proposed_actions list and explain the escalation_reason.
Output schema:
{"summary":"...","likely_causes":[{"cause":"...","confidence":"low|medium|high","evidence":["..."]}],"proposed_actions":[{"kind":"restart_service","service":"nginx","reason":"...","expected_impact":"...","evidence":["..."],"metadata":{"runbook_id":"optional_allowlisted_id"}}],"escalation_reason":"..."}
Incident context:
{json.dumps(payload, ensure_ascii=False, indent=2)}
```

`SUPPORTED_ACTION_KINDS` の実値は次である。

```text
config_toggle_rollback, dependency_rollback, disk_usage_check, failed_units_check, file_stat, http_health_check, journal_keyword_search, listen_port_check, memory_pressure_check, restart_service, runbook, service_active_check, service_failover, service_logs, service_status, tcp_port_check
```

### Prompt 日本語訳

```text
あなたは personal Ubuntu server のための慎重な incident triage assistant である。
JSON のみを返す。
package upgrade、file edit、firewall change、reboot、chmod、chown、rm、database change、任意 shell を提案してはいけない。
runbook-style action は metadata.runbook_id を参照しなければならない。guard は local allowlist にある固定 command だけを実行する。
厳密に正当化される場合だけ、次の action kind を使う: {", ".join(sorted(SUPPORTED_ACTION_KINDS))}。
安全な action が該当しない場合、proposed_actions は empty list にし、escalation_reason を説明する。
出力 schema:
{"summary":"...","likely_causes":[{"cause":"...","confidence":"low|medium|high","evidence":["..."]}],"proposed_actions":[{"kind":"restart_service","service":"nginx","reason":"...","expected_impact":"...","evidence":["..."],"metadata":{"runbook_id":"optional_allowlisted_id"}}],"escalation_reason":"..."}
incident context:
{json.dumps(payload, ensure_ascii=False, indent=2)}
```

## Agent-Visible Context

Planner が見る `worker_visible_context` は `core/scenario_context.py` で作られる。主な内容は次の通り。

| key | 内容 | LLM への意味 |
|---|---|---|
| `suspected_domains` | triage が rank した fault domain と confidence/evidence | true label ではなく仮説 |
| `candidate_scope` | triage domain から merge された files/services/actions | planner が守るべき scope |
| `missing_evidence` | 足りない evidence の説明 | empty plan や追加観測判断の材料 |
| `recommended_next_observations` | canonical additional observation request | 追加観測 node が解釈できる request |
| `ambiguity_level` | `low` / `medium` / `high` | 推測せず止めるかどうかの材料 |
| `triage_summary` | triage の自然言語 summary | hypothesis の背景 |
| `observation.compose_ps` | service state/health の要約 | container 状態 |
| `observation.health_checks` | `/healthz`, `/api/items`, `/api/topology` | success/failure の現在状態 |
| `observation.file_snippets` | candidate files に絞った snippet | `replace_text.old_text` の根拠 |
| `observation.relevant_log_excerpts` | app/nginx log excerpt | fault marker の根拠 |
| `observation.http_error_evidence` | HTTP body excerpt | DB/query error など |
| `observation.suspicious_patterns` | logs/HTTP で hit した pattern | domain ranking の補助 |
| `observation.static_observations` | baseline port、nginx reference note、topology env など | layer の取り違え防止 |
| `observation.current_state_evidence` | 現在の health/status/snippet 由来 evidence | historical evidence より優先 |
| `observation.historical_evidence` | 古い nginx log noise など | stale evidence として扱う |
| `observation.additional_observation` | 追加観測の request/collected/count/turn | multi-turn の再計画材料 |
| `safety_constraints` | no shell, replace_text, restore 禁止など | planner の明示制約 |

`safety_constraints` として planner に直接渡される値は次である。

```json
{
  "single_turn_runner": true,
  "show_file_allowed": false,
  "edit_operations": ["replace_text"],
  "no_repository_wide_edits": true,
  "no_shell_commands": true,
  "replace_text_old_text_must_be_visible": true,
  "broad_single_token_code_replacements_forbidden": true,
  "restore_from_base_role": "forbidden_in_controlled_experiments",
  "prefer_minimal_patch_for_code_files": ["app/main.py"],
  "initial_code_restore_is_discouraged": true
}
```

## Candidate Scope: Agent に見える制限

LLM planner に直接見える files/services/actions は、hidden scenario definition ではなく `core/triage.py` の domain policy から作られる。複数 domain が近い confidence の場合は最大 3 domain まで merge される。

| domain | files | services | allowed_actions |
|---|---|---|---|
| `reverse_proxy_or_upstream_mismatch` | `nginx/nginx.conf`, `app/app.env` | `nginx`, `app` | `edit_file`, `run_config_test`, `restart_compose_service`, `rebuild_compose_service` |
| `app_startup_or_dependency_failure` | `app/requirements.txt`, `app/main.py`, `app/app.env` | `app` | `edit_file`, `rebuild_compose_service` |
| `app_config_or_env_mismatch` | `app/app.env`, `app/main.py`, `nginx/nginx.conf` | `app`, `nginx` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test` |
| `database_auth_or_connectivity_issue` | `app/app.env`, `app/main.py` | `app`, `db` | `edit_file`, `rebuild_compose_service` |
| `query_or_code_bug` | `app/main.py`, `app/app.env` | `app` | `edit_file`, `rebuild_compose_service` |
| `schema_drift` | `app/main.py`, `app/app.env` | `app` | `edit_file`, `rebuild_compose_service` |
| `healthcheck_only_failure` | `app/main.py` | `app` | `edit_file`, `rebuild_compose_service` |
| `ambiguous_service_disagreement` | `nginx/nginx.conf`, `app/main.py`, `app/app.env` | `nginx`, `app` | `edit_file`, `run_config_test`, `restart_compose_service`, `rebuild_compose_service` |
| `topology_or_service_discovery_fault` | `app/app.env` | `app`, `cache`, `queue`, `metrics` | `edit_file`, `rebuild_compose_service`, `run_health_check` |
| `failover_contract_mismatch` | `app/app.env` | `app`, `cache`, `queue`, `metrics` | `edit_file`, `rebuild_compose_service`, `run_health_check` |
| `degraded_mode_leak` | `app/app.env` | `app`, `cache`, `queue`, `metrics` | `edit_file`, `rebuild_compose_service`, `run_health_check` |
| `unknown` | `nginx/nginx.conf`, `app/main.py`, `app/requirements.txt`, `app/app.env` | `nginx`, `app`, `cache`, `queue`, `metrics` | `edit_file`, `run_config_test`, `restart_compose_service`, `rebuild_compose_service` |

## Verifier / Executor 側の強制制約

LLM が JSON を返した後、`parse_plan_text()`、`run_precheck()`、`execute_plan()` が次の制約を強制する。

| 制約 | 内容 |
|---|---|
| action type allowlist | `edit_file`, `restart_compose_service`, `rebuild_compose_service`, `run_config_test`, `run_health_check`, `show_file`。ただし planner parse では `show_file` が forbidden |
| editable file whitelist | `nginx/nginx.conf`, `app/main.py`, `app/requirements.txt`, `app/app.env` |
| service allowlist | `nginx`, `app`, `db`, `cache`, `queue`, `worker`, `metrics` |
| config test target | `compose`, `nginx` |
| max actions | 1 plan あたり最大 6 |
| max changed lines | 1 edit で 20 changed lines 以下 |
| path safety | absolute path と repo 外 path は禁止 |
| replace_text | `old_text` は対象 file に exactly once 出現する必要がある |
| visible evidence | `old_text` は現在の observed file snippet に含まれる必要がある |
| code file contextuality | `app/main.py` の `old_text` は 8 文字以上かつ context を持つ必要があり、単一 token 置換は禁止 |
| restore_from_base | `RESTORE_FROM_BASE_MODE` default が `forbid` であり、controlled experiment では block |
| auto action | app env/code/requirements edit 後は app rebuild を自動付与可能。nginx.conf edit 後は nginx config test を自動付与可能 |
| success check | planner は success check の run_health_check を返さないよう prompt され、postcheck が自動評価する |

## Benchmark Scenarios と Verifier/Evaluator 制約

次の table は `scenarios/definitions.yaml` の scenario 定義である。これは主に verifier / postcheck / evaluator の制約であり、LLM に hidden answer として渡されるものではない。

| ID | name | description | allowed_files | allowed_actions | success_checks | restore_policy |
|---|---|---|---|---|---|---|
| `a` | `A` | Nginx reverse proxy points to the wrong backend port and returns 502. | `nginx/nginx.conf` | `edit_file`, `run_config_test`, `restart_compose_service`, `run_health_check` | `nginx_running`, `healthz_200`, `api_items_200` |  |
| `b` | `B` | The app container cannot start because a required dependency was removed. | `app/requirements.txt` | `edit_file`, `rebuild_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `healthz_200` |  |
| `c` | `C` | The app-side DB password is incorrect and database queries fail. | `app/app.env` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `api_items_200` |  |
| `d` | `D` | The app code queries a non-existent table, so only /api/items fails. | `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` |  |
| `e` | `E` | The app listens on a different port than nginx expects, creating competing repair choices. | `app/main.py`, `app/app.env`, `nginx/nginx.conf` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `nginx_running`, `healthz_200`, `api_items_200` |  |
| `f` | `F` | The app code queries a non-existent column, so only /api/items fails. | `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` |  |
| `g` | `G` | Only the health endpoint is broken while the main API path continues to serve items. | `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` |  |
| `h` | `H` | Nginx points to an invalid upstream host name and returns 502. | `nginx/nginx.conf` | `edit_file`, `run_config_test`, `restart_compose_service`, `run_health_check` | `nginx_running`, `healthz_200`, `api_items_200` |  |
| `i` | `I` | A masked two-stage env failure combines app port drift with a wrong DB password. | `app/app.env`, `nginx/nginx.conf` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `nginx_running`, `healthz_200`, `api_items_200` |  |
| `i2` | `I2` | App port drift masks a downstream query bug until upstream reachability is restored. | `app/app.env`, `app/main.py`, `nginx/nginx.conf` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `nginx_running`, `healthz_200`, `api_items_200` | `disallow_initial_restore_for: app/main.py`; `allow_restore_only_after_failed_patch_for: app/main.py` |
| `m` | `M` | A three-layer cascade exposes nginx host mismatch, then DB auth failure, then a query bug. | `nginx/nginx.conf`, `app/app.env`, `app/main.py` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `nginx_running`, `healthz_200`, `api_items_200` | `disallow_initial_restore_for: app/main.py`; `allow_restore_only_after_failed_patch_for: app/main.py` |
| `k` | `K` | The API returns a generic internal error while the real root cause is only visible via extra observation. | `app/main.py`, `app/app.env` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` |  |
| `l` | `L` | Stale nginx upstream failures remain in the logs while the current fault is an app/query bug. | `app/main.py`, `nginx/nginx.conf` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` |  |
| `n` | `N` | A dependency failure masks a downstream query bug until the app can start again. | `app/requirements.txt`, `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` | `disallow_initial_restore_for: app/main.py`; `allow_restore_only_after_failed_patch_for: app/main.py` |
| `o` | `O` | Stale nginx evidence coexists with a DB-auth failure that masks a downstream query bug. | `nginx/nginx.conf`, `app/app.env`, `app/main.py` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` | `disallow_initial_restore_for: app/main.py`; `allow_restore_only_after_failed_patch_for: app/main.py` |
| `p` | `visible_green_hidden_red` | API returns 200 but silently degrades to an empty fallback response instead of serving real DB-backed items. | `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok` |  |
| `q` | `competing_repair_choice` | Multiple repair options appear plausible, but only restoring the app-side port contract to the healthy baseline is considered correct. | `app/app.env`, `nginx/nginx.conf` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok`, `port_contract_matches_baseline` |  |
| `r` | `non_commutative_masked_cascade` | A three-layer masked cascade where dependency failure hides DB auth drift, and DB auth drift hides a latent query bug; correct recovery requires staged re-observation and replanning. | `app/requirements.txt`, `app/app.env`, `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok` | `disallow_initial_restore_for: app/main.py`; `allow_restore_only_after_failed_patch_for: app/main.py` |
| `s` | `bilateral_port_contract_violation` | Both nginx upstream port and app listen port are wrong in different directions, requiring cross-file baseline restoration. | `nginx/nginx.conf`, `app/app.env` | `edit_file`, `rebuild_compose_service`, `restart_compose_service`, `run_config_test`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok`, `port_contract_matches_baseline` |  |
| `t` | `network_topology_fault` | DB_HOST points to 127.0.0.1 inside Docker, making the app unable to reach the database container. | `app/app.env` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `app_running`, `healthz_200`, `api_items_200` |  |
| `u` | `network_topology_masks_query_cascade` | DB_HOST connectivity failure masks a downstream query bug until the database becomes reachable again. | `app/app.env`, `app/main.py` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok` | `disallow_initial_restore_for: app/main.py`; `allow_restore_only_after_failed_patch_for: app/main.py` |
| `v` | `cache_name_resolution_fault` | The app-visible cache dependency target points to a non-existent service, so user-facing HTTP stays green while the DC topology contract is degraded. | `app/app.env` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok`, `dc_services_running`, `dc_topology_contract_ok`, `dc_no_degraded_mode` |  |
| `w` | `failover_target_mismatch` | A reachable failover target is wired into CACHE_HOST, but it points at the queue service instead of the expected cache service. | `app/app.env` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok`, `dc_services_running`, `dc_topology_contract_ok`, `dc_no_degraded_mode` |  |
| `x` | `bilateral_dependency_drift` | Cache and queue targets are swapped and degraded mode is left enabled, requiring semantic topology checks rather than plain HTTP 200 checks. | `app/app.env` | `edit_file`, `rebuild_compose_service`, `run_health_check` | `healthz_200`, `api_items_200`, `api_items_nonempty`, `api_items_schema_ok`, `dc_services_running`, `dc_topology_contract_ok`, `dc_no_degraded_mode` |  |

## Additional Observation

追加観測は LLM が直接 shell を走らせるのではなく、canonical request string を state に返し、`additional_observation_node()` が許可済み観測だけを実行する。認識される canonical request は次である。

- `expand app log excerpt`
- `expand nginx log excerpt`
- `extract narrower relevant snippet from app/main.py`
- `extract narrower relevant snippet from app/app.env`
- `extract narrower relevant snippet from nginx/nginx.conf`
- `run nginx config test as observation`

Reviewer / self-critique / triage はこのうち一部を推奨する。planner system prompt は `show_file` を禁止しているため、追加 file inspection はこの node を経由する。

## Hidden / Not Hidden の整理

| 情報 | LLM に渡るか | 補足 |
|---|---:|---|
| requested scenario ID | 基本的に渡らない | state にはあるが prompt context には直接入らない |
| scenario description | 渡らない | `scenarios/definitions.yaml` は verifier/evaluator 用 |
| scenario success_checks | planner には渡らない | postcheck/precheck が使う |
| allowed_files / allowed_actions from scenario | 直接は渡らない | verifier 側制約。planner は triage の `candidate_scope` を見る |
| triage suspected_domains | 渡る | hidden label ではなく observation 由来 hypothesis |
| candidate_scope | 渡る | files/services/actions の agent-visible scope |
| file snippets | 渡る | candidate files に絞られる |
| full file content | 渡らない | snippet と additional observation のみ |
| base files | 渡らない | `restore_from_base` は controlled experiment では forbidden |
| logs / health checks | 要約・excerpt が渡る | service_logs 全文は worker-visible context では trimmed |
| reviewer/judge history | multi-turn では渡る | planner history / reviewer history / blackboard snapshot |

## Production PoC Validation Scenarios

Production PoC の実機検証シナリオは `docs/production_poc/validation_scenarios.md` にある。これは benchmark の `scenarios/definitions.yaml` とは別で、実ホスト上の手順・期待観測を定義している。

| ID | シナリオ | agent/analyzer に関係する制限 |
|---|---|---|
| 1 | Web service を停止して検知 | 最初は `propose-only`。restart は allowlist 確認済みの場合のみ execute |
| 2-A | systemd 管理 Minecraft 停止 | allowlist 外なら execute でも自動再起動しない |
| 2-B | tmux / shell script 管理 Minecraft 停止 | systemd と誤判定せず、手動復旧が必要という通知にする |
| 3 | localhost health check を失敗先へ向ける | `propose-only` では危険操作を実行しない |
| 4 | dummy failed unit でエスカレーション確認 | 安全な自動操作がなければ Discord に escalation を出す |
| 5 | execute モードで restart と検証 | allowlist service 1 つに絞り、restart は 1 回だけ。検証失敗時に連鎖自動操作をしない |
| 6 | restart 以外の low-risk runbook | `allowed_runbooks` の固定 argv と一致する runbook のみ実行可能 |
| 7 | medium-risk action の backup / approval gate | fresh snapshot と approval file が揃った場合だけ実行可能 |
| 8 | rollback runbook | verification 失敗時、rollback runbook を 1 段だけ実行。失敗時は manual 対応へ |

## 研究上の含意

現在の実装では、LLM に「シナリオ固有の正解」を渡さないための境界はおおむね保たれている。特に planner prompt は `hidden scenario labels` を明示的に否定し、`replace_text.old_text` を visible snippet に限定している。これにより、成功率は単に正解を復元できるかではなく、観測、仮説更新、安全制約を通じて回復できるかを測る形になっている。

一方で、`candidate_scope` は triage の domain ranking に強く依存する。つまり、LLM planner が見ている制限は scenario definition そのものではなく、観測から推定された scope である。失敗分析では、scenario の `allowed_files` と planner の `candidate_scope` を混同しないことが重要である。`allowed_files` は「実験上その scenario で許される修復面」、`candidate_scope` は「その run で agent に見えている修復面」である。

Production PoC は benchmark とは逆に、実ホストへの影響を抑えるため prompt 自体が任意 shell、file edit、reboot、permission change、database change を強く禁止している。さらに ActionGuard が local allowlist、approval、backup、verification、rollback を強制するため、LLM output は提案であり、実行権限そのものではない。

# Hypothesis Transition Evaluation

Phase 4.5 は、成功率だけでなく「どの制御構造が仮説固執を減らしたか」を見るための評価準備フェーズである。

## 比較条件

最低限の比較条件は次の 4 つに固定する。

- `single_agent_one_shot`: `agent.py`
- `single_agent_iterative_self_critique`: `self_critique_agent.py`
- `multi_agent_single_planner`: `multi_agent.py`
- `improved_multi_agent`: 今後の planner diversity / prompt 改良版

`single_agent_iterative_self_critique` は planner と critic の provider/model を `SINGLE_AGENT_*` に揃え、外部 reviewer / judge role は使わない。

## 保存されるログ

各 result JSON には次を保存する。

- `baseline_condition`
- `hypothesis_log`
- `hypothesis_metrics`
- `self_critique_history`

`hypothesis_log` の各 turn には次を含める。

- `primary_hypothesis`
- `secondary_hypotheses`
- `confidence`
- `evidence_summary`
- `proposed_action`
- `reviewer_feedback_category`
- `judge_decision`
- `hypothesis_changed`
- `changed_after_critique`

## 集計

result JSON または observation summary から CSV を作る。

```bash
./.venv/bin/python aggregate_hypothesis_metrics.py results/20260419T114139Z_m.json
./.venv/bin/python aggregate_hypothesis_metrics.py observations/<run>/summary.csv --output observations/<run>/hypothesis_metrics.csv
```

最低限見る指標は次である。

- Top-1 仮説変更回数
- 仮説集合更新回数
- 批判後の仮説変化率
- 誤仮説固着長
- first-fix success と full recovery
- 再観測回数と仮説変化への寄与

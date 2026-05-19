# Experiment Token Dashboard

Run from the repository root:

```bash
python3 tools/token_dashboard/server.py --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`.

The API rescans `observations/*/summary.csv` on every request and follows each
row's `result_json` / `result_path` when available, so new experiment summaries
appear after a page refresh. The page also refreshes itself every 30 seconds.
Experiment names with token/cost data link to per-experiment report pages at
`/experiment.html?id=<experiment-directory>`.

Cost is an estimate using the price table in `server.py`. It excludes tax,
exchange rates, free credits, Batch/Flex/Priority multipliers, regional uplifts,
and tool-call fees.

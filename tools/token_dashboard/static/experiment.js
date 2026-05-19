const state = {
  data: null,
  experimentId: new URLSearchParams(window.location.search).get("id") || "",
  chartMetric: "cost",
};

const fmtInt = new Intl.NumberFormat("en-US");
const fmtUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});
const fmtShortUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const $ = (id) => document.getElementById(id);

function n(value) {
  return Number(value || 0);
}

function money(value) {
  if (value === null || value === undefined) return "-";
  return fmtUsd.format(n(value));
}

function seconds(value) {
  if (!value) return "-";
  const num = n(value);
  return num >= 60 ? `${(num / 60).toFixed(1)}m` : `${num.toFixed(1)}s`;
}

function compactDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusClass(value) {
  const lowered = String(value || "unknown").toLowerCase();
  if (lowered === "success") return "success";
  if (lowered === "failure") return "failure";
  if (lowered === "unknown") return "unknown";
  return "other";
}

function modelColor(index) {
  const colors = [
    "var(--chart-1)",
    "var(--chart-2)",
    "var(--chart-3)",
    "var(--chart-4)",
    "var(--chart-5)",
    "var(--chart-6)",
  ];
  return colors[index % colors.length];
}

function summarizeModels(runs) {
  const map = new Map();
  for (const run of runs) {
    for (const part of run.parts || []) {
      const model = part.model || "unknown";
      const provider = part.provider || "unknown";
      const key = `${provider}::${model}`;
      const usage = part.usage || {};
      if (!map.has(key)) {
        map.set(key, {
          provider,
          model,
          runs: 0,
          input_tokens: 0,
          output_tokens: 0,
          total_tokens: 0,
          cost_usd: 0,
          unpriced_tokens: 0,
        });
      }
      const item = map.get(key);
      item.runs += 1;
      item.input_tokens += n(usage.input_tokens);
      item.output_tokens += n(usage.output_tokens);
      item.total_tokens += n(usage.total_tokens);
      if (part.cost_usd === null || part.cost_usd === undefined) {
        item.unpriced_tokens += n(usage.total_tokens);
      } else {
        item.cost_usd += n(part.cost_usd);
      }
    }
  }
  return [...map.values()].sort((a, b) => b.cost_usd - a.cost_usd);
}

function renderModelDonut(models) {
  const metric = state.chartMetric;
  const valueKey = metric === "tokens" ? "total_tokens" : "cost_usd";
  const total = models.reduce((sum, item) => sum + n(item[valueKey]), 0);
  const svg = $("modelDonut");
  svg.innerHTML = "";
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  bg.setAttribute("class", "donut-bg");
  bg.setAttribute("cx", "110");
  bg.setAttribute("cy", "110");
  bg.setAttribute("r", "82");
  svg.append(bg);

  const circumference = 2 * Math.PI * 82;
  let offset = 0;
  models.forEach((item, index) => {
    const value = n(item[valueKey]);
    if (!value || !total) return;
    const slice = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    const length = (value / total) * circumference;
    slice.setAttribute("class", "donut-slice");
    slice.setAttribute("cx", "110");
    slice.setAttribute("cy", "110");
    slice.setAttribute("r", "82");
    slice.setAttribute("stroke", modelColor(index));
    slice.setAttribute("stroke-dasharray", `${length} ${circumference - length}`);
    slice.setAttribute("stroke-dashoffset", `${-offset}`);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${item.model}: ${metric === "tokens" ? fmtInt.format(value) : money(value)}`;
    slice.append(title);
    offset += length;
    svg.append(slice);
  });

  $("donutMetric").textContent = metric === "tokens" ? "Tokens" : "Cost";
  $("donutTotal").textContent = metric === "tokens" ? fmtInt.format(total) : money(total);

  const legend = $("modelLegend");
  legend.innerHTML = "";
  models.forEach((item, index) => {
    const value = n(item[valueKey]);
    const share = total ? (value / total) * 100 : 0;
    const row = document.createElement("div");
    row.className = "legend-row";
    row.innerHTML = `
      <span class="legend-dot" style="background:${modelColor(index)}"></span>
      <span class="legend-name" title="${item.model}">${item.model}</span>
      <span class="legend-share">${share.toFixed(1)}%</span>
      <span class="legend-value">${metric === "tokens" ? fmtInt.format(value) + " tok" : money(value)}</span>
    `;
    legend.append(row);
  });
}

function renderEfficiency(models) {
  const target = $("efficiencyList");
  target.innerHTML = "";
  const ranked = [...models].sort((a, b) => {
    const aRate = n(a.total_tokens) ? n(a.cost_usd) / n(a.total_tokens) : Number.POSITIVE_INFINITY;
    const bRate = n(b.total_tokens) ? n(b.cost_usd) / n(b.total_tokens) : Number.POSITIVE_INFINITY;
    return aRate - bRate;
  });
  for (const item of ranked) {
    const costPer1k = n(item.total_tokens) ? (n(item.cost_usd) / n(item.total_tokens)) * 1000 : 0;
    const tokensPerRun = n(item.runs) ? n(item.total_tokens) / n(item.runs) : 0;
    const costPerRun = n(item.runs) ? n(item.cost_usd) / n(item.runs) : 0;
    const row = document.createElement("div");
    row.className = "efficiency-row";
    row.innerHTML = `
      <div class="efficiency-name" title="${item.model}">${item.model}</div>
      <div class="efficiency-meta">
        <span>${fmtShortUsd.format(costPer1k)} / 1K tok</span>
        <span>${fmtInt.format(Math.round(tokensPerRun))} tok/model-run</span>
        <span>${fmtShortUsd.format(costPerRun)} / model-run</span>
      </div>
    `;
    target.append(row);
  }
}

function renderScenarioRows(runs) {
  const groups = new Map();
  for (const run of runs) {
    const key = run.scenario || "unknown";
    if (!groups.has(key)) {
      groups.set(key, {
        scenario: key,
        runs: 0,
        success: 0,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        cost_usd: 0,
        elapsed_seconds: 0,
      });
    }
    const group = groups.get(key);
    group.runs += 1;
    if (run.final_status === "success") group.success += 1;
    group.input_tokens += n(run.input_tokens);
    group.output_tokens += n(run.output_tokens);
    group.total_tokens += n(run.total_tokens);
    group.cost_usd += n(run.cost_usd);
    group.elapsed_seconds += n(run.elapsed_seconds);
  }

  const body = $("scenarioRows");
  body.innerHTML = "";
  for (const item of [...groups.values()].sort((a, b) => b.cost_usd - a.cost_usd)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="text">${item.scenario}</td>
      <td>${fmtInt.format(item.runs)}</td>
      <td>${item.runs ? Math.round((item.success / item.runs) * 100) : 0}%</td>
      <td>${fmtInt.format(item.total_tokens)}</td>
      <td>${money(item.cost_usd)}</td>
      <td>${money(item.runs ? item.cost_usd / item.runs : 0)}</td>
      <td>${seconds(item.runs ? item.elapsed_seconds / item.runs : 0)}</td>
    `;
    body.append(tr);
  }
}

function renderRunRows(runs) {
  const body = $("runRows");
  body.innerHTML = "";
  for (const run of runs) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="text">${compactDate(run.started_at)}</td>
      <td class="text">${run.scenario}</td>
      <td class="text">${run.mode}</td>
      <td><span class="badge ${statusClass(run.final_status)}">${run.final_status}</span></td>
      <td class="text">${modelCell(run)}</td>
      <td>${fmtInt.format(run.input_tokens)}</td>
      <td>${fmtInt.format(run.output_tokens)}</td>
      <td>${fmtInt.format(run.total_tokens)}</td>
      <td>${seconds(run.elapsed_seconds)}</td>
      <td>${money(run.cost_usd)}</td>
    `;
    body.append(tr);
  }
  $("runCount").textContent = `${fmtInt.format(runs.length)} token rows`;
}

function modelCell(run) {
  const parts = run.parts || [];
  if (parts.length <= 1) {
    const model = parts[0]?.model || (run.models || []).join(", ") || "-";
    return `<span class="model-detail-single" title="${model}">${model}</span>`;
  }
  const detailRows = parts
    .map((part) => {
      const usage = part.usage || {};
      return `
        <div class="model-part">
          <span class="model-part-role">${part.role || "-"}</span>
          <span class="model-part-name" title="${part.model || "-"}">${part.model || "-"}</span>
          <span class="model-part-usage">
            ${fmtInt.format(n(usage.input_tokens))} in /
            ${fmtInt.format(n(usage.output_tokens))} out /
            ${fmtInt.format(n(usage.total_tokens))} total /
            ${money(part.cost_usd)}
          </span>
        </div>
      `;
    })
    .join("");
  return `
    <details class="model-detail">
      <summary>${parts.length} models / ${fmtInt.format(run.total_tokens)} tok</summary>
      <div class="model-part-list">${detailRows}</div>
    </details>
  `;
}

function renderMissing(data) {
  const available = data.experiments.filter((item) => item.token_rows > 0);
  $("experimentTitle").textContent = "Experiment not found";
  $("status").innerHTML = `コスト集計がある実験を選んでください: ${available
    .map((item) => `<a href="/experiment.html?id=${encodeURIComponent(item.experiment)}">${item.experiment}</a>`)
    .join(" / ")}`;
}

function render() {
  const data = state.data;
  if (!data) return;
  const experiment = data.experiments.find((item) => item.experiment === state.experimentId && item.token_rows > 0);
  if (!experiment) {
    renderMissing(data);
    return;
  }

  const runs = data.runs
    .filter((run) => run.experiment === state.experimentId && run.total_tokens > 0)
    .sort((a, b) => String(a.started_at || "").localeCompare(String(b.started_at || "")));
  const models = summarizeModels(runs);
  const success = runs.filter((run) => run.final_status === "success").length;
  const failures = runs.filter((run) => run.final_status === "failure").length;
  const totalCost = runs.reduce((sum, run) => sum + n(run.cost_usd), 0);
  const totalTokens = runs.reduce((sum, run) => sum + n(run.total_tokens), 0);
  const inputTokens = runs.reduce((sum, run) => sum + n(run.input_tokens), 0);
  const outputTokens = runs.reduce((sum, run) => sum + n(run.output_tokens), 0);
  const elapsed = runs.reduce((sum, run) => sum + n(run.elapsed_seconds), 0);
  const costRuns = runs.filter((run) => run.cost_usd !== null && run.cost_usd !== undefined);
  const maxCost = costRuns.reduce((max, run) => (n(run.cost_usd) > n(max.cost_usd) ? run : max), costRuns[0] || {});
  const minCost = costRuns.reduce((min, run) => (n(run.cost_usd) < n(min.cost_usd) ? run : min), costRuns[0] || {});

  $("experimentTitle").textContent = experiment.experiment;
  $("status").textContent = `${experiment.csv_path} / ${runs.length} token rows`;
  $("totalCost").textContent = money(totalCost);
  $("pricedRows").textContent = `${fmtInt.format(experiment.priced_rows)} priced rows`;
  $("totalTokens").textContent = fmtInt.format(totalTokens);
  $("inputOutput").textContent = `Input ${fmtInt.format(inputTokens)} / Output ${fmtInt.format(outputTokens)}`;
  $("successRate").textContent = `${runs.length ? Math.round((success / runs.length) * 100) : 0}%`;
  $("successCount").textContent = `${success} / ${runs.length} success`;
  $("costPerSuccess").textContent = money(success ? totalCost / success : 0);
  $("avgCost").textContent = `平均 ${money(runs.length ? totalCost / runs.length : 0)} / run`;
  $("avgTokens").textContent = fmtInt.format(Math.round(runs.length ? totalTokens / runs.length : 0));
  $("avgElapsed").textContent = seconds(runs.length ? elapsed / runs.length : 0);
  $("maxCostRun").textContent = maxCost.scenario ? `${money(maxCost.cost_usd)} (${maxCost.scenario})` : "-";
  $("minCostRun").textContent = minCost.scenario ? `${money(minCost.cost_usd)} (${minCost.scenario})` : "-";

  const cheapest = [...models].sort((a, b) => n(a.cost_usd) / n(a.total_tokens) - n(b.cost_usd) / n(b.total_tokens))[0];
  const expensive = [...models].sort((a, b) => n(b.cost_usd) / n(b.total_tokens) - n(a.cost_usd) / n(a.total_tokens))[0];
  $("summaryList").innerHTML = `
    <p><strong>${experiment.experiment}</strong> はコスト集計対象 ${runs.length} 件、成功 ${success} 件、失敗 ${failures} 件です。</p>
    <p>総使用量は <strong>${fmtInt.format(totalTokens)} tokens</strong>、概算コストは <strong>${money(totalCost)}</strong> です。</p>
    <p>平均は <strong>${fmtInt.format(Math.round(totalTokens / runs.length))} tokens/run</strong>、<strong>${money(totalCost / runs.length)} / run</strong> です。</p>
    <p>この実験内で最も低単価なのは <strong>${cheapest?.model || "-"}</strong>、最も高単価なのは <strong>${expensive?.model || "-"}</strong> です。</p>
  `;

  renderModelDonut(models);
  renderEfficiency(models);
  renderScenarioRows(runs);
  renderRunRows(runs);
}

async function load() {
  $("status").textContent = "読み込み中...";
  const response = await fetch("/api/token-usage?dedupe=1", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.data = await response.json();
  render();
}

$("refreshButton").addEventListener("click", () => {
  load().catch((error) => {
    $("status").textContent = `読み込み失敗: ${error.message}`;
  });
});

document.querySelectorAll("[data-chart-metric]").forEach((button) => {
  button.addEventListener("click", () => {
    state.chartMetric = button.dataset.chartMetric;
    document
      .querySelectorAll("[data-chart-metric]")
      .forEach((item) => item.classList.toggle("active", item === button));
    render();
  });
});

load().catch((error) => {
  $("status").textContent = `読み込み失敗: ${error.message}`;
});

setInterval(() => {
  load().catch(() => {});
}, 30000);

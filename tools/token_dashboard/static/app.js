const state = {
  data: null,
  query: "",
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

function matches(item) {
  if (!state.query) return true;
  const haystack = [
    item.experiment,
    item.scenario,
    item.mode,
    item.final_status,
    ...(item.models || []),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(state.query);
}

function barRows(target, items, valueKey, labelFn, valueFn, limit = 10) {
  const max = Math.max(...items.map((item) => n(item[valueKey])), 1);
  target.innerHTML = "";
  if (!items.length) {
    target.innerHTML = '<p class="muted">No data</p>';
    return;
  }
  for (const item of items.slice(0, limit)) {
    const row = document.createElement("div");
    row.className = "bar-row";
    const label = document.createElement("div");
    label.className = "bar-label";
    label.title = labelFn(item);
    if (item.experiment && item.token_rows > 0) {
      const link = document.createElement("a");
      link.href = `/experiment.html?id=${encodeURIComponent(item.experiment)}`;
      link.textContent = labelFn(item);
      label.append(link);
    } else {
      label.textContent = labelFn(item);
    }
    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${Math.max((n(item[valueKey]) / max) * 100, 1)}%`;
    track.append(fill);
    const value = document.createElement("div");
    value.className = "bar-value";
    value.textContent = valueFn(item);
    row.append(label, track, value);
    target.append(row);
  }
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

function renderScenarioRows(items) {
  const body = $("scenarioRows");
  body.innerHTML = "";
  for (const item of items.slice(0, 24)) {
    const successRate = item.runs ? `${Math.round((item.success / item.runs) * 100)}%` : "-";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="text">${item.name}</td>
      <td>${fmtInt.format(item.runs)}</td>
      <td>${successRate}</td>
      <td>${fmtInt.format(item.total_tokens)}</td>
      <td>${money(item.cost_usd)}</td>
    `;
    body.append(tr);
  }
}

function renderRunRows(items) {
  const body = $("runRows");
  body.innerHTML = "";
  for (const item of items.slice(0, 250)) {
    const badgeClass = statusClass(item.final_status);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="text">${compactDate(item.started_at)}</td>
      <td class="text" title="${item.experiment}">${item.experiment}</td>
      <td class="text">${item.scenario}</td>
      <td class="text">${item.mode}</td>
      <td><span class="badge ${badgeClass}">${item.final_status}</span></td>
      <td class="text">${modelCell(item)}</td>
      <td>${fmtInt.format(item.input_tokens)}</td>
      <td>${fmtInt.format(item.output_tokens)}</td>
      <td>${money(item.cost_usd)}</td>
    `;
    body.append(tr);
  }
  $("runCount").textContent = `${fmtInt.format(items.length)} rows`;
}

function modelCell(item) {
  const parts = item.parts || [];
  if (parts.length <= 1) {
    const model = parts[0]?.model || (item.models || []).join(", ") || "-";
    return `<span class="model-detail-single" title="${model}">${model}</span>`;
  }
  const total = fmtInt.format(item.total_tokens);
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
      <summary>${parts.length} models / ${total} tok</summary>
      <div class="model-part-list">${detailRows}</div>
    </details>
  `;
}

function render() {
  const data = state.data;
  if (!data) return;
  const filteredRuns = data.runs.filter(matches);
  const experimentSet = new Set(filteredRuns.map((row) => row.experiment));
  const scenarioSet = new Set(filteredRuns.map((row) => row.scenario));
  const modeSet = new Set(filteredRuns.map((row) => row.mode));
  const filteredExperiments = data.experiments.filter((item) => experimentSet.has(item.experiment));
  const filteredScenarios = data.scenarios.filter((item) => scenarioSet.has(item.name));
  const filteredModes = data.modes.filter((item) => modeSet.has(item.name));

  $("totalCost").textContent = money(data.totals.cost_usd);
  $("totalTokens").textContent = fmtInt.format(data.totals.total_tokens);
  $("inputTokens").textContent = fmtInt.format(data.totals.input_tokens);
  $("outputTokens").textContent = fmtInt.format(data.totals.output_tokens);
  $("reasoningTokens").textContent = `Reasoning ${fmtInt.format(data.totals.reasoning_tokens)}`;
  $("pricedRows").textContent = `${fmtInt.format(data.priced_rows)} priced rows`;
  $("tokenRows").textContent = `${fmtInt.format(data.token_rows)} token rows`;
  $("costPerSuccess").textContent = money(data.totals.cost_per_success_usd);
  $("unpricedTokens").textContent = `Unpriced ${fmtInt.format(data.totals.unpriced_tokens)} tokens`;
  $("experimentCount").textContent = `${fmtInt.format(filteredExperiments.length)} experiments`;

  renderModelDonut(data.models);
  renderEfficiency(data.models);

  barRows(
    $("experimentBars"),
    filteredExperiments,
    "cost_usd",
    (item) => item.experiment,
    (item) => `${fmtShortUsd.format(item.cost_usd)} / ${fmtInt.format(item.total_tokens)} tok`,
    14,
  );
  barRows(
    $("modelBars"),
    data.models,
    "cost_usd",
    (item) => item.model,
    (item) => `${fmtShortUsd.format(item.cost_usd)} / ${fmtInt.format(item.total_tokens)} tok`,
    10,
  );
  barRows(
    $("modeBars"),
    filteredModes,
    "cost_usd",
    (item) => item.name,
    (item) => `${fmtShortUsd.format(item.cost_usd)} / ${fmtInt.format(item.runs)} runs`,
    10,
  );
  renderScenarioRows(filteredScenarios);
  renderRunRows(filteredRuns);

  $("status").textContent =
    `${compactDate(data.generated_at)} read: ${data.csv_files} CSV, ${data.rows} rows` +
    (data.duplicate_rows_skipped ? `, ${data.duplicate_rows_skipped} duplicates skipped` : "");
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

$("searchInput").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  render();
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

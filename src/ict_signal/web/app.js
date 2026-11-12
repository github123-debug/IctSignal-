const appState = {
  overview: null,
  states: [],
  signals: [],
  market: {},
  config: {},
  logs: [],
  contractFilter: "ALL",
  directionFilter: "ALL",
  logFilter: "ALL",
  refreshing: false,
};

const stateLabels = {
  IDLE: "等待条件",
  LIQUIDITY_TOUCHED: "流动性触及",
  BOS_CONFIRMED: "BOS 已确认",
  SIGNAL_FIRED: "信号触发",
  COOLDOWN: "冷却中",
};

const configLabels = {
  market_data_source: "行情数据源",
  universe: "扫描范围",
  top_n: "自动选币数量",
  min_quote_volume_usdt: "最低 24H 成交额",
  poll_seconds: "轮询间隔",
  max_concurrency: "最大并发数",
  fvg_definition: "FVG 方向定义",
  fvg_max_age_hours: "FVG 有效期",
  mitigation_use_close: "回补使用收盘价",
  liquidity_tolerance_pct: "流动性触及容差",
  bos_swing_window: "摆动点窗口",
  bos_atr_period: "ATR 周期",
  bos_min_atr_mult: "最小摆动距离",
  bos_timeout_bars_15m: "等待 BOS 超时",
  entry_timeout_bars_15m: "等待回踩超时",
  cooldown_bars_15m: "全局冷却",
  stale_signal_minutes: "旧信号抑制",
  telegram_enabled: "Telegram 开关",
  telegram_token_configured: "Bot Token",
  telegram_chat_configured: "目标 Chat",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initIcons(root = document) {
  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 }, root });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch (_) { /* response is not JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

function formatPrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  const digits = number >= 1000 ? 2 : number >= 1 ? 4 : 8;
  return number.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function formatCompact(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 100_000_000) return `${(number / 100_000_000).toFixed(2)} 亿`;
  if (Math.abs(number) >= 10_000) return `${(number / 10_000).toFixed(1)} 万`;
  return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function formatTime(value, withDate = false) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: withDate ? "2-digit" : undefined,
    day: withDate ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    second: withDate ? undefined : "2-digit",
    hour12: false,
  }).format(date);
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (days) return `${days}天 ${hours}小时`;
  if (hours) return `${hours}小时 ${minutes}分钟`;
  return `${minutes}分钟`;
}

function effectiveState(item) {
  if (item.state === "IDLE" && item.cooldown_bars > 0) return "COOLDOWN";
  return item.state;
}

function stateBadge(item) {
  const state = typeof item === "string" ? item : effectiveState(item);
  return `<span class="status-badge status-${escapeHTML(state)}">${escapeHTML(stateLabels[state] || state)}</span>`;
}

function symbolCell(symbol) {
  const clean = String(symbol || "").replace(/USDT$/, "");
  return `<span class="symbol-cell"><span class="symbol-mark">${escapeHTML(clean.slice(0, 2))}</span>${escapeHTML(symbol)}</span>`;
}

function changeCell(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return `<span class="muted">--</span>`;
  const className = number > 0 ? "positive" : number < 0 ? "negative" : "muted";
  const sign = number > 0 ? "+" : "";
  return `<span class="${className}">${sign}${number.toFixed(2)}%</span>`;
}

function deliveryBadge(status) {
  const labels = { sent: "已发送", failed: "失败", pending: "等待", disabled: "未启用", stale: "已过期" };
  const key = status || "pending";
  return `<span class="delivery-badge delivery-${escapeHTML(key)}">${escapeHTML(labels[key] || key)}</span>`;
}

function showEmpty(tableBody, emptyElement, isEmpty) {
  tableBody.closest("table").classList.toggle("is-hidden", isEmpty);
  emptyElement.classList.toggle("is-hidden", !isEmpty);
}

function renderOverview() {
  const overview = appState.overview;
  if (!overview) return;
  const active = (overview.state_counts.LIQUIDITY_TOUCHED || 0) + (overview.state_counts.BOS_CONFIRMED || 0);
  $("#metricContracts").textContent = overview.contract_count;
  $("#metricActive").textContent = active;
  $("#metricToday").textContent = overview.signals_today;
  $("#metricTotal").textContent = `累计 ${overview.signal_count}`;
  $("#metricTelegram").textContent = overview.telegram_configured ? "已连接" : "未配置";
  $("#metricTelegram").className = `metric-word ${overview.telegram_configured ? "positive" : "negative"}`;
  $("#metricUniverse").textContent = `${String(overview.source).toUpperCase()} / 成交额筛选`;
  $("#sidebarSource").textContent = String(overview.source).toUpperCase();
  $("#syncTime").textContent = formatTime(new Date().toISOString());

  const scanner = overview.scanner;
  const badge = $("#processBadge");
  badge.className = `process-status ${scanner.running ? "is-online" : "is-offline"}`;
  badge.innerHTML = `<span class="status-dot"></span><span>${scanner.running ? "扫描运行中" : "扫描已停止"}</span>`;
  const strip = $("#systemStrip");
  strip.classList.toggle("is-offline", !scanner.running);
  $("#systemTitle").textContent = scanner.running ? "实时扫描器运行正常" : "实时扫描器已停止";
  $("#systemMeta").textContent = scanner.running
    ? `PID ${scanner.pid} · 已运行 ${formatDuration(scanner.uptime_seconds)} · 最近数据 ${formatTime(overview.last_update)}`
    : "启动扫描器后将继续处理 Gate 行情与 Telegram 信号";
  $("#startScanner").disabled = scanner.running;
  $("#stopScanner").disabled = !scanner.running;
  $("#restartScanner").disabled = !scanner.running;

  const counts = overview.state_counts;
  const total = Math.max(overview.contract_count, 1);
  const pipeline = [
    ["Idle", counts.IDLE || 0],
    ["Touched", counts.LIQUIDITY_TOUCHED || 0],
    ["Bos", counts.BOS_CONFIRMED || 0],
    ["Cooldown", counts.COOLDOWN || 0],
  ];
  $("#pipelineTotal").textContent = `${overview.contract_count} 个合约`;
  pipeline.forEach(([name, count]) => {
    $(`#count${name}`).textContent = count;
    $(`#bar${name}`).style.width = `${Math.max(count ? 2 : 0, (count / total) * 100)}%`;
  });
  renderActivity();
  renderOverviewStates();
  renderOverviewSignals();
  initIcons();
}

function renderActivity() {
  const days = [];
  const counts = new Map();
  const now = new Date();
  for (let offset = 13; offset >= 0; offset -= 1) {
    const date = new Date(now.getTime() - offset * 86400000);
    const key = date.toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
    const label = date.toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric" });
    days.push({ key, label });
    counts.set(key, 0);
  }
  appState.signals.forEach((signal) => {
    if (!signal.signal_at) return;
    const key = new Date(signal.signal_at).toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
    if (counts.has(key)) counts.set(key, counts.get(key) + 1);
  });
  const max = Math.max(1, ...counts.values());
  $("#activityChart").innerHTML = days.map(({ key, label }) => {
    const count = counts.get(key);
    const height = count ? Math.max(10, (count / max) * 130) : 2;
    return `<div class="activity-column ${count ? "" : "is-zero"}" title="${escapeHTML(label)}：${count} 个信号"><strong>${count || ""}</strong><span class="activity-bar" style="height:${height}px"></span><span>${escapeHTML(label)}</span></div>`;
  }).join("");
}

function stateRow(item, detailed = false) {
  const market = appState.market[item.symbol] || {};
  const fvg = item.fvg ? `${item.fvg.direction} ${formatPrice(item.fvg.lower)}–${formatPrice(item.fvg.upper)}` : "--";
  const range = item.day_low != null && item.day_high != null
    ? `${formatPrice(item.day_low)} – ${formatPrice(item.day_high)}` : "--";
  if (detailed) {
    return `<tr data-clickable data-symbol="${escapeHTML(item.symbol)}">
      <td>${symbolCell(item.symbol)}</td><td>${formatPrice(market.price)}</td><td>${changeCell(market.change_24h)}</td>
      <td>${formatCompact(market.volume_24h)}</td><td>${stateBadge(item)}</td>
      <td>${escapeHTML(item.liquidity_level || "--")}</td><td>${escapeHTML(range)}</td><td>${formatTime(item.updated_at)}</td>
    </tr>`;
  }
  return `<tr data-clickable data-symbol="${escapeHTML(item.symbol)}">
    <td>${symbolCell(item.symbol)}</td><td>${formatPrice(market.price)}</td><td>${changeCell(market.change_24h)}</td>
    <td>${stateBadge(item)}</td><td>${escapeHTML(item.liquidity_level || "--")}</td><td>${escapeHTML(fvg)}</td><td>${formatTime(item.updated_at)}</td>
  </tr>`;
}

function renderOverviewStates() {
  const priority = { BOS_CONFIRMED: 0, LIQUIDITY_TOUCHED: 1, COOLDOWN: 2, IDLE: 3 };
  const states = [...appState.states].sort((a, b) => {
    const stateDiff = (priority[effectiveState(a)] ?? 9) - (priority[effectiveState(b)] ?? 9);
    if (stateDiff) return stateDiff;
    return (appState.market[b.symbol]?.volume_24h || 0) - (appState.market[a.symbol]?.volume_24h || 0);
  }).slice(0, 8);
  const body = $("#overviewStatesBody");
  body.innerHTML = states.map((item) => stateRow(item)).join("");
  showEmpty(body, $("#overviewStatesEmpty"), states.length === 0);
  bindStateRows(body);
}

function signalRow(signal, detailed = false) {
  const direction = signal.direction || "--";
  const row = `<tr data-clickable data-fingerprint="${escapeHTML(signal.fingerprint)}">
    <td>${formatTime(signal.signal_at, true)}</td><td>${symbolCell(signal.symbol)}</td>
    <td><span class="direction-badge direction-${escapeHTML(direction)}">${escapeHTML(direction)}</span></td>
    <td>${escapeHTML(signal.liquidity_level)}</td>${detailed ? `<td>${escapeHTML(signal.fvg_id)}</td>` : ""}
    <td>${formatPrice(signal.signal_price)}</td><td>${deliveryBadge(signal.delivery_status)}</td>
  </tr>`;
  return row;
}

function renderOverviewSignals() {
  const signals = appState.signals.slice(0, 6);
  const body = $("#overviewSignalsBody");
  body.innerHTML = signals.map((item) => signalRow(item)).join("");
  showEmpty(body, $("#overviewSignalsEmpty"), signals.length === 0);
  bindSignalRows(body);
}

function renderContracts() {
  const query = $("#contractSearch").value.trim().toUpperCase();
  const filtered = appState.states.filter((item) => {
    const state = effectiveState(item);
    const stateMatch = appState.contractFilter === "ALL"
      || (appState.contractFilter === "ACTIVE" && ["LIQUIDITY_TOUCHED", "BOS_CONFIRMED"].includes(state))
      || appState.contractFilter === state;
    return stateMatch && (!query || item.symbol.includes(query));
  }).sort((a, b) => (appState.market[b.symbol]?.volume_24h || 0) - (appState.market[a.symbol]?.volume_24h || 0));
  const body = $("#contractsBody");
  body.innerHTML = filtered.map((item) => stateRow(item, true)).join("");
  $("#contractCount").textContent = `${filtered.length} 个合约`;
  showEmpty(body, $("#contractsEmpty"), filtered.length === 0);
  bindStateRows(body);
}

function renderSignals() {
  const query = $("#signalSearch").value.trim().toUpperCase();
  const filtered = appState.signals.filter((item) => {
    const directionMatch = appState.directionFilter === "ALL" || item.direction === appState.directionFilter;
    const textMatch = !query || `${item.symbol} ${item.liquidity_level} ${item.fvg_id}`.toUpperCase().includes(query);
    return directionMatch && textMatch;
  });
  const body = $("#signalsBody");
  body.innerHTML = filtered.map((item) => signalRow(item, true)).join("");
  showEmpty(body, $("#signalsEmpty"), filtered.length === 0);
  $("#signalTotal").textContent = appState.signals.length;
  $("#signalLong").textContent = appState.signals.filter((item) => item.direction === "LONG").length;
  $("#signalShort").textContent = appState.signals.filter((item) => item.direction === "SHORT").length;
  $("#signalSent").textContent = appState.signals.filter((item) => item.delivery_status === "sent").length;
  bindSignalRows(body);
}

function renderLogs() {
  const consoleElement = $("#logConsole");
  const parsed = appState.logs.map((line) => {
    const match = line.trimEnd().match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)\s+(INFO|WARNING|ERROR|DEBUG)\s+([^:]+):\s?(.*)$/);
    if (!match) return { level: "INFO", time: "", message: line.trimEnd() };
    return { level: match[2], time: match[1], message: `${match[3]} · ${match[4]}` };
  }).filter((item) => appState.logFilter === "ALL" || item.level === appState.logFilter);
  if (!parsed.length) {
    consoleElement.innerHTML = `<div class="log-empty">暂无匹配日志</div>`;
    return;
  }
  consoleElement.innerHTML = parsed.map((item) => `<div class="log-line log-${escapeHTML(item.level)}">
    <span class="log-line-time">${escapeHTML(item.time)}</span><span class="log-line-level">${escapeHTML(item.level)}</span><span class="log-line-message">${escapeHTML(item.message)}</span>
  </div>`).join("");
  if ($("#logAutoScroll").checked) consoleElement.scrollTop = consoleElement.scrollHeight;
}

function configValue(key, value) {
  if (["telegram_token_configured", "telegram_chat_configured"].includes(key)) {
    return { text: value ? "已配置" : "未配置", className: value ? "is-ok" : "is-warn" };
  }
  if (key === "telegram_enabled" || key === "mitigation_use_close") {
    return { text: value ? "开启" : "关闭", className: value ? "is-ok" : "is-warn" };
  }
  if (key === "universe") return { text: Array.isArray(value) ? value.join(", ") : "自动选择", className: "" };
  if (key === "min_quote_volume_usdt") return { text: `${formatCompact(value)} USDT`, className: "" };
  if (["poll_seconds"].includes(key)) return { text: `${value} 秒`, className: "" };
  if (["fvg_max_age_hours"].includes(key)) return { text: `${value} 小时`, className: "" };
  if (["bos_timeout_bars_15m", "entry_timeout_bars_15m", "cooldown_bars_15m"].includes(key)) return { text: `${value} 根 15M`, className: "" };
  if (key === "liquidity_tolerance_pct") return { text: `${(Number(value) * 100).toFixed(3)}%`, className: "" };
  return { text: String(value ?? "--"), className: "" };
}

function renderConfig() {
  $("#configGrid").innerHTML = Object.entries(appState.config).map(([key, value]) => {
    const display = configValue(key, value);
    return `<div class="config-item"><span class="config-key">${escapeHTML(configLabels[key] || key)}</span><strong class="config-value ${display.className}">${escapeHTML(display.text)}</strong></div>`;
  }).join("");
}

function bindStateRows(root) {
  $$('tr[data-symbol]', root).forEach((row) => row.addEventListener("click", () => openContract(row.dataset.symbol)));
}

function bindSignalRows(root) {
  $$('tr[data-fingerprint]', root).forEach((row) => row.addEventListener("click", () => openSignal(row.dataset.fingerprint)));
}

function openContract(symbol) {
  const item = appState.states.find((entry) => entry.symbol === symbol);
  if (!item) return;
  const market = appState.market[symbol] || {};
  $("#dialogSymbol").textContent = symbol;
  const fvg = item.fvg;
  $("#contractDialogBody").innerHTML = `
    <div class="detail-price"><strong>${formatPrice(market.price)}</strong>${changeCell(market.change_24h)}</div>
    <div class="detail-grid">
      <div class="detail-item"><span>状态</span><strong>${stateLabels[effectiveState(item)] || effectiveState(item)}</strong></div>
      <div class="detail-item"><span>关键流动性</span><strong>${escapeHTML(item.liquidity_level || "--")}</strong></div>
      <div class="detail-item"><span>日内高点</span><strong>${formatPrice(item.day_high)}</strong></div>
      <div class="detail-item"><span>日内低点</span><strong>${formatPrice(item.day_low)}</strong></div>
      <div class="detail-item"><span>FVG 方向</span><strong>${escapeHTML(fvg?.direction || "--")}</strong></div>
      <div class="detail-item"><span>FVG 区间</span><strong>${fvg ? `${formatPrice(fvg.lower)} – ${formatPrice(fvg.upper)}` : "--"}</strong></div>
      <div class="detail-item"><span>流动性等待</span><strong>${item.liquidity_wait_bars} / ${appState.config.bos_timeout_bars_15m || "--"} 根</strong></div>
      <div class="detail-item"><span>回踩等待</span><strong>${item.entry_wait_bars} / ${appState.config.entry_timeout_bars_15m || "--"} 根</strong></div>
      <div class="detail-item"><span>今日已触及</span><strong>${escapeHTML(item.touched_levels.join(", ") || "--")}</strong></div>
      <div class="detail-item"><span>已失效水平</span><strong>${escapeHTML(item.invalidated_levels.join(", ") || "--")}</strong></div>
      <div class="detail-item"><span>24H 高点</span><strong>${formatPrice(market.high_24h)}</strong></div>
      <div class="detail-item"><span>24H 低点</span><strong>${formatPrice(market.low_24h)}</strong></div>
    </div>`;
  $("#contractDialog").showModal();
}

function openSignal(fingerprint) {
  const signal = appState.signals.find((item) => item.fingerprint === fingerprint);
  if (!signal) return;
  $("#signalDialogTitle").textContent = `${signal.symbol} · ${signal.direction}`;
  $("#signalMessage").textContent = signal.message || "";
  $("#signalDialog").showModal();
}

function toast(message, isError = false) {
  const element = document.createElement("div");
  element.className = `toast ${isError ? "is-error" : ""}`;
  element.innerHTML = `<i data-lucide="${isError ? "circle-alert" : "circle-check"}"></i><span>${escapeHTML(message)}</span>`;
  $("#toastRegion").appendChild(element);
  initIcons(element);
  setTimeout(() => element.remove(), 4200);
}

async function loadLogs() {
  try {
    const result = await api("/api/logs?lines=300");
    appState.logs = result.lines || [];
    renderLogs();
  } catch (error) {
    toast(error.message, true);
  }
}

async function refreshAll(showFeedback = false) {
  if (appState.refreshing) return;
  appState.refreshing = true;
  $("#refreshButton").classList.add("is-spinning");
  try {
    const [overview, states, signals, market, config, logs] = await Promise.all([
      api("/api/overview"), api("/api/states"), api("/api/signals?limit=500"),
      api("/api/market"), api("/api/config"), api("/api/logs?lines=300"),
    ]);
    Object.assign(appState, { overview, states, signals, market, config, logs: logs.lines || [] });
    renderOverview();
    renderContracts();
    renderSignals();
    renderLogs();
    renderConfig();
    if (showFeedback) toast("数据已刷新");
  } catch (error) {
    toast(error.message, true);
    $("#processBadge").className = "process-status is-offline";
    $("#processBadge").innerHTML = '<span class="status-dot"></span><span>连接失败</span>';
  } finally {
    appState.refreshing = false;
    $("#refreshButton").classList.remove("is-spinning");
  }
}

function switchView(name, updateHash = true) {
  const view = $(`#view-${name}`);
  if (!view) return;
  $$(".view").forEach((item) => item.classList.toggle("is-active", item === view));
  $$(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === name));
  $("#pageTitle").textContent = view.dataset.title;
  $("#breadcrumbLabel").textContent = view.dataset.label;
  if (updateHash) history.replaceState(null, "", `#${name}`);
  if (name === "logs") loadLogs();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function scannerAction(action) {
  if (action === "stop" && !window.confirm("确认停止实时扫描器？")) return;
  if (action === "restart" && !window.confirm("确认重启实时扫描器？")) return;
  const buttons = $$(".command-button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    await api(`/api/scanner/${action}`, { method: "POST" });
    toast({ start: "扫描器已启动", stop: "扫描器已停止", restart: "扫描器已重启" }[action]);
    await new Promise((resolve) => setTimeout(resolve, 800));
    await refreshAll();
  } catch (error) {
    toast(error.message, true);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function testTelegram() {
  const button = $("#testTelegram");
  const label = $("span", button);
  const originalLabel = label.textContent;
  button.disabled = true;
  label.textContent = "发送中";
  try {
    const result = await api("/api/telegram/test", { method: "POST" });
    toast(result.message || "Telegram 测试消息已发送");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    label.textContent = originalLabel;
  }
}

function bindSegmented(containerSelector, stateKey, render) {
  $$("button", $(containerSelector)).forEach((button) => button.addEventListener("click", () => {
    $$("button", $(containerSelector)).forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    appState[stateKey] = button.dataset.filter;
    render();
  }));
}

function initEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $$('[data-view-jump]').forEach((button) => button.addEventListener("click", () => switchView(button.dataset.viewJump)));
  $("#refreshButton").addEventListener("click", () => refreshAll(true));
  $("#refreshLogs").addEventListener("click", loadLogs);
  $("#contractSearch").addEventListener("input", renderContracts);
  $("#signalSearch").addEventListener("input", renderSignals);
  $("#startScanner").addEventListener("click", () => scannerAction("start"));
  $("#stopScanner").addEventListener("click", () => scannerAction("stop"));
  $("#restartScanner").addEventListener("click", () => scannerAction("restart"));
  $("#testTelegram").addEventListener("click", testTelegram);
  bindSegmented("#stateFilters", "contractFilter", renderContracts);
  bindSegmented("#directionFilters", "directionFilter", renderSignals);
  bindSegmented("#logFilters", "logFilter", renderLogs);
  $$('[data-dialog-close]').forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
  $$("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  }));
  window.addEventListener("hashchange", () => switchView(location.hash.slice(1) || "overview", false));
}

document.addEventListener("DOMContentLoaded", async () => {
  initIcons();
  initEvents();
  switchView(location.hash.slice(1) || "overview", false);
  await refreshAll();
  setInterval(() => {
    if (!document.hidden) refreshAll();
  }, 15000);
});

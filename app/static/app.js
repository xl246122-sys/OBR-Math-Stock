"use strict";

let token = "", timer = null, pending = false;
let universeData = null, signalsData = [], statusData = null, positionsData = null;
let displayedFeeChange = null, acknowledgedFeeChange = null;
let pendingControlAction = null;

try {
  acknowledgedFeeChange = localStorage.getItem("obr-fee-change-ack");
  const savedTheme = localStorage.getItem("obr-theme");
  if (savedTheme === "light" || savedTheme === "dark") {
    document.documentElement.setAttribute("data-theme", savedTheme);
  }
} catch (e) {}

const $ = id => document.getElementById(id);

const blockerTitles = {
  PAPER_VERIFICATION_REQUIRED: "模拟盘核验文件待完备 (需核实26h内有效费率指纹与量能标的清单)",
  VOLUME_NOT_VERIFIED: "焦点标的实时量能单位与单调性尚未核验",
  HISTORICAL_VOLUME_COLD_START: "历史同进度成交量积累中 (需满10个历史交易日样本)",
  FEES_NOT_VERIFIED: "账户适用手续费率尚待核实 (公开费率表不等于账户实际费率)",
  LIVE_FEES_NOT_VERIFIED: "实盘账户适用手续费尚未核实",
  LIVE_ACCOUNT_NOT_RECONCILED: "实盘独立账本尚未完成启动对账",
  LIVE_INSTRUMENT_METADATA_NOT_VERIFIED: "美国上市股票/ETF 权威元数据尚未全量核验",
  PAPER_MODE_OFF: "模拟盘通道开关当前已关闭",
  DAILY_LOSS_LIMIT: "已触发当日最大亏损熔断保护",
  EXCHANGE_RULES_UNVERIFIED_OR_STALE: "平台交易规则待刷新或已超20分钟有效期",
  MARKET_DATA_GAP: "行情连续性存在缺口锁定 (等待连续无缺口K线恢复)",
  MARKET_DISCONNECTED: "行情 WebSocket 通道重连中"
};

function text(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function number(value, suffix = "") {
  return typeof value === "number" ? value.toFixed(2) + suffix : "未测得";
}

function showError(message) {
  const el = $("error");
  if (!el) return;
  el.hidden = !message;
  el.textContent = message || "";
}

function showNotice(message) {
  const el = $("notice");
  if (!el) return;
  el.hidden = !message;
  el.textContent = message || "";
}

async function api(path, method = "GET", body = null, controlToken = null) {
  const headers = { Authorization: "Bearer " + token };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
    if (controlToken) headers["X-OBR-Control-Token"] = controlToken;
  }
  const response = await fetch("/api/v1/" + path, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : null,
    cache: "no-store"
  });
  if (!response.ok) {
    const msg = response.status === 401
      ? "监控访问令牌无效，请重新连接。"
      : response.status === 403
      ? "独立操作令牌无效，写操作已拦截。"
      : response.status === 409
      ? "操作未满足前置风控条件（请确认通道关闭、空仓状态或样本外验证结果）。"
      : "接口返回 HTTP " + response.status;
    throw new Error(msg);
  }
  return response.headers.get("content-type")?.includes("application/json")
    ? response.json()
    : response.text();
}

function renderTable(id, headers, rows) {
  const root = $(id);
  if (!root) return;
  root.replaceChildren();
  if (!rows || !rows.length) {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = "暂无记录。系统严格遵循真实审计原则，不会用示例数据填充此处。";
    root.append(p);
    return;
  }
  const tbl = document.createElement("table");
  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  headers.forEach(h => {
    const th = document.createElement("th");
    th.textContent = h;
    trHead.append(th);
  });
  thead.append(trHead);
  tbl.append(thead);

  const tbody = document.createElement("tbody");
  rows.forEach(row => {
    const tr = document.createElement("tr");
    row.forEach(val => {
      const td = document.createElement("td");
      td.textContent = val ?? "—";
      tr.append(td);
    });
    tbody.append(tr);
  });
  tbl.append(tbody);
  root.append(tbl);
}

function renderKvList(id, pairs) {
  const root = $(id);
  if (!root) return;
  root.replaceChildren();
  pairs.forEach(([k, v]) => {
    const row = document.createElement("div");
    row.className = "kv-row";
    const kSpan = document.createElement("span");
    kSpan.className = "muted";
    kSpan.textContent = k;
    const vSpan = document.createElement("span");
    vSpan.className = "mono";
    vSpan.textContent = v ?? "—";
    row.append(kSpan, vSpan);
    root.append(row);
  });
}

function renderSignals() {
  const q = ($("signal-search")?.value || "").trim().toUpperCase();
  const filtered = (signalsData || []).filter(s =>
    !q ||
    (s.symbol || "").toUpperCase().includes(q) ||
    (s.state || "").toUpperCase().includes(q) ||
    (s.reason || "").toUpperCase().includes(q)
  );
  renderTable(
    "signal-table",
    ["标的", "类型", "状态", "参考价", "决策归因", "源时间 (UTC)"],
    filtered.map(s => [
      s.symbol,
      s.kind,
      s.state,
      s.reference_price ? "$" + s.reference_price : "—",
      s.reason,
      s.source_ms ? new Date(s.source_ms).toISOString() : "—"
    ])
  );
}

function renderUniverse() {
  if (!universeData) return;
  const query = ($("search")?.value || "").toUpperCase().trim();
  const focusSet = new Set(universeData.focus || []);
  const rows = (universeData.symbols || [])
    .filter(s => s.includes(query))
    .map(s => [
      s,
      universeData.rules?.[s]?.tradability || "待核验",
      focusSet.has(s) ? "★ 重点订阅" : "候选观察"
    ]);
  renderTable("universe-table", ["股票代码", "平台交易方向", "订阅层级"], rows);
}

function drawEquityCurve(canvas, points) {
  if (!canvas || !points || points.length < 2) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width = 340;
  const h = canvas.height = 110;
  ctx.clearRect(0, 0, w, h);

  const vals = points.map(p => parseFloat(p.equity)).filter(v => Number.isFinite(v));
  if (vals.length < 2) return;
  const low = Math.min(...vals);
  const high = Math.max(...vals);
  const span = Math.max(high - low, 0.01);
  const isGain = vals[vals.length - 1] >= vals[0];

  ctx.strokeStyle = isGain ? "#10b981" : "#f43f5e";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  vals.forEach((v, idx) => {
    const x = (w - 16) * (idx / (vals.length - 1)) + 8;
    const y = h - 12 - (h - 24) * ((v - low) / span);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function loadDemo() {
  try {
    const d = await api("demo");
    const root = $("demo-scenarios");
    if (!root) return;
    root.replaceChildren();
    (d.scenarios || []).forEach(sc => {
      const card = document.createElement("div");
      card.className = "demo-card";
      const title = document.createElement("h3");
      title.textContent = sc.scenario === "TAKE_PROFIT"
        ? "场景：净止盈退出 (+1.75%)"
        : sc.scenario === "STOP_LOSS"
        ? "场景：净止损退出 (-0.80%)"
        : "场景：当日亏损熔断保护";
      const sub = document.createElement("p");
      sub.className = "muted small mono";
      sub.textContent = `期末现金 $${sc.account?.cash || "0"} · 已实现盈亏 $${sc.account?.realized_pnl || "0"}`;
      const canvas = document.createElement("canvas");
      canvas.className = "equity-canvas";
      card.append(title, sub, canvas);
      root.append(card);
      drawEquityCurve(canvas, sc.equity_curve || []);
    });
  } catch (e) {
    showError(e.message);
  }
}

async function loadEvolution() {
  try {
    const evo = await api("evolution/ai-context");
    const grid = $("evolution-reviews-grid");
    if (grid) {
      grid.replaceChildren();
      const latest = evo.latest_reviews_by_period || {};
      const order = [
        ["DAILY", "每日复盘 (1D)"],
        ["TRADING_5D", "每5交易日 (5D)"],
        ["MONTHLY", "月度复盘 (1M)"],
        ["QUARTERLY", "季度复盘 (1Q)"],
        ["SEMIANNUAL", "半年度复盘 (6M)"]
      ];
      order.forEach(([key, label]) => {
        const rev = latest[key];
        const card = document.createElement("div");
        card.className = "demo-card";
        const h3 = document.createElement("h3");
        h3.textContent = label;
        const p = document.createElement("p");
        p.className = "muted small";
        if (rev) {
          const pp = rev.paper_performance || {};
          const sd = rev.signal_diagnostics || {};
          const sugg = rev.optimization_suggestions?.[0]?.rationale || "保持当前稳定基线";
          p.textContent = `区间 ${rev.period_key} · 模拟平仓 ${pp.closed_trades_count || 0} 笔 · 胜率 ${pp.win_rate || "0"} · 净收益 $${pp.net_pnl || "0"} · 候选 ${sd.total_candidates || 0} (错失 ${sd.missed_opportunities_count || 0}) · 建议：${sugg}`;
        } else {
          p.textContent = "暂无该周期复盘记录";
        }
        card.append(h3, p);
        grid.append(card);
      });
    }

    const versions = evo.strategy_versions || [];
    renderTable(
      "evolution-versions-table",
      ["版本号", "状态", "样本外门控 (OOS)", "样本外净收益", "备注"],
      versions.map(v => [
        v.version_id,
        v.status,
        v.validation_evidence?.passed_validation ? "✓ 通过" : "待验证/未过",
        "$" + (v.validation_evidence?.out_of_sample_net_pnl || "0.00"),
        v.notes || "—"
      ])
    );
  } catch (e) {
    showError(e.message);
  }
}

async function refreshFees() {
  const fee = await api("fees");
  const checked = fee.observation?.checked_ms;
  const statusStr = fee.status === "CURRENT_PUBLIC_SCHEDULE"
    ? "官方公开费率已核查 (有效期内)"
    : fee.status === "STALE"
    ? "核查已超过 26 小时，等待更新"
    : "尚无成功核查记录";
  text(
    "fee-status-line",
    `${statusStr} · 每天北京时间 09:00 核查 · ${checked ? "上次核查 " + new Date(checked).toLocaleString() : ""} · 账户实际费率仍须独立确认`
  );
  text("fee-body", JSON.stringify(fee.observation?.terms || {}, null, 2));

  if (fee.change && fee.change.id !== acknowledgedFeeChange && fee.change.id !== displayedFeeChange) {
    displayedFeeChange = fee.change.id;
    text(
      "fee-dialog-text",
      "核查时间：" + new Date(fee.change.time_ms).toLocaleString() +
        "\n官方来源：" + fee.source +
        "\n变更类型：" + fee.change.kind +
        "\n原规则：\n" + JSON.stringify(fee.change.before, null, 2) +
        "\n新规则：\n" + JSON.stringify(fee.change.after, null, 2)
    );
    const dlg = $("fee-dialog");
    if (dlg && !dlg.open) dlg.showModal();
  }
}

async function refresh() {
  if (pending || !token) return;
  pending = true;
  try {
    const [status, metric, signals, outcomes, alerts, reports, u, pos] = await Promise.all([
      api("status"),
      api("metrics"),
      api("signals"),
      api("outcomes").catch(() => []),
      api("alerts"),
      api("reports"),
      api("universe"),
      api("positions")
    ]);
    showError("");
    statusData = status;
    signalsData = signals;
    universeData = u;
    positionsData = pos;

    $("login").hidden = true;
    $("workspace").hidden = false;
    $("top-DualChannel").hidden = false;
    $("refresh-btn").hidden = false;
    $("logout").hidden = false;

    const m = metric.latest || {};
    const modes = status.trading_modes || {};
    const paperOn = Boolean(modes.paper_enabled);
    const liveOn = Boolean(modes.live_enabled);
    const sharedSigCount = modes.live_ledger?.received_signals_count || 0;

    text("top-health", status.health);
    text("top-phase", status.market_phase);
    text("pill-paper", `模拟盘: ${paperOn ? "开启" : "关闭"}`);
    text("pill-live", `实盘: ${liveOn ? "开启" : "关闭"}`);
    text("pill-shared", `共享信号: ${sharedSigCount}`);

    text("strategy-headline", `系统运行总览 · 稳定版 ${status.active_strategy_version || "closed-bar-momentum-v2"}`);
    text(
      "connection",
      `行情 ${status.market_connection} · 时段 ${status.market_phase} · 模拟盘 ${paperOn ? "运行中" : "已关闭"} · 实盘 ${liveOn ? "运行中" : "已关闭"} · 更新于 ${new Date().toLocaleTimeString()}`
    );

    text("health", status.health);
    text("mode", status.mode);
    text("symbols", `${status.observed_symbols} / ${status.candidate_count}`);
    text("focus", `${status.focus_count} 个重点实时订阅标的`);
    text("kpi-paper-cash", "$" + (pos.cash || pos.configuration?.initial_cash || "600.00"));
    text("kpi-paper-pnl", `今日已实现盈亏 $${pos.realized_pnl || "0.00"}`);
    text("latency", number(m.processing?.p95_ms, " ms"));
    text("memory", typeof m.rss_bytes === "number" ? number(m.rss_bytes / 1048576, " MB") : "未测得");

    // Blockers
    const blockers = status.blockers || [];
    text("blocker-count-badge", blockers.length ? `${blockers.length} 项阻断` : "全部就绪");
    $("blockers").replaceChildren(
      ...(blockers.length
        ? blockers.map(code => {
            const div = document.createElement("div");
            div.className = "diag-item";
            div.textContent = `${blockerTitles[code] || code} [${code}]`;
            return div;
          })
        : [(() => {
            const d = document.createElement("div");
            d.className = "diag-item";
            d.textContent = "✓ 所有开仓前置风控门控已就绪";
            return d;
          })()])
    );

    // Feeds
    $("feeds").replaceChildren(
      ...(status.feeds || []).map((f, i) => {
        const row = document.createElement("div");
        row.className = "feed-row";
        const label = document.createElement("span");
        const role = f.role || (i === 0 ? "price" : "focus");
        label.textContent = `${role} (${f.connected ? "已连接" : "重连中"} · ${f.data_gap ? "缺口锁定" : "连续正常"})`;
        const value = document.createElement("span");
        value.className = "mono muted small";
        value.textContent = `队列 ${f.queue} · 重连 ${f.reconnects} · 丢弃 ${f.dropped || 0}`;
        row.append(label, value);
        return row;
      })
    );
    text("source-age", "源延迟 P95: " + number(m.source_age?.p95_ms, " ms"));

    // Focus symbols
    $("focus-symbols").replaceChildren(
      ...(status.focus_symbols || []).map(s => {
        const span = document.createElement("span");
        span.className = "tag";
        span.textContent = s;
        span.onclick = () => {
          document.querySelector('[data-tab="signals"]')?.click();
          if ($("search")) {
            $("search").value = s;
            renderUniverse();
          }
        };
        return span;
      })
    );

    // Signals & Outcomes & Universe
    renderSignals();
    renderTable(
      "outcome-table",
      ["标的", "观察窗口", "触发参考价", "观察价", "收益率"],
      (outcomes || []).map(o => [
        o.symbol,
        (o.horizon_minutes || o.horizon || "—") + "m",
        o.reference_price ? "$" + o.reference_price : "—",
        o.observed_price || o.price || "—",
        o.return_pct || "—"
      ])
    );
    const ver = u.instrument_verification || {};
    text(
      "universe-summary",
      `共 ${u.symbols?.length || 0} 个候选标的 · 元数据状态 ${u.metadata_status || "UNVERIFIED"} (已核验 US STOCK/ETF: ${ver.verified_count || 0})`
    );
    renderUniverse();

    // Dual-Channel Trading
    const pCfg = pos.configuration || {};
    renderKvList("paper-summary", [
      ["模拟账户状态", pos.enabled ? "已初始化 (独立撮合)" : `等待核验 (${pos.reason || "—"})`],
      ["初始资金 / 可用现金", `$${pCfg.initial_cash || "600"} / $${pos.cash || pCfg.initial_cash || "600"}`],
      ["单笔上限 / 总敞口上限", `$${pCfg.per_order_budget || "300"} / $${pCfg.max_exposure || "600"}`],
      ["同时持仓上限 / 每日标的上限", `${pCfg.max_positions || 2} 笔 / ${pCfg.max_daily_symbols || 5} 个`],
      ["当日已实现盈亏 / 熔断阈值", `$${pos.realized_pnl || "0.00"} / -$${pCfg.max_daily_loss || "6"}`]
    ]);
    renderTable(
      "paper-positions-table",
      ["标的", "持仓股数", "持仓成本"],
      (pos.positions || []).map(p => [p.symbol, p.quantity, "$" + p.cost])
    );
    renderTable(
      "paper-orders-table",
      ["标的", "方向", "状态", "数量 / 已成交", "限价", "原因"],
      (pos.orders || []).slice(-20).reverse().map(o => [
        o.symbol,
        o.side,
        o.state,
        `${o.quantity} / ${o.filled}`,
        "$" + o.limit,
        o.reason
      ])
    );

    const ledger = modes.live_ledger || {};
    const lCfg = modes.live_config?.configuration || ledger.configuration || {};
    text("live-main-free", "$" + (ledger.main_usdc_free || "0.00"));
    text("live-main-res", "预占 $" + (ledger.main_usdc_reserved || "0.00"));
    text("live-card-settle", "$" + (ledger.card_settlement_usdc || "0.00"));
    renderKvList("live-summary", [
      ["账本命名空间", ledger.account_namespace || "LIVE_EQUITY_MAIN_USDC_CARD"],
      ["启动对账状态", ledger.reconciled ? "✓ 已完成对账" : "未完成对账 (禁止实盘自动开仓)"],
      ["实盘分配资金 / 单笔上限", `$${lCfg.allocated_usdc || "600"} USDC / $${lCfg.per_order_budget || "300"}`],
      ["同时持仓 / 每日标的上限", `${lCfg.max_positions || 2} 笔 / ${lCfg.max_daily_symbols || 5} 个`],
      ["净止盈 / 净止损触发比例", `${lCfg.take_profit_pct || "0.0175"} / ${lCfg.stop_loss_pct || "0.0080"}`],
      ["手工既有持仓隔离数", `${Object.keys(ledger.external_positions || {}).length} 个标的 (策略不接管)`]
    ]);

    // Alerts & Reports
    text("alert-count-badge", String((alerts || []).length));
    renderTable(
      "alert-table",
      ["触发时间 (UTC)", "告警代码", "诊断详情"],
      (alerts || []).map(a => [new Date(a.time_ms).toISOString(), a.code, JSON.stringify(a.detail)])
    );

    $("report-list").replaceChildren(
      ...(reports || []).map(r => {
        const button = document.createElement("button");
        button.className = "btn-secondary";
        button.textContent = r.date;
        button.onclick = async () => {
          try {
            text("report-body", await api("reports/" + r.date));
          } catch (e) {
            showError(e.message);
          }
        };
        return button;
      })
    );
    if (!reports || !reports.length) text("report-body", "暂无日报，等待定时生成。");

    await refreshFees();
  } catch (e) {
    showError(e.message);
  } finally {
    pending = false;
  }
}

// Event Listeners
$("theme-toggle").onclick = () => {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("obr-theme", next); } catch (e) {}
};

$("refresh-btn").onclick = refresh;

$("login-form").onsubmit = async event => {
  event.preventDefault();
  token = $("token").value.trim();
  $("token").value = "";
  await refresh();
  clearInterval(timer);
  timer = setInterval(refresh, 10000);
};

$("logout").onclick = () => {
  token = "";
  clearInterval(timer);
  $("workspace").hidden = true;
  $("top-DualChannel").hidden = true;
  $("refresh-btn").hidden = true;
  $("logout").hidden = true;
  $("login").hidden = false;
  showError("");
  showNotice("");
};

document.querySelectorAll("[data-tab]").forEach(button => {
  button.onclick = () => {
    const tab = button.dataset.tab;
    document.querySelectorAll(".panel").forEach(p => { p.hidden = p.id !== tab; });
    document.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("active", b === button));
    if (tab === "evolution") loadEvolution();
    if (tab === "trading" && !$("demo-scenarios")?.children.length) loadDemo();
  };
});

$("search").oninput = renderUniverse;
if ($("signal-search")) $("signal-search").oninput = renderSignals;
if ($("run-demo-btn")) $("run-demo-btn").onclick = loadDemo;
if ($("refresh-evolution-btn")) $("refresh-evolution-btn").onclick = loadEvolution;

$("fee-ack-btn").onclick = () => {
  acknowledgedFeeChange = displayedFeeChange;
  try { localStorage.setItem("obr-fee-change-ack", displayedFeeChange); } catch (e) {}
  $("fee-dialog").close();
};

function openControlModal(title, desc, actionFn) {
  text("control-dialog-title", title);
  text("control-dialog-desc", desc);
  $("control-fields").replaceChildren();
  $("control-token-input").value = "";
  pendingControlAction = actionFn;
  $("control-dialog").showModal();
}

$("control-cancel-btn").onclick = () => {
  pendingControlAction = null;
  $("control-dialog").close();
};

$("control-form").onsubmit = async e => {
  e.preventDefault();
  const ctrl = $("control-token-input").value.trim();
  if (!pendingControlAction) return;
  try {
    await pendingControlAction(ctrl);
    $("control-dialog").close();
    pendingControlAction = null;
    await refresh();
  } catch (err) {
    showError(err.message);
  }
};

$("quick-paper-toggle").onclick = () => {
  const modes = statusData?.trading_modes || {};
  const next = modes.paper_enabled ? "PAPER_OFF" : "PAPER_ON";
  openControlModal(
    next === "PAPER_ON" ? "开启模拟盘通道" : "关闭模拟盘通道",
    "模拟盘与实盘共用同一套 ORB-Math 确认信号，资金与订单独立核算。",
    async ctrl => {
      await api("trading-mode", "POST", { mode: next, revision: modes.revision || 0 }, ctrl);
      showNotice("模拟盘通道状态已更新");
    }
  );
};

$("quick-live-toggle").onclick = () => {
  const modes = statusData?.trading_modes || {};
  const next = modes.live_enabled ? "LIVE_OFF" : "LIVE_ON";
  openControlModal(
    next === "LIVE_ON" ? "开启实盘通道 (模拟盘照样运行)" : "关闭实盘通道",
    "实盘买入使用 MAIN 现货 USDC，卖出结算至 CARD 钱包，不自动划转。",
    async ctrl => {
      await api("trading-mode", "POST", { mode: next, revision: modes.revision || 0 }, ctrl);
      showNotice("实盘通道状态已更新");
    }
  );
};

if ($("open-paper-config")) {
  $("open-paper-config").onclick = async () => {
    try {
      const saved = await api("paper-config");
      const cfg = saved.configuration || {};
      openControlModal(
        "配置模拟盘预算与风险限额",
        "保存前请先关闭模拟盘开关并确保无未平仓头寸。",
        async ctrl => {
          const payload = {
            revision: saved.revision || 0,
            initial_cash: $("f-initial_cash").value.trim(),
            per_order_budget: $("f-per_order_budget").value.trim(),
            max_positions: parseInt($("f-max_positions").value, 10),
            max_daily_loss: $("f-max_daily_loss").value.trim(),
            max_exposure: $("f-max_exposure").value.trim(),
            max_daily_symbols: parseInt($("f-max_daily_symbols").value, 10)
          };
          await api("paper-config", "POST", payload, ctrl);
          showNotice("模拟盘预算配置已原子保存");
        }
      );
      const fields = [
        ["initial_cash", "初始模拟资金 (USD)", cfg.initial_cash || "600"],
        ["per_order_budget", "单笔含费上限 (USD)", cfg.per_order_budget || "300"],
        ["max_positions", "同时持仓上限 (1-5)", cfg.max_positions || 2],
        ["max_daily_loss", "当日亏损熔断上限 (USD)", cfg.max_daily_loss || "6"],
        ["max_exposure", "总敞口上限 (USD)", cfg.max_exposure || "600"],
        ["max_daily_symbols", "每日标的数上限 (1-5)", cfg.max_daily_symbols || 5]
      ];
      fields.forEach(([k, labelText, val]) => {
        const lbl = document.createElement("label");
        lbl.textContent = labelText;
        const inp = document.createElement("input");
        inp.id = "f-" + k;
        inp.value = String(val);
        if (k === "initial_cash" && saved.initial_cash_locked) inp.disabled = true;
        $("control-fields").append(lbl, inp);
      });
    } catch (e) {
      showError(e.message);
    }
  };
}

if ($("open-live-config")) {
  $("open-live-config").onclick = async () => {
    try {
      const saved = await api("live-config");
      const cfg = saved.configuration || {};
      openControlModal(
        "配置实盘仓位与止盈止损参数",
        "买入使用 MAIN 现货 USDC，卖出结算至 CARD；与模拟盘共用同一套确认信号。",
        async ctrl => {
          const payload = {
            revision: saved.revision || 0,
            allocated_usdc: $("fl-allocated_usdc").value.trim(),
            per_order_budget: $("fl-per_order_budget").value.trim(),
            max_positions: parseInt($("fl-max_positions").value, 10),
            max_daily_loss: $("fl-max_daily_loss").value.trim(),
            max_exposure: $("fl-max_exposure").value.trim(),
            max_daily_symbols: parseInt($("fl-max_daily_symbols").value, 10),
            take_profit_pct: $("fl-take_profit_pct").value.trim(),
            stop_loss_pct: $("fl-stop_loss_pct").value.trim()
          };
          await api("live-config", "POST", payload, ctrl);
          showNotice("实盘仓位参数已保存生效");
        }
      );
      const fields = [
        ["allocated_usdc", "实盘分配资金 (MAIN USDC)", cfg.allocated_usdc || "600"],
        ["per_order_budget", "单笔含费上限 (USDC)", cfg.per_order_budget || "300"],
        ["max_positions", "同时持仓上限 (1-5)", cfg.max_positions || 2],
        ["max_daily_loss", "日亏损熔断上限 (USDC)", cfg.max_daily_loss || "30"],
        ["max_exposure", "总敞口上限 (USDC)", cfg.max_exposure || "600"],
        ["max_daily_symbols", "每日标的数上限 (1-5)", cfg.max_daily_symbols || 5],
        ["take_profit_pct", "净止盈比例 (如 0.0175)", cfg.take_profit_pct || "0.0175"],
        ["stop_loss_pct", "净止损比例 (如 0.0080)", cfg.stop_loss_pct || "0.0080"]
      ];
      fields.forEach(([k, labelText, val]) => {
        const lbl = document.createElement("label");
        lbl.textContent = labelText;
        const inp = document.createElement("input");
        inp.id = "fl-" + k;
        inp.value = String(val);
        $("control-fields").append(lbl, inp);
      });
    } catch (e) {
      showError(e.message);
    }
  };
}

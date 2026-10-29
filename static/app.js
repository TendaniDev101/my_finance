const { createApp, ref, reactive, computed, nextTick } = Vue;

const SECTOR_ICONS = {
  "Banks": "\u{1F3E6}", "Mining": "⛏️", "Mining / Chemicals": "⚗️",
  "Property": "\u{1F3E2}", "Telecoms": "\u{1F4E1}", "Insurance": "\u{1F6E1}️",
  "Food": "\u{1F35E}", "Healthcare": "\u{1F3E5}", "Tech / Media": "\u{1F4BB}",
  "Luxury Goods": "\u{1F48E}", "Consumer Staples": "\u{1F6D2}",
  "Consumer Discretionary": "\u{1F6CD}️", "Industrials": "\u{1F3ED}",
  "Logistics": "\u{1F69A}", "Education": "\u{1F393}", "Hospitality & Gaming": "\u{1F3B0}",
  "Packaging": "\u{1F4E6}", "Agriculture / Chemicals": "\u{1F33E}",
  "Diversified Financials": "\u{1F4B0}", "Investment Holding": "\u{1F3DB}️",
};

const COLOR = { blue: "#2a78d6", red: "#e34948", aqua: "#1baf7a", muted: "#898781", grid: "#e1e0d9", ink: "#0b0b0b" };

// Saved portfolios are persisted server-side via /api/saved-portfolios, backed
// by Postgres (see db.py). Locally that's a Homebrew Postgres instance; on a
// real deployment DATABASE_URL needs to point at something Cloud Run can
// actually reach (its own filesystem is stateless, and it can't reach a
// database sitting on someone's laptop) - that's a separate, not-yet-made
// decision (Cloud SQL / Neon / Supabase). Until DATABASE_URL is wired up
// there, these endpoints 503 - handled below by just showing an error.
const SAVE_PRINCIPAL = 100; // the hypothetical "invest R100" amount

Chart.register(ChartDataLabels);
Chart.defaults.set("plugins.datalabels", { display: false });

createApp({
  setup() {
    const appEl = document.getElementById("app");
    const minTickers = Number(appEl.dataset.min || 2);
    const maxTickers = Number(appEl.dataset.max || 25);

    const universe = reactive({});
    const bySector = reactive({});
    const selected = reactive([]);
    const search = ref("");
    const view = ref("grid");
    const currentSector = ref(null);
    const loading = ref(false);
    const errorMsg = ref("");
    const result = ref(null);
    const chartCanvas = ref(null);
    let chartInstance = null;

    const savedPortfolios = reactive([]);
    const savedError = ref("");
    const savedLoading = ref(false);

    async function loadSavedPortfolios() {
      savedLoading.value = true;
      savedError.value = "";
      try {
        const res = await fetch("/api/saved-portfolios");
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || "Could not load saved portfolios");
        savedPortfolios.splice(0, savedPortfolios.length, ...body.map(fromApiShape));
      } catch (err) {
        savedError.value = err.message;
      } finally {
        savedLoading.value = false;
      }
    }

    // The DB stores kind/principal/holdings/expected_return/expected_risk;
    // everything else the UI needs (label, live current_value, refreshing
    // state) is derived/ephemeral and only ever lives in memory.
    function fromApiShape(row) {
      return {
        id: row.id,
        kind: row.kind,
        label: row.kind === "max_sharpe" ? "Max-Sharpe" : "Min-variance",
        saved_at: row.saved_at,
        principal: row.principal,
        holdings: row.holdings,
        expected_return: row.expected_return,
        expected_risk: row.expected_risk,
        current_value: null,
        as_of: null,
        refreshing: false,
        error: null,
      };
    }

    async function loadUniverse() {
      const res = await fetch("/api/universe");
      const data = await res.json();
      Object.assign(universe, data);

      const grouped = {};
      for (const [ticker, info] of Object.entries(data)) {
        (grouped[info.sector] ??= []).push(ticker);
      }
      for (const tickers of Object.values(grouped)) {
        tickers.sort((a, b) => data[a].name.localeCompare(data[b].name));
      }
      Object.assign(bySector, grouped);
    }

    const sectors = computed(() =>
      Object.keys(bySector)
        .sort()
        .map((name) => ({
          name,
          tickers: bySector[name],
          selectedCount: bySector[name].filter((t) => selected.includes(t)).length,
        }))
    );

    const searchResults = computed(() => {
      const q = search.value.trim().toLowerCase();
      if (!q) return [];
      return Object.keys(universe)
        .filter((t) => t.toLowerCase().includes(q) || universe[t].name.toLowerCase().includes(q))
        .sort((a, b) => universe[a].name.localeCompare(universe[b].name));
    });

    const canBuild = computed(() => selected.length >= minTickers && selected.length <= maxTickers);

    function isSelected(ticker) {
      return selected.includes(ticker);
    }
    function isDisabled(ticker) {
      return !isSelected(ticker) && selected.length >= maxTickers;
    }
    function chipClass(ticker) {
      return { "chip-selected": isSelected(ticker), "chip-disabled": isDisabled(ticker) };
    }
    function toggle(ticker) {
      const i = selected.indexOf(ticker);
      if (i >= 0) selected.splice(i, 1);
      else if (selected.length < maxTickers) selected.push(ticker);
    }
    function clearSelection() {
      selected.splice(0, selected.length);
    }
    function openSector(name) {
      currentSector.value = name;
      view.value = "detail";
    }
    function shortTicker(t) {
      return t.replace(".JO", "");
    }
    function sectorIcon(name) {
      return SECTOR_ICONS[name] || "\u{1F4C8}";
    }
    function pct(x) {
      return `${(x * 100).toFixed(1)}%`;
    }
    function sortedWeights(weights) {
      return Object.entries(weights).sort((a, b) => b[1] - a[1]);
    }

    const portfolioCards = computed(() =>
      result.value
        ? [
            { key: "max_sharpe", label: "Max-Sharpe portfolio", data: result.value.max_sharpe },
            { key: "min_variance", label: "Min-variance portfolio", data: result.value.min_variance },
          ]
        : []
    );

    async function savePortfolio(key) {
      if (!result.value) return;
      const portfolio = result.value[key];
      const assetsByTicker = Object.fromEntries(result.value.assets.map((a) => [a.ticker, a]));

      const holdings = Object.entries(portfolio.weights).map(([ticker, weight]) => {
        const price = assetsByTicker[ticker]?.price;
        return {
          ticker,
          name: assetsByTicker[ticker]?.name ?? ticker,
          weight,
          price_at_save: price,
          shares: (weight * SAVE_PRINCIPAL) / price,
        };
      });

      savedError.value = "";
      try {
        const res = await fetch("/api/saved-portfolios", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind: key, principal: SAVE_PRINCIPAL, holdings,
            expected_return: portfolio.return, expected_risk: portfolio.risk,
          }),
        });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || "Could not save this portfolio");
        savedPortfolios.unshift(fromApiShape(body));
      } catch (err) {
        savedError.value = err.message;
      }
    }

    async function removeSavedPortfolio(id) {
      savedError.value = "";
      try {
        const res = await fetch(`/api/saved-portfolios/${id}`, { method: "DELETE" });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "Could not remove this portfolio");
        }
        const i = savedPortfolios.findIndex((e) => e.id === id);
        if (i >= 0) savedPortfolios.splice(i, 1);
      } catch (err) {
        savedError.value = err.message;
      }
    }

    async function refreshSavedPortfolio(entry) {
      entry.refreshing = true;
      entry.error = null;
      try {
        const res = await fetch("/api/portfolio-value", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ holdings: entry.holdings.map((h) => ({ ticker: h.ticker, shares: h.shares })) }),
        });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || "Could not refresh");
        entry.current_value = body.total_value;
        entry.as_of = body.as_of;
      } catch (err) {
        entry.error = err.message;
      } finally {
        entry.refreshing = false;
      }
    }

    function refreshAllSavedPortfolios() {
      savedPortfolios.forEach(refreshSavedPortfolio);
    }

    function gainPct(entry) {
      if (entry.current_value == null) return null;
      return (entry.current_value - entry.principal) / entry.principal;
    }

    function elapsedLabel(isoDate) {
      const days = Math.floor((Date.now() - new Date(isoDate).getTime()) / 86400000);
      if (days <= 0) return "today";
      if (days === 1) return "1 day ago";
      if (days < 30) return `${days} days ago`;
      const months = Math.floor(days / 30);
      return months === 1 ? "1 month ago" : `${months} months ago`;
    }

    async function buildPortfolio() {
      errorMsg.value = "";
      loading.value = true;
      result.value = null;
      try {
        const res = await fetch("/api/optimize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tickers: [...selected] }),
        });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || "Something went wrong");
        result.value = body;
        await nextTick();
        renderChart(body);
        document.getElementById("results")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) {
        errorMsg.value = err.message;
      } finally {
        loading.value = false;
      }
    }

    function renderChart(data) {
      if (!chartCanvas.value) return;
      const frontierPoints = data.frontier.map((p) => ({ x: p.risk, y: p.return })).sort((a, b) => a.x - b.x);
      const assetPoints = data.assets.map((a) => ({ x: a.ann_vol, y: a.ann_return, label: shortTicker(a.ticker) }));

      // Chart.js's `order` is counterintuitive (confirmed against Chart.js's
      // own docs after the first attempt at this got it backwards): HIGHER
      // order is drawn FIRST, so it ends up UNDERNEATH; LOWER order is drawn
      // LAST, so it ends up ON TOP. The frontier line needs the highest
      // number (drawn first/underneath) so the point markers - especially
      // Max Sharpe, which sits mid-curve, not at an endpoint - render on top
      // of it instead of being cut through by the line.
      const datasets = [
        {
          type: "line", label: "Efficient frontier", data: frontierPoints,
          borderColor: COLOR.blue, borderWidth: 2, pointRadius: 0, fill: false, tension: 0.15, order: 4,
        },
        {
          type: "scatter", label: "Individual stocks", data: assetPoints,
          backgroundColor: COLOR.muted, pointRadius: 5, order: 3,
          datalabels: { display: true, formatter: (v) => v.label, align: "top", color: COLOR.ink, font: { size: 10 } },
        },
        {
          type: "scatter", label: "Min variance",
          data: [{ x: data.min_variance.risk, y: data.min_variance.return, label: "Min Var" }],
          backgroundColor: COLOR.aqua, pointStyle: "rectRot", pointRadius: 9, order: 2,
          datalabels: { display: true, formatter: (v) => v.label, align: "bottom", color: COLOR.aqua, font: { size: 11, weight: "bold" } },
        },
        {
          type: "scatter", label: "Max Sharpe",
          data: [{ x: data.max_sharpe.risk, y: data.max_sharpe.return, label: "Max Sharpe" }],
          backgroundColor: COLOR.red, pointStyle: "star", pointRadius: 11, order: 1,
          datalabels: { display: true, formatter: (v) => v.label, align: "top", color: COLOR.red, font: { size: 11, weight: "bold" } },
        },
      ];

      if (chartInstance) chartInstance.destroy();
      chartInstance = new Chart(chartCanvas.value, {
        type: "scatter",
        data: { datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false, // fill .chart-wrap's fixed CSS height instead of deriving height from width
          interaction: { mode: "nearest", intersect: true },
          plugins: {
            legend: { position: "bottom" },
            tooltip: {
              callbacks: {
                label: (item) => `${item.raw.label ?? ""}  risk ${pct(item.raw.x)} · return ${pct(item.raw.y)}`,
              },
            },
          },
          scales: {
            x: { title: { display: true, text: "Annualized volatility (risk)" }, ticks: { callback: (v) => pct(v) }, grid: { color: COLOR.grid } },
            y: { title: { display: true, text: "Annualized expected return" }, ticks: { callback: (v) => pct(v) }, grid: { color: COLOR.grid } },
          },
        },
      });
    }

    loadUniverse();
    loadSavedPortfolios().then(refreshAllSavedPortfolios);

    return {
      universe, bySector, selected, search, view, currentSector, loading, errorMsg, result, chartCanvas,
      maxTickers, sectors, searchResults, canBuild, portfolioCards,
      isSelected, isDisabled, chipClass, toggle, clearSelection, openSector,
      shortTicker, sectorIcon, pct, sortedWeights, buildPortfolio,
      savedPortfolios, savedError, savedLoading, savePortfolio, removeSavedPortfolio,
      refreshSavedPortfolio, refreshAllSavedPortfolios, gainPct, elapsedLabel,
    };
  },
}).mount("#app");

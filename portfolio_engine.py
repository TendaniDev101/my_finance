"""
Core portfolio math for the web app: live JSE data -> cleaned returns ->
classic (unconstrained-cap) long-only mean-variance optimization ->
efficient frontier. Deliberately the "clean textbook demo" version - no
per-asset or per-sector caps, no return/covariance shrinkage - so the
frontier is easy to explain and sanity-check against theory.
"""
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize

TRADING_DAYS = 252
ZAR_RISK_FREE_RATE = 0.065  # SA 3-month T-bill, ~Oct 2026 - verify before relying on it

UNIVERSE = {
    # --- original 30 ---
    "FSR.JO": ("FirstRand", "Banks"), "SBK.JO": ("Standard Bank", "Banks"),
    "CPI.JO": ("Capitec", "Banks"), "NED.JO": ("Nedbank", "Banks"),
    "ABG.JO": ("Absa", "Banks"), "SHP.JO": ("Shoprite", "Consumer Staples"),
    "WHL.JO": ("Woolworths", "Consumer Staples"), "MRP.JO": ("Mr Price", "Consumer Discretionary"),
    "PIK.JO": ("Pick n Pay", "Consumer Staples"), "TFG.JO": ("The Foschini Group", "Consumer Discretionary"),
    "AGL.JO": ("Anglo American", "Mining"), "GFI.JO": ("Gold Fields", "Mining"),
    "IMP.JO": ("Impala Platinum", "Mining"), "KIO.JO": ("Kumba Iron Ore", "Mining"),
    "SOL.JO": ("Sasol", "Mining / Chemicals"), "VOD.JO": ("Vodacom", "Telecoms"),
    "MTN.JO": ("MTN Group", "Telecoms"), "NPN.JO": ("Naspers", "Tech / Media"),
    "PRX.JO": ("Prosus", "Tech / Media"), "CFR.JO": ("Richemont", "Luxury Goods"),
    "BVT.JO": ("Bidvest", "Industrials"), "BID.JO": ("Bid Corp", "Industrials"),
    "SLM.JO": ("Sanlam", "Insurance"), "OMU.JO": ("Old Mutual", "Insurance"),
    "DSY.JO": ("Discovery", "Insurance"), "GRT.JO": ("Growthpoint", "Property"),
    "TBS.JO": ("Tiger Brands", "Food"), "CLS.JO": ("Clicks Group", "Consumer Staples"),
    "APN.JO": ("Aspen Pharmacare", "Healthcare"), "REM.JO": ("Remgro", "Investment Holding"),

    # --- added batch: verified valid + ZAc currency on Yahoo ---
    "SPP.JO": ("Spar Group", "Consumer Staples"), "LHC.JO": ("Life Healthcare", "Healthcare"),
    "ITE.JO": ("Italtile", "Consumer Discretionary"), "TRU.JO": ("Truworths", "Consumer Discretionary"),
    "CLH.JO": ("City Lodge Hotels", "Hospitality & Gaming"), "SUI.JO": ("Sun International", "Hospitality & Gaming"),
    "AVI.JO": ("AVI Limited", "Food"), "PPH.JO": ("Pepkor Holdings", "Consumer Discretionary"),
    "NPH.JO": ("Northam Platinum", "Mining"), "SSW.JO": ("Sibanye-Stillwater", "Mining"),
    "EXX.JO": ("Exxaro Resources", "Mining"), "ARI.JO": ("African Rainbow Minerals", "Mining"),
    "HAR.JO": ("Harmony Gold", "Mining"), "PAN.JO": ("Pan African Resources", "Mining"),
    "GLN.JO": ("Glencore", "Mining"), "S32.JO": ("South32", "Mining"),
    "RDF.JO": ("Redefine Properties", "Property"), "FFB.JO": ("Fortress REIT B", "Property"),
    "EQU.JO": ("Equites Property Fund", "Property"), "HYP.JO": ("Hyprop Investments", "Property"),
    "RES.JO": ("Resilient REIT", "Property"), "RLO.JO": ("Reunert", "Industrials"),
    "WBO.JO": ("Wilson Bayly Holmes-Ovcon", "Industrials"), "PPC.JO": ("PPC", "Industrials"),
    "AEL.JO": ("Altron", "Industrials"), "KAP.JO": ("KAP Industrial", "Industrials"),
    "OMN.JO": ("Omnia Holdings", "Agriculture / Chemicals"), "INL.JO": ("Investec Limited", "Diversified Financials"),
    "INP.JO": ("Investec plc", "Diversified Financials"), "MPT.JO": ("Mpact", "Packaging"),
    "MTH.JO": ("Motus Holdings", "Industrials"), "SPG.JO": ("Super Group", "Logistics"),
    "NTC.JO": ("Netcare", "Healthcare"),

    # --- second added batch: verified valid + ZAc currency on Yahoo ---
    "SNT.JO": ("Santam", "Insurance"), "OUT.JO": ("OUTsurance Group", "Insurance"),
    "KST.JO": ("PSG Konsult", "Diversified Financials"), "BAT.JO": ("Brait", "Diversified Financials"),
    "HCI.JO": ("Hosken Consolidated Investments", "Diversified Financials"),
    "SBP.JO": ("Sabvest Capital", "Diversified Financials"), "RNI.JO": ("Reinet Investments", "Diversified Financials"),
    "PPE.JO": ("Purple Group", "Diversified Financials"), "CML.JO": ("Coronation Fund Managers", "Diversified Financials"),
    "VKE.JO": ("Vukile Property Fund", "Property"), "SAC.JO": ("SA Corporate Real Estate", "Property"),
    "ATT.JO": ("Attacq", "Property"), "EMI.JO": ("Emira Property Fund", "Property"),
    "OCT.JO": ("Octodec Investments", "Property"), "SSS.JO": ("Stor-Age", "Property"),
    "DIB.JO": ("Dipula Income Fund", "Property"), "NRP.JO": ("NEPI Rockcastle", "Property"),
    "APF.JO": ("Accelerate Property Fund", "Property"), "DLT.JO": ("Delta Property Fund", "Property"),
    "TGA.JO": ("Thungela Resources", "Mining"), "THA.JO": ("Tharisa", "Mining"),
    "DRD.JO": ("DRDGold", "Mining"), "MRF.JO": ("Merafe Resources", "Mining"),
    "AFT.JO": ("Afrimat", "Mining"), "HDC.JO": ("Hudaco Industries", "Industrials"),
    "IVT.JO": ("Invicta Holdings", "Industrials"), "RBX.JO": ("Raubex Group", "Industrials"),
    "GND.JO": ("Grindrod", "Logistics"), "RCL.JO": ("RCL Foods", "Food"),
    "LBR.JO": ("Libstar Holdings", "Food"), "ARL.JO": ("Astral Foods", "Food"),
    "QFH.JO": ("Quantum Foods", "Food"), "PMR.JO": ("Premier Group", "Food"),
    "OCE.JO": ("Oceana Group", "Food"), "LEW.JO": ("Lewis Group", "Consumer Discretionary"),
    "CSB.JO": ("Cashbuild", "Consumer Discretionary"), "DCP.JO": ("Dis-Chem Pharmacies", "Healthcare"),
    "DTC.JO": ("Datatec", "Tech / Media"), "CAT.JO": ("Caxton & CTP Publishers", "Tech / Media"),
    "BYI.JO": ("Bytes Technology Group", "Tech / Media"), "TKG.JO": ("Telkom", "Telecoms"),
    "ADH.JO": ("AdvTech", "Education"),
}

MIN_TICKERS, MAX_TICKERS = 2, 25


class PortfolioError(ValueError):
    pass


def _clean_bad_ticks(prices: pd.DataFrame, threshold=0.5) -> pd.DataFrame:
    """Yahoo's JSE feed occasionally drops a single day's price to ~1% of
    its real value then fully reverts the next trading day. Detect any
    day whose return is reversed almost exactly by the next day's return,
    and repair it by linear interpolation."""
    cleaned = prices.copy()
    for col in cleaned.columns:
        r = cleaned[col].pct_change()
        r_next = r.shift(-1)
        suspicious = (r.abs() > threshold) & (r_next.abs() > threshold) & (np.sign(r) != np.sign(r_next))
        bad_dates = r.index[suspicious]
        if len(bad_dates):
            cleaned.loc[bad_dates, col] = np.nan
    return cleaned.interpolate(method="linear")


def fetch_prices(tickers: list[str], period="3y") -> pd.DataFrame:
    """Live daily close prices in ZAR. Yahoo returns JSE prices in cents
    (ZAc) - dividing by 100 is required, not a style choice."""
    data = yf.download(tickers, period=period, progress=False)["Close"]
    if isinstance(data, pd.Series):
        data = data.to_frame(tickers[0])
    data = data.dropna(how="all").dropna() / 100
    return _clean_bad_ticks(data)


def compute_mu_sigma(returns: pd.DataFrame):
    mu = returns.mean() * TRADING_DAYS
    sigma = returns.cov() * TRADING_DAYS
    return mu, sigma


def portfolio_return(w, mu):
    return float(w @ mu)


def portfolio_volatility(w, sigma):
    return float(np.sqrt(w @ sigma @ w))


def _long_only_constraints(n):
    bounds = tuple((0.0, 1.0) for _ in range(n))
    constraints = ({"type": "eq", "fun": lambda w: np.sum(w) - 1},)
    x0 = np.repeat(1 / n, n)
    return bounds, constraints, x0


def min_variance_portfolio(mu, sigma):
    n = len(mu)
    bounds, constraints, x0 = _long_only_constraints(n)
    result = minimize(lambda w: portfolio_volatility(w, sigma), x0,
                       method="SLSQP", bounds=bounds, constraints=constraints)
    if not result.success:
        raise PortfolioError(f"min-variance optimization failed: {result.message}")
    return result.x


def max_sharpe_portfolio(mu, sigma, rf=ZAR_RISK_FREE_RATE):
    n = len(mu)
    bounds, constraints, x0 = _long_only_constraints(n)

    def neg_sharpe(w):
        ret, vol = portfolio_return(w, mu), portfolio_volatility(w, sigma)
        return -(ret - rf) / vol

    result = minimize(neg_sharpe, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    if not result.success:
        raise PortfolioError(f"max-Sharpe optimization failed: {result.message}")
    return result.x


def efficient_frontier(mu, sigma, min_variance_weights, n_points=40):
    """Trace ONLY the efficient (upper) branch: target returns from the
    global minimum-variance portfolio's own return up to the highest
    individual asset return. Scanning down to the lowest asset return
    (as an earlier version did) also finds valid minimum-variance
    portfolios, but on the INEFFICIENT lower branch - same risk, worse
    return. Connecting both branches in one line, sorted by risk,
    zigzags between them instead of tracing a smooth curve.

    Warm-starts each solve from the previous target's weights (adjacent
    targets have similar optimal weights) - far more reliable than
    restarting from equal weights at every point, especially near the
    corners."""
    n = len(mu)
    bounds = tuple((0.0, 1.0) for _ in range(n))
    r_min = portfolio_return(min_variance_weights, mu)
    targets = np.linspace(r_min, mu.max(), n_points)

    risks, rets = [], []
    w_prev = min_variance_weights.copy()
    for target in targets:
        constraints = (
            {"type": "eq", "fun": lambda w: np.sum(w) - 1},
            {"type": "eq", "fun": lambda w, t=target: portfolio_return(w, mu) - t},
        )
        result = minimize(lambda w: portfolio_volatility(w, sigma), w_prev, method="SLSQP",
                           bounds=bounds, constraints=constraints,
                           options={"maxiter": 500, "ftol": 1e-12})
        if result.success:
            risks.append(portfolio_volatility(result.x, sigma))
            rets.append(float(target))
            w_prev = result.x
    return risks, rets


def build_portfolio(tickers: list[str]) -> dict:
    tickers = [t.upper() for t in tickers]
    unknown = [t for t in tickers if t not in UNIVERSE]
    if unknown:
        raise PortfolioError(f"Not in the supported JSE universe: {', '.join(unknown)}")
    if not (MIN_TICKERS <= len(tickers) <= MAX_TICKERS):
        raise PortfolioError(f"Pick between {MIN_TICKERS} and {MAX_TICKERS} stocks (got {len(tickers)}).")

    prices = fetch_prices(tickers)
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        raise PortfolioError(f"No usable price history for: {', '.join(missing)}")

    returns = prices[tickers].pct_change().dropna()
    mu, sigma = compute_mu_sigma(returns)

    min_var_w = min_variance_portfolio(mu, sigma)
    max_sharpe_w = max_sharpe_portfolio(mu, sigma)
    frontier_risk, frontier_return = efficient_frontier(mu, sigma, min_var_w)

    ind_vol = np.sqrt(np.diag(sigma))

    return {
        "window": {"start": str(prices.index.min().date()), "end": str(prices.index.max().date()),
                    "trading_days": len(prices)},
        "assets": [
            {"ticker": t, "name": UNIVERSE[t][0], "sector": UNIVERSE[t][1],
             "ann_return": float(mu[t]), "ann_vol": float(ind_vol[i])}
            for i, t in enumerate(tickers)
        ],
        "frontier": [{"risk": r, "return": ret} for r, ret in zip(frontier_risk, frontier_return)],
        "min_variance": {
            "weights": {t: float(w) for t, w in zip(tickers, min_var_w) if w > 0.001},
            "return": portfolio_return(min_var_w, mu),
            "risk": portfolio_volatility(min_var_w, sigma),
        },
        "max_sharpe": {
            "weights": {t: float(w) for t, w in zip(tickers, max_sharpe_w) if w > 0.001},
            "return": portfolio_return(max_sharpe_w, mu),
            "risk": portfolio_volatility(max_sharpe_w, sigma),
            "sharpe": (portfolio_return(max_sharpe_w, mu) - ZAR_RISK_FREE_RATE) / portfolio_volatility(max_sharpe_w, sigma),
        },
        "risk_free_rate": ZAR_RISK_FREE_RATE,
    }

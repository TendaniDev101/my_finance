# JSE Portfolio Builder

A small local website: pick 6-7 JSE-listed stocks, it fetches live prices
from Yahoo Finance, runs a classic long-only mean-variance optimization
(no caps - the textbook version), and draws the efficient frontier.

## Run it

```bash
cd webapp
/path/to/yFinance/.venv/bin/python -m uvicorn main:app --reload --port 8000
```

Then open http://127.0.0.1:8000

## How it works

- **`portfolio_engine.py`** - the math. Fetches live prices (`yfinance`),
  fixes the same two JSE data issues from the earlier notebook (prices
  come back in cents, not Rand; occasional single-day bad ticks get
  repaired via interpolation), computes annualized mean/covariance, and
  solves: minimum-variance portfolio, maximum-Sharpe portfolio, and the
  efficient frontier (40 points), all long-only with no per-asset caps.
- **`main.py`** - FastAPI app. `GET /` serves the picker page (built with
  plain string substitution, not a template engine - this environment's
  Jinja2/Starlette combination had an internal caching bug, so templating
  was dropped in favor of something with fewer moving parts).
  `POST /api/optimize` takes `{"tickers": [...]}` (6 or 7 JSE tickers from
  the supported universe) and returns the frontier + both portfolios as
  JSON.
- **`static/app.js`** - vanilla JS + Chart.js (loaded from jsDelivr) to
  render the scatter/frontier chart and the two weight tables. No build
  step, no framework.

## Universe

30 liquid, well-known JSE names across 11 sectors (banks, mining,
retail, telecoms, insurance, etc.) - see `UNIVERSE` in
`portfolio_engine.py`. Each one was checked against Yahoo Finance before
being added; one candidate (Anglo American Platinum, `AMS.JO`) was
dropped because Yahoo no longer resolves it, likely after Anglo's 2025
platinum demerger.

## Known limitations

- Live Yahoo Finance data can be slow or occasionally unavailable -
  `/api/optimize` will return a 502 with a message if the fetch fails.
- No caching: every click re-fetches ~2-3 years of daily history for the
  selected tickers. Fine for personal/demo use; add a short-TTL cache
  (e.g. `functools.lru_cache` with a time bucket, or Redis) before
  putting this in front of real traffic.
- This is the "clean textbook demo" variant: no per-asset/sector caps, no
  covariance shrinkage. For something closer to the production pipeline
  in `jse_portfolio.py` (Ledoit-Wolf shrinkage, 30%/asset and 40%/sector
  caps), port those functions into `portfolio_engine.py`.

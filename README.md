# JSE Portfolio Builder

A local website: pick up to 25 JSE-listed stocks (browse by sector or
search), it fetches live prices from Yahoo Finance, runs a classic
long-only mean-variance optimization (no caps - the textbook version),
draws the efficient frontier, and lets you save a portfolio to track a
hypothetical R100 investment in it against real prices over time.

## Run it

```bash
cd webapp
DATABASE_URL="postgresql://<user>@localhost:<port>/jse_portfolio" \
  /path/to/yFinance/.venv/bin/python -m uvicorn main:app --reload --port 8000
```

Then open http://127.0.0.1:8000. `DATABASE_URL` is only needed for the
"save a portfolio" feature - see below. Everything else (picker, live
optimization, the frontier chart) works fine without it.

## Local Postgres setup (for saved portfolios)

Saved portfolios persist server-side in Postgres, not the browser - see
`db.py` for why. One-time setup against a local Homebrew Postgres:

```bash
# find the actual port it's running on - Homebrew defaults to 5432, but
# check `brew services list` / the service's log if that fails; a prior
# instance left this one on 5433
brew services list
createdb -h localhost -p <port> jse_portfolio
```

The table itself (`saved_portfolios`) is created automatically on first
use - no migration step. Then point `DATABASE_URL` at it, e.g.:

```
postgresql://<your-mac-username>@localhost:<port>/jse_portfolio
```

If `DATABASE_URL` is unset or unreachable, the app still starts and the
picker/optimizer still work fine - only `/api/saved-portfolios` and
`/api/portfolio-value` return a 503 instead of crashing anything.

**Deployed (Cloud Run) status**: not yet wired up. Cloud Run's filesystem
is stateless and it can't reach a database on your laptop, so the
deployed site needs `DATABASE_URL` pointed at something actually
reachable over the internet (Cloud SQL, Neon, Supabase, etc.) -
deliberately not decided yet; local dev works today regardless.

## How it works

- **`portfolio_engine.py`** - the math. Fetches live prices (`yfinance`),
  fixes the same two JSE data issues from the earlier notebook (prices
  come back in cents, not Rand; occasional single-day bad ticks get
  repaired via interpolation), computes annualized mean/covariance, and
  solves: minimum-variance portfolio, maximum-Sharpe portfolio, and the
  efficient frontier (40 points, upper branch only), all long-only with
  no per-asset caps.
- **`db.py`** - Postgres persistence for saved portfolios. No ORM - one
  table, plain SQL via `psycopg`. Lazy schema creation (first use, not
  import time), so the app degrades gracefully instead of failing to
  start when the DB isn't reachable.
- **`main.py`** - FastAPI app.
  - `GET /` serves the picker page (plain string substitution, not a
    template engine - this environment's Jinja2/Starlette combination
    had an internal caching bug, dropped in favor of something with
    fewer moving parts)
  - `POST /api/optimize` - `{"tickers": [...]}` (2-25 from the supported
    universe) → frontier + both portfolios, including each stock's
    current price
  - `GET /api/universe` - the full ticker list with names/sectors
  - `POST /api/portfolio-value` - re-prices a holdings list `[{ticker,
    shares}]` against today's live prices, no optimization
  - `POST /api/saved-portfolios`, `GET /api/saved-portfolios`,
    `DELETE /api/saved-portfolios/{id}` - CRUD for saved portfolios
- **`static/app.js`** - Vue 3 (loaded from jsDelivr, no build step) +
  Chart.js for the frontier chart. Drill-down sector picker, a global
  search box, and the saved-portfolios panel all live here.

## Universe

123 liquid, well-known JSE names across 23 sectors - see `UNIVERSE` in
`portfolio_engine.py`. Every ticker was individually checked against
Yahoo Finance (both that it resolves and that it reports in `ZAc`
cents, which the app corrects for) before being added - several
plausible-looking ones turned out to be genuinely delisted (Anglo
American Platinum → renamed `VAL.JO`; MultiChoice → delisted Dec 2025
after the Canal+ takeover; Adcock Ingram, Royal Bafokeng Platinum,
Barloworld, Murray & Roberts, Peregrine Holdings → all taken private).

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
- Saved portfolios are a single shared list (no accounts/auth) - fine for
  a personal tool, not fine for a public multi-user product as-is.

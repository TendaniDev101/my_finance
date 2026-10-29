"""
JSE Portfolio Builder - FastAPI backend.

Run with:  uvicorn main:app --reload --port 8000   (from inside webapp/)
Then open: http://127.0.0.1:8000
"""
import json
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from pathlib import Path

from portfolio_engine import UNIVERSE, MIN_TICKERS, MAX_TICKERS, build_portfolio, get_current_prices, PortfolioError
import db

BASE_DIR = Path(__file__).parent

app = FastAPI(title="JSE Portfolio Builder")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# The frontend (Vue, Cloudflare Pages) is served from a different origin than
# this API (Cloud Run), so the browser needs CORS to allow it. No cookies/auth
# are used here and all data is public market data, so a wildcard default is
# low-risk - but set ALLOWED_ORIGINS once you know the Pages URL to tighten it,
# e.g. ALLOWED_ORIGINS="https://jse-portfolio.pages.dev"
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allowed_origins == "*" else _allowed_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _asset_version(relative_path: str) -> str:
    """mtime of a static file, used to cache-bust it in the URL. StaticFiles
    serves app.js/style.css with no Cache-Control header, so browsers fall
    back to heuristic caching - without this, editing those files during
    dev can silently keep serving a stale cached copy under the same URL."""
    return str(int((BASE_DIR / relative_path).stat().st_mtime))


class OptimizeRequest(BaseModel):
    tickers: list[str]

    @field_validator("tickers")
    @classmethod
    def check_count(cls, v):
        if not (MIN_TICKERS <= len(v) <= MAX_TICKERS):
            raise ValueError(f"Pick between {MIN_TICKERS} and {MAX_TICKERS} stocks")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate tickers selected")
        return v


class Holding(BaseModel):
    ticker: str
    shares: float


class PortfolioValueRequest(BaseModel):
    holdings: list[Holding]

    @field_validator("holdings")
    @classmethod
    def check_holdings(cls, v):
        if not v:
            raise ValueError("No holdings provided")
        return v


class SavedHolding(BaseModel):
    ticker: str
    name: str
    weight: float
    price_at_save: float
    shares: float


class SavePortfolioRequest(BaseModel):
    kind: str
    principal: float
    holdings: list[SavedHolding]
    expected_return: float | None = None
    expected_risk: float | None = None

    @field_validator("kind")
    @classmethod
    def check_kind(cls, v):
        if v not in ("max_sharpe", "min_variance"):
            raise ValueError("kind must be 'max_sharpe' or 'min_variance'")
        return v

    @field_validator("holdings")
    @classmethod
    def check_holdings(cls, v):
        if not v:
            raise ValueError("No holdings provided")
        return v


def _serialize_saved(row: dict) -> dict:
    holdings = row["holdings"]
    if isinstance(holdings, str):  # psycopg may hand back jsonb as raw text
        holdings = json.loads(holdings)
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "saved_at": row["saved_at"].isoformat(),
        "principal": float(row["principal"]),
        "expected_return": float(row["expected_return"]) if row["expected_return"] is not None else None,
        "expected_risk": float(row["expected_risk"]) if row["expected_risk"] is not None else None,
        "holdings": holdings,
    }


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    # Keep every error response in the same {"detail": "<string>"} shape the
    # frontend expects, instead of FastAPI's default list-of-dicts for 422s.
    errors = exc.errors()
    msg = errors[0]["msg"].removeprefix("Value error, ") if errors else "Invalid request"
    return JSONResponse(status_code=400, content={"detail": msg})


@app.get("/", response_class=HTMLResponse)
def index():
    # Re-read from disk on every request (cheap, small file) rather than once
    # at import time - so editing index.html doesn't also require restarting
    # uvicorn to see the change.
    template = (BASE_DIR / "templates" / "index.html").read_text()
    html = (template
            .replace("__MIN_TICKERS__", str(MIN_TICKERS))
            .replace("__MAX_TICKERS__", str(MAX_TICKERS))
            .replace("__APP_JS_V__", _asset_version("static/app.js"))
            .replace("__STYLE_CSS_V__", _asset_version("static/style.css")))
    response = HTMLResponse(html)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/universe")
def api_universe():
    return {t: {"name": n, "sector": s} for t, (n, s) in UNIVERSE.items()}


@app.post("/api/optimize")
def api_optimize(req: OptimizeRequest):
    try:
        return build_portfolio(req.tickers)
    except PortfolioError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch/optimize: {e}")


@app.post("/api/portfolio-value")
def api_portfolio_value(req: PortfolioValueRequest):
    """Re-prices a saved portfolio's holdings (ticker + notional share count)
    against today's live prices - what powers "how has my saved R100 done".
    The saved portfolio itself lives in the browser's localStorage, not here;
    this endpoint only ever sees a holdings list, never anything persistent."""
    tickers = [h.ticker for h in req.holdings]
    try:
        prices, as_of = get_current_prices(tickers)
    except PortfolioError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch current prices: {e}")

    rows = []
    total = 0.0
    for h in req.holdings:
        price = prices[h.ticker]
        value = h.shares * price
        total += value
        rows.append({"ticker": h.ticker, "shares": h.shares, "price": price, "value": value})

    return {"holdings": rows, "total_value": total, "as_of": as_of}


@app.post("/api/saved-portfolios")
def api_save_portfolio(req: SavePortfolioRequest):
    try:
        row = db.insert_saved_portfolio(
            kind=req.kind, principal=req.principal,
            holdings=[h.model_dump() for h in req.holdings],
            expected_return=req.expected_return, expected_risk=req.expected_risk,
        )
    except db.DatabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return _serialize_saved(row)


@app.get("/api/saved-portfolios")
def api_list_saved_portfolios():
    try:
        rows = db.list_saved_portfolios()
    except db.DatabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return [_serialize_saved(r) for r in rows]


@app.delete("/api/saved-portfolios/{portfolio_id}")
def api_delete_saved_portfolio(portfolio_id: str):
    try:
        deleted = db.delete_saved_portfolio(portfolio_id)
    except db.DatabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved portfolio not found")
    return {"deleted": True}

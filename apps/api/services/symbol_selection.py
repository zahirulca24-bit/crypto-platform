"""
Symbol Selection Engine - Service Layer

Implements a deterministic, synchronous scan of public market data to select
the most suitable trading symbols based on configurable filters and a weighted
multi-metric scoring system.

Scoring formula (fixed server-controlled weights):
    score = 0.40 * norm_liquidity
          + 0.30 * (1 - norm_spread)
          + 0.20 * volatility_suitability
          + 0.10 * norm_activity

Where:
    norm_liquidity  = min-max scaled log10(quote_volume_24h) after winsorization
    norm_spread     = min-max scaled spread_pct after winsorization
    norm_activity   = 1.0 for all eligible (active) symbols
    volatility_suitability = clamp(
        1 - abs(norm_volatility - TARGET_VOLATILITY) / VOLATILITY_TOLERANCE,
        0.0, 1.0
    )

Normalization method:
    1. Winsorize each metric at the 1st and 99th percentiles (WINSOR_LOW / WINSOR_HIGH)
       across the entire eligible symbol set.
    2. Apply min-max scaling to [0, 1] on the winsorized values.
    3. Liquidity uses log10(quote_volume_24h) before winsorization/scaling.
    4. Volatility is the std-dev of log-returns of the last VOLATILITY_LOOKBACK
       closed OHLCV candles.

Ranking:
    - Highest score first.
    - Deterministic tie-breaker: symbol ascending.
    - Top max_symbols (default 10) are selected; the rest are rejected.

Both selected AND rejected symbols are persisted with full context.
"""

import math
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from exchange.adapter import CCXTMarketDataAdapter
from models import SymbolSelectionRun, SymbolSelectionResult
from packages.research.models import ObservationCreate
from packages.research.service import observe_best_effort
from schemas import (
    SymbolSelectionRequest,
    SymbolSelectionResponse,
    SymbolSelectionResultItem,
    SymbolMetrics,
    NormalizedMetrics,
    ScoreComponents,
)

logger = logging.getLogger(__name__)

# ── Server-controlled constants ────────────────────────────────────────────────
WEIGHTS: Dict[str, float] = {
    "liquidity": 0.40,
    "spread": 0.30,
    "volatility": 0.20,
    "activity": 0.10,
}
VOLATILITY_LOOKBACK: int = 20          # number of closed candles
TARGET_VOLATILITY: float = 0.50        # ideal normalised volatility (centre of bell)
VOLATILITY_TOLERANCE: float = 0.50    # half-width of acceptable range
WINSOR_LOW: float = 0.01              # 1st percentile
WINSOR_HIGH: float = 0.99             # 99th percentile
DEFAULT_MAX_SYMBOLS: int = 10

# Leveraged/tokenised token patterns (simple prefix/suffix heuristics)
_LEVERAGED_PATTERNS = ("3L", "3S", "5L", "5S", "2L", "2S", "BULL", "BEAR", "UP", "DOWN", "LEV", "SHORT", "LONG")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _is_leveraged(symbol: str) -> bool:
    base = symbol.split("/")[0].upper()
    return any(base.endswith(p) or base.startswith(p) for p in _LEVERAGED_PATTERNS)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_spread_pct(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid == 0:
        return None
    return (ask - bid) / mid * 100.0


def _compute_volatility(candles: List[Dict[str, Any]]) -> Optional[float]:
    """Standard deviation of log-returns from closed candles."""
    closes = []
    for c in candles:
        if c.get("is_closed", True):
            v = _safe_float(c.get("close"))
            if v and v > 0:
                closes.append(v)
    if len(closes) < 2:
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / n
    return math.sqrt(variance)


def _percentile(values: List[float], p: float) -> float:
    """Simple linear-interpolation percentile (p in [0,1])."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = p * (len(sorted_v) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_v) - 1)
    frac = idx - lo
    return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac


def _winsorize_and_scale(raw_values: List[Optional[float]]) -> List[Optional[float]]:
    """
    1. Compute 1st and 99th percentile across non-None values.
    2. Clip each value to [p1, p99].
    3. Min-max scale to [0, 1].
    Returns a parallel list; None inputs remain None.
    """
    non_null = [v for v in raw_values if v is not None]
    if len(non_null) < 2:
        return [0.0 if v is not None else None for v in raw_values]

    p_low = _percentile(non_null, WINSOR_LOW)
    p_high = _percentile(non_null, WINSOR_HIGH)
    clipped = [max(p_low, min(p_high, v)) if v is not None else None for v in raw_values]

    non_null_clipped = [v for v in clipped if v is not None]
    v_min = min(non_null_clipped)
    v_max = max(non_null_clipped)
    span = v_max - v_min

    def scale(v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if span == 0:
            return 0.0
        return (v - v_min) / span

    return [scale(v) for v in clipped]


def _volatility_suitability(norm_vol: Optional[float]) -> float:
    """
    Measures how close the normalised volatility is to the server-controlled target.

    volatility_suitability = clamp(
        1 - abs(norm_volatility - TARGET_VOLATILITY) / VOLATILITY_TOLERANCE,
        0.0, 1.0
    )
    """
    if norm_vol is None:
        return 0.0
    raw = 1.0 - abs(norm_vol - TARGET_VOLATILITY) / VOLATILITY_TOLERANCE
    return max(0.0, min(1.0, raw))


# ── Rejection reason constants ─────────────────────────────────────────────────
class RejectionReason:
    INACTIVE = "inactive_market"
    QUOTE_CURRENCY = "quote_currency_mismatch"
    MARKET_TYPE = "market_type_mismatch"
    LEVERAGED = "leveraged_token"
    EXCLUDED = "explicitly_excluded"
    NOT_INCLUDED = "not_in_include_list"
    LOW_VOLUME = "volume_below_minimum"
    HIGH_SPREAD = "spread_above_maximum"
    LOW_VOLATILITY = "volatility_below_minimum"
    HIGH_VOLATILITY = "volatility_above_maximum"
    MISSING_TICKER = "ticker_fetch_failed"
    MISSING_OHLCV = "ohlcv_fetch_failed"


# ── Main service ───────────────────────────────────────────────────────────────

def run_symbol_selection(
    request: SymbolSelectionRequest,
    db: Session,
    adapter: Optional[CCXTMarketDataAdapter] = None,
) -> SymbolSelectionResponse:
    """
    Execute one symbol-selection run synchronously.

    Steps:
      1. Fetch and filter markets.
      2. Fetch ticker + OHLCV for each eligible market; compute raw metrics.
      3. Normalise metrics (winsorization → min-max).
      4. Score with fixed weights.
      5. Rank (score desc, symbol asc).
      6. Persist run + all results (selected and rejected).
      7. Return response.
    """
    started_at = datetime.now(timezone.utc)

    if adapter is None:
        adapter = CCXTMarketDataAdapter(exchange_id=request.exchange)

    max_symbols = request.max_symbols if request.max_symbols is not None else DEFAULT_MAX_SYMBOLS

    # ── 1. Fetch all markets ────────────────────────────────────────────────
    try:
        all_markets = adapter.fetch_markets()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch markets: {exc}") from exc

    scanned_count = len(all_markets)

    # ── 2. Filter markets ───────────────────────────────────────────────────
    eligible: List[Dict[str, Any]] = []     # passed all static filters
    rejected_static: List[Tuple[str, List[str]]] = []  # (symbol, reasons)

    include_set = set(request.include_symbols or [])
    exclude_set = set(request.exclude_symbols or [])

    for market in all_markets:
        symbol: str = market["symbol"]
        reasons: List[str] = []

        if not market.get("active", True):
            reasons.append(RejectionReason.INACTIVE)
        if request.quote_currency and market.get("quote", "").upper() != request.quote_currency.upper():
            reasons.append(RejectionReason.QUOTE_CURRENCY)
        if request.market_type:
            mtype = market.get("type", "spot")
            if mtype != request.market_type:
                reasons.append(RejectionReason.MARKET_TYPE)
        if _is_leveraged(symbol):
            reasons.append(RejectionReason.LEVERAGED)
        if symbol in exclude_set:
            reasons.append(RejectionReason.EXCLUDED)
        if include_set and symbol not in include_set:
            reasons.append(RejectionReason.NOT_INCLUDED)

        if reasons:
            rejected_static.append((symbol, reasons))
        else:
            eligible.append(market)

    # ── 3. Fetch metrics for eligible markets ───────────────────────────────
    # (ticker + OHLCV raw metrics, then apply volume/spread/volatility filters)
    metric_rows: List[Dict[str, Any]] = []  # one per eligible market

    for market in eligible:
        symbol = market["symbol"]
        row: Dict[str, Any] = {"symbol": symbol, "rejection_reasons": []}

        # Ticker
        try:
            ticker = adapter.fetch_ticker(symbol)
        except Exception:
            row["rejection_reasons"].append(RejectionReason.MISSING_TICKER)
            metric_rows.append(row)
            continue

        last_price = _safe_float(ticker.get("last"))
        bid = _safe_float(ticker.get("bid"))
        ask = _safe_float(ticker.get("ask"))
        base_volume = _safe_float(ticker.get("volume"))          # base volume
        quote_volume = _safe_float(ticker.get("quoteVolume"))    # 24h quote volume

        spread_pct = _compute_spread_pct(bid, ask)

        # OHLCV for volatility
        try:
            candles = adapter.fetch_ohlcv(symbol, timeframe="1h", limit=VOLATILITY_LOOKBACK + 1)
        except Exception:
            row["rejection_reasons"].append(RejectionReason.MISSING_OHLCV)
            metric_rows.append(row)
            continue

        volatility = _compute_volatility(candles)
        percent_change = None
        if candles:
            first_open = _safe_float(candles[0].get("open"))
            if first_open and first_open > 0 and last_price:
                percent_change = (last_price - first_open) / first_open * 100.0

        row["raw_metrics"] = {
            "last_price": last_price,
            "bid": bid,
            "ask": ask,
            "spread_pct": spread_pct,
            "quote_volume_24h": quote_volume,
            "base_volume_24h": base_volume,
            "volatility": volatility,
            "percent_change": percent_change,
            "activity": 1.0,
        }

        # Volume filter
        if request.min_quote_volume is not None:
            if quote_volume is None or quote_volume < request.min_quote_volume:
                row["rejection_reasons"].append(RejectionReason.LOW_VOLUME)

        # Spread filter
        if request.max_spread_pct is not None:
            if spread_pct is None or spread_pct > request.max_spread_pct:
                row["rejection_reasons"].append(RejectionReason.HIGH_SPREAD)

        # Volatility filters
        if request.min_volatility is not None:
            if volatility is None or volatility < request.min_volatility:
                row["rejection_reasons"].append(RejectionReason.LOW_VOLATILITY)
        if request.max_volatility is not None:
            if volatility is not None and volatility > request.max_volatility:
                row["rejection_reasons"].append(RejectionReason.HIGH_VOLATILITY)

        metric_rows.append(row)

    # Separate metric_rows that passed all metric-level filters
    passed_rows = [r for r in metric_rows if not r["rejection_reasons"]]
    failed_rows = [r for r in metric_rows if r["rejection_reasons"]]

    eligible_count = len(passed_rows)

    # ── 4. Normalise metrics across the eligible set ────────────────────────
    def extract(field: str, use_log: bool = False) -> List[Optional[float]]:
        vals = []
        for r in passed_rows:
            v = r["raw_metrics"].get(field)
            if use_log and v is not None and v > 0:
                v = math.log10(v)
            elif use_log and (v is None or v <= 0):
                v = None
            vals.append(v)
        return vals

    raw_liquidity = extract("quote_volume_24h", use_log=True)
    raw_spread = extract("spread_pct")
    raw_volatility = extract("volatility")
    raw_activity = [1.0] * len(passed_rows)   # all eligible are active

    norm_liquidity = _winsorize_and_scale(raw_liquidity)
    norm_spread = _winsorize_and_scale(raw_spread)
    norm_volatility = _winsorize_and_scale(raw_volatility)
    norm_activity = _winsorize_and_scale(raw_activity)

    # ── 5. Score ────────────────────────────────────────────────────────────
    scored: List[Tuple[float, str, Dict]] = []
    for i, row in enumerate(passed_rows):
        nl = norm_liquidity[i] if norm_liquidity[i] is not None else 0.0
        ns = norm_spread[i] if norm_spread[i] is not None else 0.0
        nv = norm_volatility[i]
        na = norm_activity[i] if norm_activity[i] is not None else 1.0

        vs = _volatility_suitability(nv)

        score = (
            WEIGHTS["liquidity"] * nl
            + WEIGHTS["spread"] * (1.0 - ns)
            + WEIGHTS["volatility"] * vs
            + WEIGHTS["activity"] * na
        )

        row["norm_metrics"] = {
            "liquidity": nl,
            "spread": ns,
            "volatility": nv,
            "activity": na,
        }
        row["score_components"] = {
            "liquidity": WEIGHTS["liquidity"] * nl,
            "spread": WEIGHTS["spread"] * (1.0 - ns),
            "volatility": WEIGHTS["volatility"] * vs,
            "activity": WEIGHTS["activity"] * na,
            "volatility_suitability": vs,
        }
        row["score"] = score
        scored.append((score, row["symbol"], row))

    # ── 6. Rank (score desc, symbol asc for ties) ──────────────────────────
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected_symbols = [sym for _, sym, _ in scored[:max_symbols]]
    selected_set = set(selected_symbols)

    # Assign ranks and selection flags
    for rank_idx, (score, symbol, row) in enumerate(scored):
        row["selected"] = symbol in selected_set
        row["rank"] = rank_idx + 1 if row["selected"] else None

    selected_count = len(selected_symbols)
    rejected_count = (scanned_count - eligible_count) + len(failed_rows) + (eligible_count - selected_count)

    # ── 7. Build result objects ─────────────────────────────────────────────
    completed_at = datetime.now(timezone.utc)

    run_id = uuid.uuid4()
    configuration = {
        "exchange": request.exchange,
        "quote_currency": request.quote_currency,
        "market_type": request.market_type,
        "max_symbols": max_symbols,
        "min_quote_volume": request.min_quote_volume,
        "max_spread_pct": request.max_spread_pct,
        "min_volatility": request.min_volatility,
        "max_volatility": request.max_volatility,
        "include_symbols": request.include_symbols,
        "exclude_symbols": request.exclude_symbols,
        "weights": WEIGHTS,
        "lookback": VOLATILITY_LOOKBACK,
        "target_volatility": TARGET_VOLATILITY,
        "volatility_tolerance": VOLATILITY_TOLERANCE,
        "winsor_percentiles": {"low": WINSOR_LOW, "high": WINSOR_HIGH},
    }

    db_run = SymbolSelectionRun(
        id=run_id,
        exchange=request.exchange,
        configuration=configuration,
        weights=WEIGHTS,
        lookback=VOLATILITY_LOOKBACK,
        target_volatility=Decimal(str(TARGET_VOLATILITY)),
        volatility_tolerance=Decimal(str(VOLATILITY_TOLERANCE)),
        winsor_percentiles={"low": WINSOR_LOW, "high": WINSOR_HIGH},
        scanned_count=scanned_count,
        eligible_count=eligible_count,
        selected_count=selected_count,
        rejected_count=rejected_count,
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(db_run)
    db.flush()  # flush run to DB so FK constraint is satisfied before inserting results

    # Persist all symbol results
    all_result_items: List[SymbolSelectionResultItem] = []

    def _empty_norm() -> Dict[str, Optional[float]]:
        return {"liquidity": None, "spread": None, "volatility": None, "activity": None}

    def _empty_components() -> Dict[str, float]:
        return {"liquidity": 0.0, "spread": 0.0, "volatility": 0.0, "activity": 0.0, "volatility_suitability": 0.0}

    # Statically rejected (before ticker/ohlcv fetch)
    for sym, reasons in rejected_static:
        raw = {"last_price": None, "bid": None, "ask": None, "spread_pct": None,
               "quote_volume_24h": None, "base_volume_24h": None,
               "volatility": None, "percent_change": None, "activity": None}
        db.add(SymbolSelectionResult(
            run_id=run_id, symbol=sym, selected=False, rank=None, score=None,
            raw_metrics=raw, norm_metrics=_empty_norm(),
            score_components=_empty_components(), rejection_reasons=reasons,
        ))
        all_result_items.append(_make_item(sym, False, None, None, raw, _empty_norm(), _empty_components(), reasons))

    # Metric-level rejected (ticker/ohlcv fetched but failed filter)
    for row in failed_rows:
        sym = row["symbol"]
        raw = row.get("raw_metrics", {})
        reasons = row["rejection_reasons"]
        db.add(SymbolSelectionResult(
            run_id=run_id, symbol=sym, selected=False, rank=None, score=None,
            raw_metrics=raw, norm_metrics=_empty_norm(),
            score_components=_empty_components(), rejection_reasons=reasons,
        ))
        all_result_items.append(_make_item(sym, False, None, None, raw, _empty_norm(), _empty_components(), reasons))

    # Scored symbols (selected + ranked-out rejected)
    for score_val, sym, row in scored:
        sel = row["selected"]
        rank_val = row.get("rank")
        raw = row["raw_metrics"]
        norm = row["norm_metrics"]
        comp = row["score_components"]
        score_decimal = Decimal(str(round(score_val, 10))) if sel else None
        db.add(SymbolSelectionResult(
            run_id=run_id, symbol=sym, selected=sel, rank=rank_val,
            score=score_decimal,
            raw_metrics=raw, norm_metrics=norm, score_components=comp,
            rejection_reasons=[] if sel else ["ranked_below_max_symbols"],
        ))
        all_result_items.append(_make_item(
            sym, sel, rank_val,
            float(score_decimal) if score_decimal is not None else score_val,
            raw, norm, comp,
            [] if sel else ["ranked_below_max_symbols"],
        ))

    db.commit()

    # R&D observes the already-persisted authoritative selection results.
    for item in all_result_items:
        observe_best_effort(db, ObservationCreate(
            event_type="symbol.selected" if item.selected else "symbol.rejected",
            source="symbol_selection",
            exchange=request.exchange,
            symbol=item.symbol,
            timeframe="1h",
            price=Decimal(str(item.metrics.last_price)) if item.metrics.last_price is not None else None,
            volume=Decimal(str(item.metrics.quote_volume_24h)) if item.metrics.quote_volume_24h is not None else None,
            spread=Decimal(str(item.metrics.spread_pct)) if item.metrics.spread_pct is not None else None,
            volatility=Decimal(str(item.metrics.volatility)) if item.metrics.volatility is not None else None,
            selection_score=Decimal(str(item.score)) if item.score is not None else None,
            selection_status="selected" if item.selected else "rejected",
            selection_reasons=item.rejection_reasons,
            market_context={
                "selection_run_id": str(run_id),
                "raw_metrics": item.metrics.model_dump(mode="json"),
                "normalized_metrics": item.normalized_metrics.model_dump(mode="json"),
                "score_components": item.score_components.model_dump(mode="json"),
            },
        ))

    return SymbolSelectionResponse(
        run_id=str(run_id),
        exchange=request.exchange,
        scanned_count=scanned_count,
        eligible_count=eligible_count,
        selected_count=selected_count,
        rejected_count=rejected_count,
        selected_symbols=selected_symbols,
        results=all_result_items,
    )


def _make_item(
    symbol: str,
    selected: bool,
    rank: Optional[int],
    score: Optional[float],
    raw: Dict,
    norm: Dict,
    comp: Dict,
    reasons: List[str],
) -> SymbolSelectionResultItem:
    metrics = SymbolMetrics(
        last_price=raw.get("last_price"),
        bid=raw.get("bid"),
        ask=raw.get("ask"),
        spread_pct=raw.get("spread_pct"),
        quote_volume_24h=raw.get("quote_volume_24h"),
        base_volume_24h=raw.get("base_volume_24h"),
        volatility=raw.get("volatility"),
        percent_change=raw.get("percent_change"),
        activity=raw.get("activity"),
    )
    normalized = NormalizedMetrics(
        liquidity=norm.get("liquidity"),
        spread=norm.get("spread"),
        volatility=norm.get("volatility"),
        activity=norm.get("activity"),
    )
    components = ScoreComponents(
        liquidity=comp.get("liquidity", 0.0),
        spread=comp.get("spread", 0.0),
        volatility=comp.get("volatility", 0.0),
        activity=comp.get("activity", 0.0),
        volatility_suitability=comp.get("volatility_suitability", 0.0),
    )
    return SymbolSelectionResultItem(
        symbol=symbol,
        selected=selected,
        rank=rank,
        score=score,
        metrics=metrics,
        normalized_metrics=normalized,
        score_components=components,
        rejection_reasons=reasons,
    )


def get_run_by_id(run_id: str, db: Session) -> SymbolSelectionResponse:
    """Retrieve a persisted run and return the same response shape as the POST."""
    import uuid as uuid_mod
    try:
        run_uuid = uuid_mod.UUID(run_id)
    except ValueError:
        raise ValueError(f"Invalid run_id: {run_id}")

    db_run = db.query(SymbolSelectionRun).filter(SymbolSelectionRun.id == run_uuid).first()
    if not db_run:
        raise LookupError(f"Run {run_id} not found")

    db_results = (
        db.query(SymbolSelectionResult)
        .filter(SymbolSelectionResult.run_id == run_uuid)
        .all()
    )

    selected_symbols = sorted(
        [r.symbol for r in db_results if r.selected],
        key=lambda sym: (db_results[[r.symbol for r in db_results].index(sym)].rank or 99999),
    )

    all_items = []
    for r in db_results:
        all_items.append(_make_item(
            r.symbol, r.selected, r.rank,
            float(r.score) if r.score is not None else None,
            r.raw_metrics, r.norm_metrics, r.score_components,
            r.rejection_reasons or [],
        ))

    return SymbolSelectionResponse(
        run_id=str(db_run.id),
        exchange=db_run.exchange,
        scanned_count=db_run.scanned_count,
        eligible_count=db_run.eligible_count,
        selected_count=db_run.selected_count,
        rejected_count=db_run.rejected_count,
        selected_symbols=selected_symbols,
        results=all_items,
    )

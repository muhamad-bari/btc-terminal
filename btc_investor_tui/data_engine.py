"""Data aggregation layer for a standalone BTC long-term investor TUI.

This module intentionally avoids MCP, OpenClaw, JSON-RPC, and AI prompt code.
It prepares plain Python payloads that the Textual UI can render.
"""

from __future__ import annotations

import math
import importlib
import logging
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.volatility import BollingerBands

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    _LOGGER.addHandler(logging.NullHandler())
_LOGGER.setLevel(logging.DEBUG)
_LOGGER.propagate = False

_T = TypeVar("_T")

_bitcoin_market_service = importlib.import_module("tradingview_mcp.core.services.bitcoin_market_service")
_news_service = importlib.import_module("tradingview_mcp.core.services.news_service")
_sentiment_service = importlib.import_module("tradingview_mcp.core.services.sentiment_service")
_yahoo_finance_service = importlib.import_module("tradingview_mcp.core.services.yahoo_finance_service")

get_bitcoin_market_pulse = cast(Callable[[], dict[str, Any]], _bitcoin_market_service.get_bitcoin_market_pulse)
RSS_FEEDS = cast(dict[str, list[dict[str, str]]], _news_service.RSS_FEEDS)
fetch_news_summary = cast(Callable[..., dict[str, Any]], _news_service.fetch_news_summary)
analyze_sentiment = cast(Callable[..., dict[str, Any]], _sentiment_service.analyze_sentiment)
get_price = cast(Callable[[str], dict[str, Any]], _yahoo_finance_service.get_price)

BTC_SYMBOL = "BTC-USDT"
_YAHOO_SYMBOL = "BTC-USD"  # Yahoo Finance uses BTC-USD; we display as BTC-USDT
DEFAULT_DAILY_PERIOD = "2y"
DEFAULT_WEEKLY_PERIOD = "5y"
DEFAULT_DAILY_INTERVAL = "1d"
DEFAULT_WEEKLY_INTERVAL = "1wk"
DEFAULT_ORDER_BLOCK_PIVOT_LEFT = 2
DEFAULT_ORDER_BLOCK_PIVOT_RIGHT = 2
DEFAULT_ORDER_BLOCK_LIMIT = 8
DEFAULT_ORDER_BLOCK_IMPULSE_LOOKBACK = 20
DEFAULT_ORDER_BLOCK_ORIGIN_LOOKBACK = 6

_NEWS_USER_AGENT = (
    "Mozilla/5.0 (compatible; btc-investor-tui/0.1; "
    "+https://github.com/atilaahmettaner/tradingview-mcp)"
)


def get_btc_candles(
    period: str = DEFAULT_WEEKLY_PERIOD,
    interval: str = DEFAULT_WEEKLY_INTERVAL,
    symbol: str = _YAHOO_SYMBOL,
) -> list[dict[str, Any]]:
    """Fetch normalized Yahoo Finance OHLCV candles for BTC.

    Supported intervals are whatever Yahoo Finance exposes through yfinance,
    including the long-term investor defaults `1wk` and `1d`.
    """
    history = yf.Ticker(symbol).history(
        period=period,
        interval=interval,
        auto_adjust=False,
        actions=False,
        repair=False,
    )
    if history.empty:
        raise RuntimeError(f"No Yahoo Finance candles returned for {symbol} {period}/{interval}")

    frame = _normalize_history_frame(history)
    candles: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        open_price = _finite_float(row.get("Open"))
        high_price = _finite_float(row.get("High"))
        low_price = _finite_float(row.get("Low"))
        close_price = _finite_float(row.get("Close"))
        if open_price is None or high_price is None or low_price is None or close_price is None:
            continue

        date = pd.Timestamp(cast(Any, index))
        if not isinstance(date, pd.Timestamp):
            continue
        if date.tzinfo is not None:
            date = date.tz_convert("UTC")
        candles.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": _round_price(open_price),
                "high": _round_price(high_price),
                "low": _round_price(low_price),
                "close": _round_price(close_price),
                "volume": _int_volume(row.get("Volume", 0)),
            }
        )

    if not candles:
        raise RuntimeError(f"Yahoo Finance candles for {symbol} contained no valid OHLC rows")
    return candles


def get_btc_quote(symbol: str = _YAHOO_SYMBOL) -> dict[str, Any]:
    """Return the current BTC quote using the repository's Yahoo service."""
    quote = get_price(symbol)
    if "error" in quote:
        fallback = _quote_from_yfinance(symbol)
        return {**fallback, "fallback_reason": quote["error"]}
    return quote


def build_btc_technical_snapshot(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a TUI-ready technical snapshot from normalized BTC candles."""
    if len(candles) < 60:
        raise ValueError("At least 60 candles are required for BTC technical snapshot")

    frame = pd.DataFrame(candles)
    closes = cast(pd.Series, pd.to_numeric(frame["close"], errors="coerce"))
    highs = cast(pd.Series, pd.to_numeric(frame["high"], errors="coerce"))
    lows = cast(pd.Series, pd.to_numeric(frame["low"], errors="coerce"))

    indicators = _calculate_indicators(closes, highs, lows)
    latest_close = _finite_float(closes.iloc[-1])
    if latest_close is None:
        raise ValueError("Latest BTC close is missing")

    sma_50 = _last_valid(indicators["sma_50"])
    sma_200 = _last_valid(indicators["sma_200"])
    ema_20 = _last_valid(indicators["ema_20"])
    ema_50 = _last_valid(indicators["ema_50"])
    rsi_14 = _last_valid(indicators["rsi_14"])
    macd = _last_valid(indicators["macd"])
    macd_signal = _last_valid(indicators["macd_signal"])
    macd_histogram = _last_valid(indicators["macd_histogram"])
    bb_upper = _last_valid(indicators["bb_upper"])
    bb_middle = _last_valid(indicators["bb_middle"])
    bb_lower = _last_valid(indicators["bb_lower"])

    previous_close = _finite_float(closes.iloc[-2]) if len(closes) > 1 else None
    weekly_change_pct = _pct_change(latest_close, previous_close)
    high_52 = _rolling_window_extreme(highs, len(candles), max_points=52, mode="max")
    low_52 = _rolling_window_extreme(lows, len(candles), max_points=52, mode="min")

    trend_label = _classify_trend(latest_close, sma_50, sma_200)
    risk_label = _classify_risk(latest_close, sma_200, rsi_14)
    composite = _composite_signal(
        close=latest_close,
        ema_20=ema_20,
        ema_50=ema_50,
        sma_50=sma_50,
        sma_200=sma_200,
        rsi_14=rsi_14,
        macd=macd,
        macd_signal=macd_signal,
    )

    return {
        "symbol": BTC_SYMBOL,
        "timeframe": _infer_timeframe(candles),
        "last_date": candles[-1]["date"],
        "latest_close": _round_price(latest_close),
        "weekly_change_pct": weekly_change_pct,
        "moving_averages": {
            "ema_20": _round_optional(ema_20),
            "ema_50": _round_optional(ema_50),
            "sma_50": _round_optional(sma_50),
            "sma_200": _round_optional(sma_200),
        },
        "oscillators": {
            "rsi_14": _round_optional(rsi_14, digits=2),
            "macd": _round_optional(macd, digits=4),
            "macd_signal": _round_optional(macd_signal, digits=4),
            "macd_histogram": _round_optional(macd_histogram, digits=4),
        },
        "bollinger_bands": {
            "upper": _round_optional(bb_upper),
            "middle": _round_optional(bb_middle),
            "lower": _round_optional(bb_lower),
        },
        "range": {
            "high_52_periods": _round_optional(high_52),
            "low_52_periods": _round_optional(low_52),
            "distance_from_52_high_pct": _pct_change(latest_close, high_52),
            "distance_from_52_low_pct": _pct_change(latest_close, low_52),
        },
        "trend_label": trend_label,
        "risk_label": risk_label,
        "composite_signal": composite,
        "indicator_series": {
            "ema_20": _series_to_optional_list(indicators["ema_20"]),
            "ema_50": _series_to_optional_list(indicators["ema_50"]),
            "rsi_14": _series_to_optional_list(indicators["rsi_14"], digits=2),
            "macd": _series_to_optional_list(indicators["macd"], digits=4),
            "macd_signal": _series_to_optional_list(indicators["macd_signal"], digits=4),
            "macd_histogram": _series_to_optional_list(indicators["macd_histogram"], digits=4),
            "stoch_k": _series_to_optional_list(indicators.get("stoch_k", pd.Series()), digits=2),
            "stoch_d": _series_to_optional_list(indicators.get("stoch_d", pd.Series()), digits=2),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def recalculate_indicators(
    candles: list[dict[str, Any]],
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    stoch_k: int = 5,
    stoch_d: int = 3,
    stoch_smooth: int = 3,
) -> dict[str, Any]:
    """Recalculate indicator series from cached candles with custom params.

    No network calls — purely CPU computation for instant re-render.
    """
    if len(candles) < 60:
        return {}
    frame = pd.DataFrame(candles)
    closes = cast(pd.Series, pd.to_numeric(frame["close"], errors="coerce"))
    highs = cast(pd.Series, pd.to_numeric(frame["high"], errors="coerce"))
    lows = cast(pd.Series, pd.to_numeric(frame["low"], errors="coerce"))
    indicators = calculate_dynamic_indicators(
        closes, ema_fast, ema_slow, rsi_period, macd_fast, macd_slow, macd_signal,
        stoch_k, stoch_d, stoch_smooth, highs, lows,
    )
    return {
        "ema_20": _series_to_optional_list(indicators["ema_20"]),
        "ema_50": _series_to_optional_list(indicators["ema_50"]),
        "rsi_14": _series_to_optional_list(indicators["rsi_14"], digits=2),
        "macd": _series_to_optional_list(indicators["macd"], digits=4),
        "macd_signal": _series_to_optional_list(indicators["macd_signal"], digits=4),
        "macd_histogram": _series_to_optional_list(indicators["macd_histogram"], digits=4),
        "stoch_k": _series_to_optional_list(indicators.get("stoch_k", pd.Series()), digits=2),
        "stoch_d": _series_to_optional_list(indicators.get("stoch_d", pd.Series()), digits=2),
    }


def detect_order_blocks(
    candles: list[dict[str, Any]],
    *,
    pivot_left: int = DEFAULT_ORDER_BLOCK_PIVOT_LEFT,
    pivot_right: int = DEFAULT_ORDER_BLOCK_PIVOT_RIGHT,
    mitigation: str = "wick",
    max_blocks: int = DEFAULT_ORDER_BLOCK_LIMIT,
) -> dict[str, Any]:
    """Detect order blocks using Smart Money Concepts (structure-based, LuxAlgo-style).

    Uses swing highs/lows to identify market structure breaks, then marks the
    candle before the break as an order block. This avoids false OBs at irrelevant
    historical price levels.
    """
    if len(candles) < 20:
        return _order_block_payload([], mitigation=mitigation, pivot_left=pivot_left, pivot_right=pivot_right, max_blocks=max_blocks)

    try:
        from smartmoneyconcepts.smc import smc as _smc

        ohlc = pd.DataFrame({
            "open": [c["open"] for c in candles],
            "high": [c["high"] for c in candles],
            "low": [c["low"] for c in candles],
            "close": [c["close"] for c in candles],
            "volume": [c.get("volume", 0) for c in candles],
        })
        # swing_length=7 gives a good balance for weekly/daily BTC charts
        swing_length = max(5, min(10, len(candles) // 15))
        swing_hl = _smc.swing_highs_lows(ohlc, swing_length=swing_length)
        close_mit = mitigation == "close"
        ob_result = _smc.ob(ohlc, swing_hl, close_mitigation=close_mit)

        blocks: list[dict[str, Any]] = []
        valid = ob_result.dropna(subset=["OB"])
        current_price = float(ohlc["close"].iloc[-1])
        for idx, row in valid.iterrows():
            ob_type = "bullish" if row["OB"] == 1 else "bearish"
            mit_idx = row.get("MitigatedIndex", 0)
            mitigated = not pd.isna(mit_idx) and mit_idx > 0
            # Skip unmitigated OBs too far from current price (>50% away)
            if not mitigated:
                ob_mid = (row["Top"] + row["Bottom"]) / 2
                distance_pct = abs(ob_mid - current_price) / current_price
                if distance_pct > 0.50:
                    continue
            origin_index = int(idx)
            blocks.append({
                "type": ob_type,
                "price_low": _round_price(row["Bottom"]),
                "price_high": _round_price(row["Top"]),
                "origin_index": origin_index,
                "origin_date": str(candles[origin_index].get("date", "")),
                "created_index": origin_index + 1,
                "created_date": str(candles[min(origin_index + 1, len(candles) - 1)].get("date", "")),
                "volume": int(row.get("OBVolume", 0) or 0),
                "mitigated": mitigated,
                "mitigated_index": int(mit_idx) if mitigated else None,
                "mitigated_date": str(candles[int(mit_idx)].get("date", "")) if mitigated and int(mit_idx) < len(candles) else None,
                "mitigation_mode": mitigation,
                "label": f"{'Demand' if ob_type == 'bullish' else 'Supply'} OB (SMC structure)",
            })
        return _order_block_payload(blocks, mitigation=mitigation, pivot_left=pivot_left, pivot_right=pivot_right, max_blocks=max_blocks)
    except Exception as exc:
        _LOGGER.warning("SMC order block detection failed, returning empty: %s", exc)
        return _order_block_payload([], mitigation=mitigation, pivot_left=pivot_left, pivot_right=pivot_right, max_blocks=max_blocks)


def get_btc_news(limit: int = 12) -> dict[str, Any]:
    """Return BTC-focused crypto/macro RSS news with a stdlib fallback parser."""
    primary = fetch_news_summary(symbol="BTC", category="all", limit=limit)
    items = primary.get("items", []) if isinstance(primary, dict) else []
    has_error = bool(items and isinstance(items[0], dict) and "error" in items[0])
    if items and not has_error:
        return {**primary, "source_mode": "tradingview_mcp.news_service"}

    fallback_items = _fetch_rss_news_fallback(limit=limit)
    return {
        "symbol": "BTC",
        "category": "all",
        "count": len(fallback_items),
        "feedparser_available": False,
        "source_mode": "stdlib_xml_fallback",
        "items": fallback_items,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_btc_reddit_sentiment(limit: int = 30) -> dict[str, Any]:
    """Return Reddit BTC sentiment using the repository's sentiment service."""
    return analyze_sentiment("BTC", category="crypto", limit=limit)


def get_btc_macro_pulse() -> dict[str, Any]:
    """Return CoinGecko BTC dominance and crypto-market macro context."""
    return get_bitcoin_market_pulse()


def _safe_fetch(
    name: str,
    fetch: Callable[[], _T],
    *,
    fallback: Callable[[str], _T],
    errors: dict[str, str],
) -> _T:
    try:
        return fetch()
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        errors[name] = message
        _LOGGER.exception("Optional BTC dashboard fetch failed: %s", name)
        return fallback(message)


def get_btc_dashboard_data(
    weekly_period: str = DEFAULT_WEEKLY_PERIOD,
    daily_period: str = DEFAULT_DAILY_PERIOD,
    news_limit: int = 12,
    sentiment_limit: int = 30,
) -> dict[str, Any]:
    """Aggregate all data needed by the Textual investor dashboard."""
    optional_errors: dict[str, str] = {}
    try:
        weekly_candles = get_btc_candles(period=weekly_period, interval=DEFAULT_WEEKLY_INTERVAL)
        daily_candles = get_btc_candles(period=daily_period, interval=DEFAULT_DAILY_INTERVAL)
        weekly_technical = build_btc_technical_snapshot(weekly_candles)
        daily_technical = build_btc_technical_snapshot(daily_candles)
        weekly_order_blocks = detect_order_blocks(weekly_candles)
        daily_order_blocks = detect_order_blocks(daily_candles)

        quote = _safe_fetch(
            "quote",
            get_btc_quote,
            fallback=lambda error: _quote_from_candles(daily_candles, error),
            errors=optional_errors,
        )
        news = _safe_fetch(
            "rss_news",
            lambda: get_btc_news(limit=news_limit),
            fallback=lambda error: _empty_news(error),
            errors=optional_errors,
        )
        reddit_sentiment = _safe_fetch(
            "reddit_sentiment",
            lambda: get_btc_reddit_sentiment(limit=sentiment_limit),
            fallback=lambda error: _empty_reddit_sentiment(error),
            errors=optional_errors,
        )
        macro_pulse = _safe_fetch(
            "macro_pulse",
            get_btc_macro_pulse,
            fallback=lambda error: _empty_macro_pulse(error),
            errors=optional_errors,
        )

        return {
            "symbol": BTC_SYMBOL,
            "asset_name": "Bitcoin",
            "default_timeframes": {"primary": "1W", "secondary": "1D"},
            "quote": quote,
            "market_summary": _build_market_summary(quote, weekly_technical),
            "weekly": {"candles": weekly_candles, "technical": weekly_technical, "order_blocks": weekly_order_blocks},
            "daily": {"candles": daily_candles, "technical": daily_technical, "order_blocks": daily_order_blocks},
            "news": news,
            "reddit_sentiment": reddit_sentiment,
            "macro_pulse": macro_pulse,
            "errors": optional_errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        _LOGGER.exception("Fatal BTC dashboard data fetch failed")
        raise


def _normalize_history_frame(history: pd.DataFrame) -> pd.DataFrame:
    frame = history.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    expected = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in expected if column not in frame.columns]
    if missing:
        raise RuntimeError(f"Yahoo Finance response missing columns: {', '.join(missing)}")
    return frame.loc[:, expected].dropna(subset=["Open", "High", "Low", "Close"])


def _calculate_indicators(closes: pd.Series, highs: pd.Series | None = None, lows: pd.Series | None = None) -> dict[str, pd.Series]:
    return calculate_dynamic_indicators(closes, highs=highs, lows=lows)


def calculate_dynamic_indicators(
    closes: pd.Series,
    ema_fast: int = 20,
    ema_slow: int = 50,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    stoch_k: int = 5,
    stoch_d: int = 3,
    stoch_smooth: int = 3,
    highs: pd.Series | None = None,
    lows: pd.Series | None = None,
) -> dict[str, pd.Series]:
    """Calculate indicators with user-configurable parameters."""
    from ta.momentum import StochasticOscillator
    result = {
        "ema_20": EMAIndicator(close=closes, window=ema_fast).ema_indicator(),
        "ema_50": EMAIndicator(close=closes, window=ema_slow).ema_indicator(),
        "sma_50": SMAIndicator(close=closes, window=50).sma_indicator(),
        "sma_200": SMAIndicator(close=closes, window=200).sma_indicator(),
        "rsi_14": RSIIndicator(close=closes, window=rsi_period).rsi(),
        "bb_upper": BollingerBands(close=closes, window=20, window_dev=2).bollinger_hband(),
        "bb_middle": BollingerBands(close=closes, window=20, window_dev=2).bollinger_mavg(),
        "bb_lower": BollingerBands(close=closes, window=20, window_dev=2).bollinger_lband(),
        "macd": MACD(close=closes, window_slow=macd_slow, window_fast=macd_fast, window_sign=macd_signal).macd(),
        "macd_signal": MACD(close=closes, window_slow=macd_slow, window_fast=macd_fast, window_sign=macd_signal).macd_signal(),
        "macd_histogram": MACD(close=closes, window_slow=macd_slow, window_fast=macd_fast, window_sign=macd_signal).macd_diff(),
    }
    # Stochastic requires high/low
    if highs is not None and lows is not None:
        stoch = StochasticOscillator(high=highs, low=lows, close=closes, window=stoch_k, smooth_window=stoch_smooth)
        result["stoch_k"] = stoch.stoch()
        result["stoch_d"] = stoch.stoch_signal()
    return result


def _normalized_order_block_candle(candle: dict[str, Any], index: int) -> dict[str, Any] | None:
    open_price = _finite_float(candle.get("open"))
    high_price = _finite_float(candle.get("high"))
    low_price = _finite_float(candle.get("low"))
    close_price = _finite_float(candle.get("close"))
    volume = _finite_float(candle.get("volume"))
    if open_price is None or high_price is None or low_price is None or close_price is None:
        return None
    if high_price < low_price:
        return None
    return {
        "index": index,
        "date": str(candle.get("date", "")),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume or 0.0,
    }


def _is_impulsive_move(candles: list[dict[str, Any]], index: int) -> bool:
    current = _normalized_order_block_candle(candles[index], index)
    if current is None or current["close"] == current["open"]:
        return False

    start = max(0, index - DEFAULT_ORDER_BLOCK_IMPULSE_LOOKBACK)
    prior = [_normalized_order_block_candle(candles[i], i) for i in range(start, index)]
    prior = [candle for candle in prior if candle is not None]
    if len(prior) < 3:
        return False

    body = abs(current["close"] - current["open"])
    candle_range = current["high"] - current["low"]
    if candle_range <= 0:
        return False

    bodies = [abs(candle["close"] - candle["open"]) for candle in prior]
    ranges = [candle["high"] - candle["low"] for candle in prior if candle["high"] > candle["low"]]
    avg_body = sum(bodies) / len(bodies) if bodies else 0
    avg_range = sum(ranges) / len(ranges) if ranges else 0
    if avg_body <= 0 or avg_range <= 0:
        return False

    body_ratio = body / candle_range
    strong_body = body >= avg_body * 1.8
    wide_range = candle_range >= avg_range * 1.15
    previous_high = max(candle["high"] for candle in prior[-5:])
    previous_low = min(candle["low"] for candle in prior[-5:])

    if current["close"] > current["open"]:
        closes_near_extreme = (current["high"] - current["close"]) / candle_range <= 0.35
        breaks_structure = current["close"] > previous_high
        return strong_body and closes_near_extreme and (wide_range or breaks_structure or body_ratio >= 0.7)

    closes_near_extreme = (current["close"] - current["low"]) / candle_range <= 0.35
    breaks_structure = current["close"] < previous_low
    return strong_body and closes_near_extreme and (wide_range or breaks_structure or body_ratio >= 0.7)


def _find_last_opposite_candle(candles: list[dict[str, Any]], impulse_index: int, impulse_type: str) -> int | None:
    start = max(0, impulse_index - DEFAULT_ORDER_BLOCK_ORIGIN_LOOKBACK)
    for index in range(impulse_index - 1, start - 1, -1):
        candle = _normalized_order_block_candle(candles[index], index)
        if candle is None or candle["close"] == candle["open"]:
            continue
        if impulse_type == "bullish" and candle["close"] < candle["open"]:
            return index
        if impulse_type == "bearish" and candle["close"] > candle["open"]:
            return index
    return None


def _build_impulsive_order_block(
    candles: list[dict[str, Any]],
    origin: dict[str, Any],
    impulse: dict[str, Any],
    block_type: str,
    mitigation: str,
) -> dict[str, Any]:
    price_low = origin["low"]
    price_high = origin["high"]
    label = "Bullish impulsive-move demand block" if block_type == "bullish" else "Bearish impulsive-move supply block"
    mitigated_index = _find_mitigation_index(candles, impulse["index"] + 1, block_type, price_low, price_high, mitigation)
    return {
        "type": block_type,
        "price_low": _round_price(price_low),
        "price_high": _round_price(price_high),
        "origin_index": origin["index"],
        "origin_date": origin["date"],
        "created_index": impulse["index"],
        "created_date": impulse["date"],
        "volume": int(origin["volume"]),
        "mitigated": mitigated_index is not None,
        "mitigated_index": mitigated_index,
        "mitigated_date": str(candles[mitigated_index].get("date", "")) if mitigated_index is not None else None,
        "mitigation_mode": mitigation,
        "detector": "impulsive_move",
        "impulse_index": impulse["index"],
        "impulse_date": impulse["date"],
        "impulse_close": _round_price(impulse["close"]),
        "label": label,
    }


def _is_volume_pivot(candles: list[dict[str, Any]], index: int, left: int, right: int) -> bool:
    pivot_volume = _finite_float(candles[index].get("volume"))
    if pivot_volume is None or pivot_volume <= 0:
        return False
    start = index - left
    end = index + right + 1
    for other_index in range(start, end):
        if other_index == index:
            continue
        other_volume = _finite_float(candles[other_index].get("volume"))
        if other_volume is not None and other_volume >= pivot_volume:
            return False
    return True


def _find_bullish_confirmation(candles: list[dict[str, Any]], index: int, pivot_right: int) -> int | None:
    pivot_high = _finite_float(candles[index].get("high"))
    if pivot_high is None:
        return None
    end = min(len(candles), index + pivot_right + 4)
    for confirm_index in range(index + 1, end):
        close_price = _finite_float(candles[confirm_index].get("close"))
        if close_price is not None and close_price > pivot_high:
            return confirm_index
    return None


def _find_bearish_confirmation(candles: list[dict[str, Any]], index: int, pivot_right: int) -> int | None:
    pivot_low = _finite_float(candles[index].get("low"))
    if pivot_low is None:
        return None
    end = min(len(candles), index + pivot_right + 4)
    for confirm_index in range(index + 1, end):
        close_price = _finite_float(candles[confirm_index].get("close"))
        if close_price is not None and close_price < pivot_low:
            return confirm_index
    return None


def _build_order_block(
    candles: list[dict[str, Any]],
    pivot: dict[str, Any],
    confirmation_index: int,
    block_type: str,
    mitigation: str,
) -> dict[str, Any]:
    if block_type == "bullish":
        price_low = min(pivot["low"], pivot["open"], pivot["close"])
        price_high = max(pivot["open"], pivot["close"])
        label = "Bullish volume-pivot demand block"
    else:
        price_low = min(pivot["open"], pivot["close"])
        price_high = max(pivot["high"], pivot["open"], pivot["close"])
        label = "Bearish volume-pivot supply block"

    mitigated_index = _find_mitigation_index(candles, confirmation_index + 1, block_type, price_low, price_high, mitigation)
    return {
        "type": block_type,
        "price_low": _round_price(price_low),
        "price_high": _round_price(price_high),
        "origin_index": pivot["index"],
        "origin_date": pivot["date"],
        "created_index": confirmation_index,
        "created_date": str(candles[confirmation_index].get("date", "")),
        "volume": int(pivot["volume"]),
        "mitigated": mitigated_index is not None,
        "mitigated_index": mitigated_index,
        "mitigated_date": str(candles[mitigated_index].get("date", "")) if mitigated_index is not None else None,
        "mitigation_mode": mitigation,
        "label": label,
    }


def _find_mitigation_index(
    candles: list[dict[str, Any]],
    start_index: int,
    block_type: str,
    price_low: float,
    price_high: float,
    mitigation: str,
) -> int | None:
    for index in range(start_index, len(candles)):
        candle = candles[index]
        high_price = _finite_float(candle.get("high"))
        low_price = _finite_float(candle.get("low"))
        close_price = _finite_float(candle.get("close"))
        if block_type == "bullish":
            test_price = close_price if mitigation == "close" else low_price
            if test_price is not None and test_price < price_low:
                return index
        else:
            test_price = close_price if mitigation == "close" else high_price
            if test_price is not None and test_price >= price_low:
                return index
    return None


def _order_block_payload(
    blocks: list[dict[str, Any]],
    *,
    mitigation: str,
    pivot_left: int,
    pivot_right: int,
    max_blocks: int,
) -> dict[str, Any]:
    recent = sorted(blocks, key=lambda block: int(block.get("origin_index", 0)), reverse=True)
    unmitigated = [block for block in recent if not block.get("mitigated")]
    bullish = [block for block in recent if block.get("type") == "bullish"]
    bearish = [block for block in recent if block.get("type") == "bearish"]
    return {
        "detector": "smc_structure",
        "mitigation_mode": mitigation,
        "pivot_left": pivot_left,
        "pivot_right": pivot_right,
        "bullish": bullish[:max_blocks],
        "bearish": bearish[:max_blocks],
        "recent": recent[:max_blocks],
        "unmitigated": unmitigated[:max_blocks],
    }


def _build_market_summary(quote: dict[str, Any], weekly_technical: dict[str, Any]) -> dict[str, Any]:
    return {
        "price": quote.get("price") or weekly_technical["latest_close"],
        "currency": quote.get("currency", "USD"),
        "weekly_change_pct": weekly_technical.get("weekly_change_pct"),
        "trend_label": weekly_technical.get("trend_label"),
        "risk_label": weekly_technical.get("risk_label"),
        "composite_signal": weekly_technical.get("composite_signal"),
        "market_state": quote.get("market_state"),
        "source": quote.get("source", "Yahoo Finance"),
    }


def _quote_from_candles(candles: list[dict[str, Any]], error: str) -> dict[str, Any]:
    latest = candles[-1]
    previous = candles[-2] if len(candles) > 1 else latest
    latest_close = _finite_float(latest.get("close"))
    previous_close = _finite_float(previous.get("close"))
    return {
        "symbol": BTC_SYMBOL,
        "price": _round_optional(latest_close),
        "previous_close": _round_optional(previous_close),
        "change": _round_optional(latest_close - previous_close) if latest_close is not None and previous_close is not None else None,
        "change_pct": _pct_change(latest_close, previous_close),
        "currency": "USD",
        "exchange": "Yahoo Finance",
        "market_state": None,
        "52w_high": None,
        "52w_low": None,
        "source": "yfinance candles fallback",
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _empty_news(error: str) -> dict[str, Any]:
    return {
        "symbol": "BTC",
        "category": "all",
        "count": 0,
        "source_mode": "unavailable",
        "items": [],
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _empty_reddit_sentiment(error: str) -> dict[str, Any]:
    return {
        "symbol": "BTC",
        "category": "crypto",
        "sentiment_label": "unavailable",
        "sentiment_score": None,
        "posts_analyzed": 0,
        "top_posts": [],
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _empty_macro_pulse(error: str) -> dict[str, Any]:
    return {
        "source": "CoinGecko",
        "tool": "bitcoin_market_pulse",
        "error": error,
        "assessment": {
            "label": "UNAVAILABLE",
            "summary": "BTC macro pulse unavailable; price and technical dashboard data still loaded.",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_rss_news_fallback(limit: int) -> list[dict[str, Any]]:
    feeds = RSS_FEEDS.get("all", [])
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feed in feeds:
        if len(items) >= limit:
            break
        for item in _read_rss_feed(feed["url"], feed["name"]):
            key = item.get("url") or item.get("title", "")
            if key in seen:
                continue
            text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
            if not any(term in text for term in ("btc", "bitcoin", "crypto", "fed", "inflation", "dollar", "rates")):
                continue
            seen.add(key)
            items.append(item)
            if len(items) >= limit:
                break
    return items


def _read_rss_feed(url: str, fallback_source: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": _NEWS_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read()
    except Exception:
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    channel_title = _xml_text(root.find("./channel/title")) or fallback_source
    entries = root.findall("./channel/item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    parsed: list[dict[str, Any]] = []
    for entry in entries:
        title = _xml_text(entry.find("title")) or _xml_text(entry.find("{http://www.w3.org/2005/Atom}title"))
        link = _xml_text(entry.find("link")) or _atom_link(entry)
        summary = (
            _xml_text(entry.find("description"))
            or _xml_text(entry.find("summary"))
            or _xml_text(entry.find("{http://www.w3.org/2005/Atom}summary"))
        )
        published = _xml_text(entry.find("pubDate")) or _xml_text(entry.find("{http://www.w3.org/2005/Atom}updated"))
        if title:
            parsed.append(
                {
                    "title": _clean_text(title),
                    "url": link,
                    "published": _normalize_pubdate(published),
                    "summary": _clean_text(summary)[:300],
                    "source": channel_title,
                }
            )
    return parsed


def _quote_from_yfinance(symbol: str) -> dict[str, Any]:
    candles = get_btc_candles(period="5d", interval="1d", symbol=symbol)
    latest = candles[-1]
    previous = candles[-2] if len(candles) > 1 else latest
    return {
        "symbol": symbol.upper(),
        "price": latest["close"],
        "previous_close": previous["close"],
        "change": _round_optional(latest["close"] - previous["close"]),
        "change_pct": _pct_change(latest["close"], previous["close"]),
        "currency": "USD",
        "exchange": "Yahoo Finance",
        "market_state": None,
        "52w_high": None,
        "52w_low": None,
        "source": "yfinance history fallback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _classify_trend(close: float, sma_50: float | None, sma_200: float | None) -> str:
    if sma_50 is None or sma_200 is None:
        return "INSUFFICIENT_HISTORY"
    if close > sma_200 and sma_50 > sma_200:
        return "LONG_TERM_BULLISH"
    if close < sma_200 and sma_50 < sma_200:
        return "LONG_TERM_BEARISH"
    return "NEUTRAL"


def _classify_risk(close: float, sma_200: float | None, rsi_14: float | None) -> str:
    if rsi_14 is not None and rsi_14 >= 70:
        return "OVERHEATED"
    if sma_200 is not None and close < sma_200:
        return "BREAKDOWN_RISK"
    if rsi_14 is not None and sma_200 is not None and rsi_14 <= 40 and close >= sma_200:
        return "ACCUMULATION_ZONE"
    return "NORMAL"


def _composite_signal(
    *,
    close: float,
    ema_20: float | None,
    ema_50: float | None,
    sma_50: float | None,
    sma_200: float | None,
    rsi_14: float | None,
    macd: float | None,
    macd_signal: float | None,
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []

    if ema_20 is not None and ema_50 is not None:
        if ema_20 > ema_50:
            score += 1
            reasons.append("EMA20 above EMA50")
        else:
            score -= 1
            reasons.append("EMA20 below EMA50")

    if sma_50 is not None and sma_200 is not None:
        if close > sma_200 and sma_50 > sma_200:
            score += 2
            reasons.append("Price and SMA50 above SMA200")
        elif close < sma_200 and sma_50 < sma_200:
            score -= 2
            reasons.append("Price and SMA50 below SMA200")

    if rsi_14 is not None:
        if 45 <= rsi_14 <= 65:
            score += 1
            reasons.append("RSI in constructive trend zone")
        elif rsi_14 >= 75:
            score -= 1
            reasons.append("RSI deeply overheated")
        elif rsi_14 <= 35:
            score -= 1
            reasons.append("RSI weak/oversold")

    if macd is not None and macd_signal is not None:
        if macd > macd_signal:
            score += 1
            reasons.append("MACD above signal")
        else:
            score -= 1
            reasons.append("MACD below signal")

    if score >= 3:
        label = "STRONG_BULLISH"
    elif score >= 1:
        label = "BULLISH"
    elif score <= -3:
        label = "STRONG_BEARISH"
    elif score <= -1:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    return {"label": label, "score": score, "reasons": reasons}


def _infer_timeframe(candles: list[dict[str, Any]]) -> str:
    if len(candles) < 2:
        return "UNKNOWN"
    first = pd.Timestamp(candles[-2]["date"])
    second = pd.Timestamp(candles[-1]["date"])
    delta_days = max(1, (second - first).days)
    if delta_days >= 6:
        return "1W"
    return "1D"


def _rolling_window_extreme(series: pd.Series, total_len: int, *, max_points: int, mode: str) -> float | None:
    window = series.tail(min(total_len, max_points)).dropna()
    if window.empty:
        return None
    value = window.max() if mode == "max" else window.min()
    return _finite_float(value)


def _series_to_optional_list(series: pd.Series, digits: int = 4) -> list[float | None]:
    return [_round_optional(_finite_float(value), digits=digits) for value in series.tolist()]


def _last_valid(series: pd.Series) -> float | None:
    valid = series.dropna()
    if valid.empty:
        return None
    return _finite_float(valid.iloc[-1])


def _finite_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _int_volume(value: Any) -> int:
    number = _finite_float(value)
    return int(number) if number is not None else 0


def _round_price(value: float) -> float:
    return round(value, 2)


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round(((current - previous) / previous) * 100, 2)


def _xml_text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _atom_link(entry: ET.Element) -> str:
    link = entry.find("{http://www.w3.org/2005/Atom}link")
    if link is None:
        return ""
    return link.attrib.get("href", "")


def _clean_text(text: str) -> str:
    stripped = re.sub(r"<[^>]+>", "", text or "")
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ", "&#39;": "'", "&quot;": '"'}
    for entity, char in entities.items():
        stripped = stripped.replace(entity, char)
    return re.sub(r"\s+", " ", stripped).strip()


def _normalize_pubdate(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()

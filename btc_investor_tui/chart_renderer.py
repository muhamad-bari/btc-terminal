"""High-density Braille chart renderer using plotille.

Renders candlestick charts with clear wicks, smooth EMA lines,
and TradingView dark-mode colors.
"""

from __future__ import annotations

import math
from typing import Any

import plotille

Payload = dict[str, Any]

# TradingView dark mode palette (plotille Canvas uses ANSI color names)
_GREEN = "green"         # candle up
_RED = "red"             # candle down
_YELLOW = "yellow"       # EMA20
_CYAN = "cyan"           # EMA50
_ZONE_BUY = "green"     # demand order block band
_ZONE_SELL = "red"      # supply order block band
_GRID = "white"          # grid/reference lines
_MAX_VISIBLE_ORDER_BLOCKS = 6


def _as_float(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _slice_candles(candles: list[dict], technical: Payload, max_points: int) -> dict[str, list]:
    """Slice candles and indicator series to fit chart width."""
    indicator_series = technical.get("indicator_series") or {}
    if not isinstance(indicator_series, dict):
        indicator_series = {}
    n = min(len(candles), max_points)
    start = max(0, len(candles) - n)
    visible = candles[start:]

    def get_series(name: str) -> list:
        values = indicator_series.get(name)
        if not isinstance(values, list):
            return [None] * len(visible)
        sliced = values[start:]
        pad = len(visible) - len(sliced)
        if pad > 0:
            sliced = [None] * pad + sliced
        return sliced[-len(visible):]

    return {
        "open": [_as_float(c.get("open")) or 0.0 for c in visible],
        "high": [_as_float(c.get("high")) or 0.0 for c in visible],
        "low": [_as_float(c.get("low")) or 0.0 for c in visible],
        "close": [_as_float(c.get("close")) or 0.0 for c in visible],
        "dates": [str(c.get("date", "")) for c in visible],
        "ema_20": get_series("ema_20"),
        "ema_50": get_series("ema_50"),
        "rsi_14": get_series("rsi_14"),
        "macd": get_series("macd"),
        "macd_signal": get_series("macd_signal"),
        "macd_histogram": get_series("macd_histogram"),
        "stoch_k": get_series("stoch_k"),
        "stoch_d": get_series("stoch_d"),
    }


def build_price_chart(
    candles: list[dict],
    technical: Payload,
    timeframe: str,
    width: int,
    height: int,
    order_blocks: Payload | None = None,
    show_ema_fast: bool = True,
    show_ema_slow: bool = True,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
) -> str:
    """Render candlestick chart with EMA overlays and deterministic order blocks."""
    max_points = min(len(candles), max(40, width // 2))
    rows = _slice_candles(candles, technical, max_points)
    n = len(rows["close"])
    if n < 2:
        return "Insufficient data"

    # Calculate price range with padding
    all_prices = rows["high"] + rows["low"]
    ymin = min(all_prices)
    ymax = max(all_prices)
    pad = (ymax - ymin) * 0.05 or 1.0
    ymin -= pad
    ymax += pad

    # Canvas: each candle gets ~2 columns for spacing
    canvas_w = max(40, width - 12)  # leave room for Y-axis labels
    canvas_h = max(10, height - 3)  # leave room for X-axis

    c = plotille.Canvas(width=canvas_w, height=canvas_h,
                        xmin=0, xmax=n, ymin=ymin, ymax=ymax)

    _draw_order_block_bands(c, order_blocks, len(candles) - n, n, ymin, ymax)

    # Draw candlesticks: wick (line) + body (rect)
    for i in range(n):
        o, h, l, cl = rows["open"][i], rows["high"][i], rows["low"][i], rows["close"][i]
        x = i + 0.5  # center of candle slot
        color = _GREEN if cl >= o else _RED

        # Wick: thin vertical line from low to high
        c.line(x, l, x, h, color=color)

        # Body: small rect from open to close
        body_lo = min(o, cl)
        body_hi = max(o, cl)
        # Ensure body has minimum visible height
        if body_hi - body_lo < (ymax - ymin) * 0.002:
            body_hi = body_lo + (ymax - ymin) * 0.002
        bx0 = i + 0.2
        bx1 = i + 0.8
        c.rect(bx0, body_lo, bx1, body_hi, color=color)

    # Draw EMA lines (smooth curves on top)
    if show_ema_fast:
        _draw_series_line(c, rows["ema_20"], _YELLOW)
    if show_ema_slow:
        _draw_series_line(c, rows["ema_50"], _CYAN)

    # Build output with Y-axis labels
    tf_label = "1W" if timeframe == "weekly" else "1D"
    legend_parts = ["\033[38;2;38;166;91m● Up\033[0m", "\033[38;2;239;57;74m● Down\033[0m"]
    if show_ema_fast:
        legend_parts.append(f"\033[38;2;255;200;50m─ EMA{ema_fast_period}\033[0m")
    if show_ema_slow:
        legend_parts.append(f"\033[38;2;100;200;255m─ EMA{ema_slow_period}\033[0m")
    if order_blocks and order_blocks.get("unmitigated"):
        legend_parts.append("\033[38;2;38;166;91m▌ Demand OB\033[0m")
        legend_parts.append("\033[38;2;239;57;74m▌ Supply OB\033[0m")
    title = f"  BTC-USDT {tf_label} │ {' '.join(legend_parts)}"

    canvas_lines = c.plot().split("\n")
    n_lines = len(canvas_lines)

    # Add Y-axis labels
    output_lines = [title]
    for idx, line in enumerate(canvas_lines):
        # Map line index to price
        price = ymax - (idx / max(1, n_lines - 1)) * (ymax - ymin)
        label = f"${price:>8,.0f} │"
        output_lines.append(f"{label}{line}")

    # X-axis: show first and last date
    dates = rows["dates"]
    x_axis = f"{'':>10} └{'─' * canvas_w}"
    date_line = f"{'':>10}  {dates[0]}" + " " * max(0, canvas_w - len(dates[0]) - len(dates[-1])) + dates[-1]
    output_lines.append(x_axis)
    output_lines.append(date_line)

    return "\n".join(output_lines)


def _draw_order_block_bands(
    canvas: plotille.Canvas,
    order_blocks: Payload | None,
    visible_start: int,
    visible_count: int,
    ymin: float,
    ymax: float,
) -> None:
    if not order_blocks:
        return
    blocks = order_blocks.get("unmitigated")
    if not isinstance(blocks, list):
        return
    for block in blocks[:_MAX_VISIBLE_ORDER_BLOCKS]:
        if not isinstance(block, dict) or block.get("mitigated"):
            continue
        price_low = _as_float(block.get("price_low"))
        price_high = _as_float(block.get("price_high"))
        if price_low is None or price_high is None or price_high <= ymin or price_low >= ymax:
            continue
        origin_index = _as_float(block.get("origin_index"))
        start_x = 0 if origin_index is None else max(0, int(origin_index) - visible_start)
        color = _ZONE_BUY if block.get("type") == "bullish" else _ZONE_SELL
        canvas.rect(start_x, max(ymin, price_low), visible_count, min(ymax, price_high), color=color)


def _draw_series_line(canvas: plotille.Canvas, values: list, color: str) -> None:
    """Draw a smooth line connecting non-None values."""
    prev_x: float | None = None
    prev_y: float | None = None
    for i, v in enumerate(values):
        y = _as_float(v)
        if y is None:
            prev_x = prev_y = None
            continue
        x = i + 0.5
        if prev_x is not None and prev_y is not None:
            canvas.line(prev_x, prev_y, x, y, color=color)
        prev_x, prev_y = x, y


def build_indicator_chart(
    candles: list[dict],
    technical: Payload,
    timeframe: str,
    indicator: str,
    width: int,
    height: int,
    show_rsi: bool = True,
    show_stoch: bool = True,
) -> str:
    """Render RSI/Stoch combined or MACD indicator chart."""
    max_points = min(len(candles), max(40, width // 2))
    rows = _slice_candles(candles, technical, max_points)
    n = len(rows["close"])
    if n < 2:
        return "Insufficient data"

    canvas_w = max(40, width - 12)
    canvas_h = max(6, height - 3)
    tf_label = "1W" if timeframe == "weekly" else "1D"

    if indicator == "macd":
        return _build_macd(rows, n, canvas_w, canvas_h, tf_label)

    # RSI or Stoch view
    if not show_rsi and not show_stoch:
        return f"  {tf_label} Oscillators disabled"
    return _build_rsi_stoch(rows, n, canvas_w, canvas_h, tf_label, show_rsi, show_stoch)


def _build_rsi_stoch(rows: dict, n: int, canvas_w: int, canvas_h: int, tf_label: str, show_rsi: bool, show_stoch: bool) -> str:
    """Render RSI and/or Stochastic in one chart (0-100 scale)."""
    c = plotille.Canvas(width=canvas_w, height=canvas_h, xmin=0, xmax=n, ymin=0, ymax=100)

    # Reference lines
    c.line(0, 70, n, 70, color=_RED)
    c.line(0, 50, n, 50, color=_GRID)
    c.line(0, 30, n, 30, color=_GREEN)

    legend = []
    if show_rsi:
        _draw_series_line(c, rows["rsi_14"], _CYAN)
        legend.append("\033[38;2;100;200;255m─ RSI\033[0m")
    if show_stoch:
        _draw_series_line(c, rows["stoch_k"], _YELLOW)
        _draw_series_line(c, rows["stoch_d"], "magenta")
        legend.append("\033[38;2;255;200;50m─ %K\033[0m")
        legend.append("\033[35m─ %D\033[0m")

    title = f"  {tf_label} │ {'  '.join(legend)}  \033[31m── 70\033[0m  \033[32m── 30\033[0m"
    canvas_lines = c.plot().split("\n")
    n_lines = len(canvas_lines)

    output_lines = [title]
    for idx, line in enumerate(canvas_lines):
        val = 100 - (idx / max(1, n_lines - 1)) * 100
        label = f"  {val:>5.0f}  │"
        output_lines.append(f"{label}{line}")

    output_lines.append(f"{'':>9} └{'─' * canvas_w}")
    return "\n".join(output_lines)


def _build_macd(rows: dict, n: int, canvas_w: int, canvas_h: int, tf_label: str) -> str:
    """Render MACD chart with signal and histogram."""
    # Determine Y range from MACD values
    all_vals = []
    for series_name in ("macd", "macd_signal", "macd_histogram"):
        for v in rows[series_name]:
            f = _as_float(v)
            if f is not None:
                all_vals.append(f)

    if not all_vals:
        return "No MACD data"

    ymin = min(all_vals)
    ymax = max(all_vals)
    pad = (ymax - ymin) * 0.1 or 1.0
    ymin -= pad
    ymax += pad

    c = plotille.Canvas(width=canvas_w, height=canvas_h, xmin=0, xmax=n, ymin=ymin, ymax=ymax)

    # Zero line
    if ymin < 0 < ymax:
        c.line(0, 0, n, 0, color=_GRID)

    # Histogram as vertical lines
    for i, v in enumerate(rows["macd_histogram"]):
        f = _as_float(v)
        if f is None:
            continue
        color = _GREEN if f >= 0 else _RED
        c.line(i + 0.5, 0, i + 0.5, f, color=color)

    # MACD and signal lines
    _draw_series_line(c, rows["macd"], _CYAN)
    _draw_series_line(c, rows["macd_signal"], _YELLOW)

    title = f"  {tf_label} MACD │ \033[38;2;100;200;255m─ MACD\033[0m  \033[38;2;255;200;50m─ Signal\033[0m  \033[38;2;38;166;91m▌\033[0m\033[38;2;239;57;74m▌ Hist\033[0m"
    canvas_lines = c.plot().split("\n")
    n_lines = len(canvas_lines)

    output_lines = [title]
    for idx, line in enumerate(canvas_lines):
        val = ymax - (idx / max(1, n_lines - 1)) * (ymax - ymin)
        label = f"{val:>8.0f} │"
        output_lines.append(f"{label}{line}")

    output_lines.append(f"{'':>9} └{'─' * canvas_w}")
    return "\n".join(output_lines)

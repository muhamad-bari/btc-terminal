"""Matplotlib/Textual-image chart canvas for the BTC investor TUI."""

from __future__ import annotations

import importlib
import importlib.util
import math
import os
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.widgets import Static

Payload = dict[str, Any]


_CHART_THEME = {
    "bg": "#020402",
    "panel": "#08110d",
    "grid": "#163027",
    "text": "#d8e6dc",
    "muted": "#6f7c73",
    "amber": "#ff9f1c",
    "green": "#00e676",
    "red": "#ff4d5a",
    "cyan": "#22d3ee",
    "yellow": "#ffd166",
    "magenta": "#e879f9",
}

_PRICE_HEADER_Y = 1.10
_INDICATOR_HEADER_Y = 1.28
_INDICATOR_HEADER_NOTE_Y = 1.30
_AXIS_KEY_SWATCH_WIDTH = 0.032
_AXIS_KEY_LABEL_OFFSET = 0.040
_AXIS_KEY_ENTRY_GAP = 0.125
_MACRO_TOP_RULE_Y = 0.94
_MACRO_TITLE_Y = 1.10
_MACRO_ROW_ONE_Y = 0.48
_MACRO_ROW_TWO_Y = 0.15


class ImageChartCanvas(Static):
    """Matplotlib-backed PNG dashboard canvas with optional textual-image output."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", markup=False, **kwargs)
        self._data: Payload | None = None
        self._macro_data: Payload | None = None
        self._timeframe = "weekly"
        self._indicator = "rsi"
        self._order_blocks: Payload | None = None
        self._ema_fast_on = True
        self._ema_slow_on = True
        self._ema_fast_p = 20
        self._ema_slow_p = 50
        self._show_rsi = True
        self._show_stoch = True
        self._rsi_p = 14
        self._stoch_k = 5
        self._stoch_d = 3
        self._stoch_smooth = 3
        self._macd_fast = 12
        self._macd_slow = 26
        self._macd_signal = 9
        self._prebuilt_png: bytes | None = None
        self._image_path: Path | None = None
        self._image_widget: Any | None = None

    def set_state(
        self,
        data: Payload | None,
        macro_data: Payload | None,
        timeframe: str,
        indicator: str,
        order_blocks: Payload | None = None,
        ema_fast_on: bool = True,
        ema_slow_on: bool = True,
        ema_fast_p: int = 20,
        ema_slow_p: int = 50,
        show_rsi: bool = True,
        show_stoch: bool = True,
        rsi_p: int = 14,
        stoch_k: int = 5,
        stoch_d: int = 3,
        stoch_smooth: int = 3,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        prebuilt_png: bytes | None = None,
    ) -> None:
        self._data = data
        self._macro_data = macro_data
        self._timeframe = timeframe
        self._indicator = indicator
        self._order_blocks = order_blocks
        self._ema_fast_on = ema_fast_on
        self._ema_slow_on = ema_slow_on
        self._ema_fast_p = ema_fast_p
        self._ema_slow_p = ema_slow_p
        self._show_rsi = show_rsi
        self._show_stoch = show_stoch
        self._rsi_p = rsi_p
        self._stoch_k = stoch_k
        self._stoch_d = stoch_d
        self._stoch_smooth = stoch_smooth
        self._macd_fast = macd_fast
        self._macd_slow = macd_slow
        self._macd_signal = macd_signal
        self._prebuilt_png = prebuilt_png
        self._render_image()

    def on_mount(self) -> None:
        self.call_later(self._render_image)

    def on_resize(self) -> None:
        self._render_image()

    def on_unmount(self) -> None:
        self._cleanup_image_path()

    def _render_image(self) -> None:
        if not self._data:
            self.update(Text("Loading...", style="bold yellow"))
            return
        section = self._data.get(self._timeframe)
        if not isinstance(section, dict):
            self.update(Text("No data", style="bold red"))
            return
        candles = section.get("candles", [])
        if not candles:
            self.update(Text("No candles", style="bold red"))
            return

        missing = _missing_pixel_chart_dependencies()
        if missing:
            self._render_text_fallback(
                f"Pixel image backend unavailable: missing {', '.join(missing)}"
            )
            return

        try:
            if self._prebuilt_png is not None:
                png = self._prebuilt_png
                self._prebuilt_png = None
            else:
                png = build_dashboard_png(
                    self._data,
                    self._macro_data,
                    self._timeframe,
                    self._indicator,
                    self._order_blocks,
                    self._ema_fast_on,
                    self._ema_slow_on,
                    self._ema_fast_p,
                    self._ema_slow_p,
                    self._show_rsi,
                    self._show_stoch,
                    self._rsi_p,
                    self._stoch_k,
                    self._stoch_d,
                    self._stoch_smooth,
                    self._macd_fast,
                    self._macd_slow,
                    self._macd_signal,
                    max(900, min(1800, max(1, self.size.width) * 12)),
                    max(620, min(1200, max(1, self.size.height) * 20)),
                )
        except Exception as exc:
            self._render_text_fallback(f"Could not render pixel chart: {exc}")
            return

        try:
            message = self._display_png(png)
        except Exception as exc:
            self._render_text_fallback(f"Could not display pixel chart: {exc}")
            return
        if message:
            self._render_text_fallback(message)

    def _display_png(self, png: bytes) -> str | None:
        image = _png_to_pillow_image(png)
        widget = self._image_widget
        if widget is not None:
            try:
                widget.image = image
                return None
            except Exception:
                self._image_widget = None
                self.remove_children()

        widget = _textual_image_widget(image)
        if widget is None:
            self._write_png_temp(png)
            return "textual-image is installed, but no compatible terminal image widget was found"
        widget.styles.width = "100%"
        widget.styles.height = "100%"
        self._image_widget = widget
        self.update("")
        self.remove_children()
        self.mount(widget)
        return None

    def _render_text_fallback(self, reason: str) -> None:
        try:
            chart = _build_text_chart_fallback(
                self._data,
                self._timeframe,
                self._indicator,
                self._order_blocks,
                self._ema_fast_on,
                self._ema_slow_on,
                self._ema_fast_p,
                self._ema_slow_p,
                self._show_rsi,
                self._show_stoch,
                self._rsi_p,
                self._stoch_k,
                self._stoch_d,
                self._stoch_smooth,
                self._macd_fast,
                self._macd_slow,
                self._macd_signal,
                max(78, self.size.width - 4),
                max(24, self.size.height - 4),
                reason,
            )
        except Exception as exc:
            self.remove_children()
            self.update(
                Text(f"Could not render image or text chart: {exc}", style="bold red")
            )
            return
        self._image_widget = None
        self.remove_children()
        self.update(Text.from_ansi(chart))

    def _write_png_temp(self, png: bytes) -> Path:
        self._cleanup_image_path()
        temp = NamedTemporaryFile(
            prefix="btc-investor-chart-", suffix=".png", delete=False
        )
        try:
            temp.write(png)
            self._image_path = Path(temp.name)
            return self._image_path
        finally:
            temp.close()

    def _cleanup_image_path(self) -> None:
        if self._image_path and self._image_path.exists():
            try:
                self._image_path.unlink()
            except OSError:
                pass
        self._image_path = None


def _build_text_chart_fallback(
    data: Payload | None,
    timeframe: str,
    indicator: str,
    order_blocks: Payload | None,
    ema_fast_on: bool,
    ema_slow_on: bool,
    ema_fast_p: int,
    ema_slow_p: int,
    show_rsi: bool,
    show_stoch: bool,
    rsi_p: int,
    stoch_k: int,
    stoch_d: int,
    stoch_smooth: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
    width: int,
    height: int,
    reason: str,
) -> str:
    if not data:
        return reason
    section = data.get(timeframe)
    if not isinstance(section, dict):
        return reason
    candles = section.get("candles", [])
    technical = section.get("technical", {})
    if not isinstance(candles, list) or not isinstance(technical, dict) or not candles:
        return reason
    try:
        from btc_investor_tui.chart_renderer import (
            build_indicator_chart,
            build_price_chart,
        )
    except Exception as exc:
        return f"{reason}\nText chart fallback unavailable: {exc}"

    price_height = max(12, int(height * 0.65))
    indicator_height = max(8, height - price_height - 2)
    price_chart = build_price_chart(
        candles,
        technical,
        timeframe,
        width,
        price_height,
        order_blocks,
        ema_fast_on,
        ema_slow_on,
        ema_fast_p,
        ema_slow_p,
    )
    indicator_chart = build_indicator_chart(
        candles,
        technical,
        timeframe,
        indicator,
        width,
        indicator_height,
        show_rsi,
        show_stoch,
        rsi_p,
        stoch_k,
        stoch_d,
        stoch_smooth,
        macd_fast,
        macd_slow,
        macd_signal,
    )
    return f"{reason}\nUsing terminal text chart fallback.\n\n{price_chart}\n\n{indicator_chart}"


def build_dashboard_png(
    data: Payload,
    macro_data: Payload | None,
    timeframe: str,
    indicator: str,
    order_blocks: Payload | None,
    ema_fast_on: bool,
    ema_slow_on: bool,
    ema_fast_p: int,
    ema_slow_p: int,
    show_rsi: bool,
    show_stoch: bool,
    rsi_p: int = 14,
    stoch_k: int = 5,
    stoch_d: int = 3,
    stoch_smooth: int = 3,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    width_px: int = 1300,
    height_px: int = 820,
) -> bytes:
    """Render the BTC dashboard image to PNG bytes without touching the network."""
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg")
    plt = importlib.import_module("matplotlib.pyplot")
    rectangle_cls = getattr(importlib.import_module("matplotlib.patches"), "Rectangle")

    section = data.get(timeframe)
    if not isinstance(section, dict):
        raise ValueError("timeframe data is unavailable")
    candles = section.get("candles", [])
    technical = section.get("technical", {})
    if not isinstance(candles, list) or not candles:
        raise ValueError("candles are unavailable")

    visible = candles[-120:]
    start_index = len(candles) - len(visible)
    dates = [str(candle.get("date", "")) for candle in visible]
    opens = [_chart_float(candle.get("open")) for candle in visible]
    highs = [_chart_float(candle.get("high")) for candle in visible]
    lows = [_chart_float(candle.get("low")) for candle in visible]
    closes = [_chart_float(candle.get("close")) for candle in visible]
    candle_prices = [value for value in highs + lows + closes if value is not None]
    if not candle_prices:
        raise ValueError("candle prices are unavailable")
    candle_price_min = min(candle_prices)
    candle_price_max = max(candle_prices)
    visible_ob_prices = _visible_order_block_prices(
        order_blocks,
        start_index,
        len(visible),
        candle_price_min,
        candle_price_max,
    )
    valid_prices = candle_prices + visible_ob_prices

    dpi = 120
    fig = plt.figure(
        figsize=(width_px / dpi, height_px / dpi), dpi=dpi, facecolor=_CHART_THEME["bg"]
    )
    has_macd_panel = indicator == "macd"
    height_ratios = [5.25]
    if show_rsi:
        height_ratios.append(1.24)
    if show_stoch:
        height_ratios.append(1.24)
    if has_macd_panel:
        height_ratios.append(1.30)
    height_ratios.append(1.35)
    grid = fig.add_gridspec(
        len(height_ratios), 1, height_ratios=height_ratios, hspace=0.92
    )
    ax_price = fig.add_subplot(grid[0])
    row = 1
    ax_rsi = fig.add_subplot(grid[row], sharex=ax_price) if show_rsi else None
    row += 1 if show_rsi else 0
    ax_stoch = fig.add_subplot(grid[row], sharex=ax_price) if show_stoch else None
    row += 1 if show_stoch else 0
    ax_macd = fig.add_subplot(grid[row], sharex=ax_price) if has_macd_panel else None
    row += 1 if has_macd_panel else 0
    ax_summary = fig.add_subplot(grid[row])

    _style_axis(ax_price)
    if ax_rsi is not None:
        _style_axis(ax_rsi)
    if ax_stoch is not None:
        _style_axis(ax_stoch)
    if ax_macd is not None:
        _style_axis(ax_macd)

    x_values = list(range(len(visible)))
    candle_width = 0.62
    price_min = min(valid_prices)
    price_max = max(valid_prices)
    ax_price.set_xlim(-0.8, max(len(visible) - 0.2, 0.2))

    for x, open_price, high_price, low_price, close_price in zip(
        x_values, opens, highs, lows, closes
    ):
        if (
            open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
        ):
            continue
        color = (
            _CHART_THEME["green"] if close_price >= open_price else _CHART_THEME["red"]
        )
        ax_price.vlines(
            x, low_price, high_price, color=color, linewidth=1.2, alpha=0.85
        )
        body_bottom = min(open_price, close_price)
        body_height = max(
            abs(close_price - open_price), (price_max - price_min) * 0.002
        )
        ax_price.add_patch(
            rectangle_cls(
                (x - candle_width / 2, body_bottom),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.9,
                alpha=0.95,
            )
        )

    series = (
        technical.get("indicator_series", {}) if isinstance(technical, dict) else {}
    )
    if isinstance(series, dict):
        if ema_fast_on:
            _plot_series(
                ax_price,
                series.get("ema_20"),
                start_index,
                _CHART_THEME["cyan"],
                f"EMA{ema_fast_p}",
            )
        if ema_slow_on:
            _plot_series(
                ax_price,
                series.get("ema_50"),
                start_index,
                _CHART_THEME["amber"],
                f"EMA{ema_slow_p}",
            )

    margin = (
        (price_max - price_min) * 0.08
        if price_max > price_min
        else max(price_max * 0.02, 1)
    )
    y_min = price_min - margin
    y_max = price_max + margin
    ax_price.set_ylim(y_min, y_max)
    _draw_order_blocks(
        ax_price,
        order_blocks,
        start_index,
        len(visible),
        y_min,
        y_max,
        candle_price_min,
        candle_price_max,
    )
    tf_label = "1W" if timeframe == "weekly" else "1D"
    ema_entries = []
    if ema_fast_on:
        ema_entries.append((f"EMA{ema_fast_p}", _CHART_THEME["cyan"]))
    if ema_slow_on:
        ema_entries.append((f"EMA{ema_slow_p}", _CHART_THEME["amber"]))
    _draw_axis_header(
        ax_price,
        f"BTC-USDT {tf_label} · Candles / EMA / Impulsive Order Blocks",
        ema_entries,
        note="OB bands transparent",
        key_x=0.47,
        header_y=_PRICE_HEADER_Y,
        note_y=_PRICE_HEADER_Y,
        key_y=_PRICE_HEADER_Y,
        title_size=13,
    )

    series_payload = series if isinstance(series, dict) else {}
    chart_axes = [ax_price]
    if ax_rsi is not None:
        _render_rsi_axis(ax_rsi, series_payload, start_index, len(visible), rsi_p)
        chart_axes.append(ax_rsi)
    if ax_stoch is not None:
        _render_stoch_axis(
            ax_stoch,
            series_payload,
            start_index,
            len(visible),
            stoch_k,
            stoch_d,
            stoch_smooth,
        )
        chart_axes.append(ax_stoch)
    if ax_macd is not None:
        _render_macd_axis(
            ax_macd,
            series_payload,
            start_index,
            len(visible),
            macd_fast,
            macd_slow,
            macd_signal,
        )
        chart_axes.append(ax_macd)
    for axis in chart_axes[:-1]:
        axis.tick_params(labelbottom=False)
    _apply_date_ticks(chart_axes[-1], dates)
    _render_summary_axis(
        ax_summary,
        data,
        macro_data,
        timeframe,
        technical,
        ema_fast_p,
        ema_slow_p,
        rsi_p,
        macd_fast,
        macd_slow,
        macd_signal,
    )

    fig.subplots_adjust(left=0.032, right=0.997, top=0.96, bottom=0.07)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def _missing_pixel_chart_dependencies() -> list[str]:
    missing: list[str] = []
    for module_name, package_name in (
        ("matplotlib", "matplotlib"),
        ("PIL", "pillow"),
        ("textual_image", "textual-image"),
    ):
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)
    return missing


def _png_to_pillow_image(png: bytes) -> Any:
    image_cls = getattr(importlib.import_module("PIL.Image"), "open")
    image = image_cls(BytesIO(png))
    image.load()
    return image


def _textual_image_widget(image: Any) -> Any | None:
    try:
        module = importlib.import_module("textual_image.widget")
    except Exception:
        return None

    class_names = ("TGPImage", "SixelImage", "HalfcellImage", "UnicodeImage")
    if "kitty" not in (os.environ.get("TERM") or "").lower() and not os.environ.get(
        "KITTY_WINDOW_ID"
    ):
        class_names = ("SixelImage", "HalfcellImage", "UnicodeImage", "TGPImage")
    for class_name in class_names:
        image_cls = getattr(module, class_name, None)
        if image_cls is None:
            continue
        try:
            return image_cls(image, id="chart-image")
        except Exception:
            continue
    return None


def _style_axis(axis: Any) -> None:
    axis.set_facecolor(_CHART_THEME["panel"])
    axis.grid(True, color=_CHART_THEME["grid"], linewidth=0.55, alpha=0.55)
    axis.tick_params(colors=_CHART_THEME["muted"], labelsize=8)
    for spine in axis.spines.values():
        spine.set_color(_CHART_THEME["grid"])


def _chart_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _plot_series(
    axis: Any, values: Any, start_index: int, color: str, label: str
) -> None:
    if not isinstance(values, list):
        return
    visible = values[start_index:]
    points = [(index, _chart_float(value)) for index, value in enumerate(visible)]
    points = [(index, value) for index, value in points if value is not None]
    if points:
        axis.plot(
            [point[0] for point in points],
            [point[1] for point in points],
            color=color,
            linewidth=1.45,
            label=label,
        )


def _draw_order_blocks(
    axis: Any,
    order_blocks: Payload | None,
    start_index: int,
    visible_len: int,
    y_min: float,
    y_max: float,
    candle_price_min: float,
    candle_price_max: float,
) -> None:
    rectangle_cls = getattr(importlib.import_module("matplotlib.patches"), "Rectangle")

    if not isinstance(order_blocks, dict):
        return
    blocks = order_blocks.get("unmitigated") or []
    if not isinstance(blocks, list):
        return
    for block in blocks[:8]:
        if not isinstance(block, dict):
            continue
        low = _chart_float(block.get("price_low"))
        high = _chart_float(block.get("price_high"))
        origin = block.get("origin_index")
        if low is None or high is None or origin is None or high <= low:
            continue
        if not _order_block_is_relevant(low, high, candle_price_min, candle_price_max):
            continue
        clipped_low = max(low, y_min)
        clipped_high = min(high, y_max)
        if clipped_high <= clipped_low:
            continue
        try:
            origin_index = int(origin)
        except (TypeError, ValueError):
            continue
        x0 = max(0, origin_index - start_index)
        if x0 >= visible_len:
            continue
        color = (
            _CHART_THEME["green"]
            if block.get("type") == "bullish"
            else _CHART_THEME["red"]
        )
        patch = rectangle_cls(
            (x0 - 0.5, clipped_low),
            visible_len - x0,
            clipped_high - clipped_low,
            facecolor=color,
            edgecolor=color,
            linewidth=1.0,
            alpha=0.2,
            clip_on=True,
        )
        patch.set_clip_path(axis.patch)
        axis.add_patch(patch)
        label = "DEMAND" if block.get("type") == "bullish" else "SUPPLY"
        band_height = clipped_high - clipped_low
        label_y = (
            clipped_low + band_height * 0.12
            if block.get("type") == "bullish"
            else clipped_high - band_height * 0.12
        )
        label_va = "bottom" if block.get("type") == "bullish" else "top"
        axis.text(
            x0,
            label_y,
            label,
            color=color,
            fontsize=7,
            va=label_va,
            ha="left",
            alpha=0.9,
            clip_on=True,
        )


def _visible_order_block_prices(
    order_blocks: Payload | None,
    start_index: int,
    visible_len: int,
    candle_price_min: float,
    candle_price_max: float,
) -> list[float]:
    if not isinstance(order_blocks, dict):
        return []
    blocks = order_blocks.get("unmitigated") or []
    if not isinstance(blocks, list):
        return []
    end_index = start_index + visible_len
    prices: list[float] = []
    for block in blocks[:8]:
        if not isinstance(block, dict):
            continue
        origin = block.get("origin_index")
        if origin is None:
            continue
        try:
            origin_index = int(origin)
        except (TypeError, ValueError):
            continue
        if origin_index >= end_index:
            continue
        low = _chart_float(block.get("price_low"))
        high = _chart_float(block.get("price_high"))
        if low is None or high is None or high <= low:
            continue
        if not _order_block_is_relevant(low, high, candle_price_min, candle_price_max):
            continue
        prices.extend([low, high])
    return prices


def _order_block_is_relevant(
    low: float, high: float, candle_price_min: float, candle_price_max: float
) -> bool:
    candle_range = candle_price_max - candle_price_min
    if candle_range <= 0:
        candle_range = max(candle_price_max * 0.02, 1.0)
    midpoint = (candle_price_min + candle_price_max) / 2
    buffer = max(candle_range * 0.10, midpoint * 0.035, 1.0)
    buffer = min(buffer, max(midpoint * 0.08, 1.0))
    expanded_min = candle_price_min - buffer
    expanded_max = candle_price_max + buffer
    return high >= expanded_min and low <= expanded_max


def _render_rsi_axis(
    axis: Any, series: Payload, start_index: int, visible_len: int, rsi_p: int
) -> None:
    axis.set_ylim(0, 100)
    axis.axhspan(70, 100, color=_CHART_THEME["red"], alpha=0.08)
    axis.axhspan(0, 30, color=_CHART_THEME["green"], alpha=0.08)
    axis.axhline(70, color=_CHART_THEME["red"], linewidth=0.8, alpha=0.7)
    axis.axhline(30, color=_CHART_THEME["green"], linewidth=0.8, alpha=0.7)
    label = f"RSI{rsi_p}"
    _line_from_visible(
        axis,
        _visible_series(series.get("rsi_14"), start_index, visible_len),
        _CHART_THEME["cyan"],
        label,
    )
    _draw_axis_header(
        axis,
        label,
        [(label, _CHART_THEME["cyan"])],
        note="zones: 30 / 70",
        key_x=0.12,
        header_y=_INDICATOR_HEADER_Y,
        note_y=_INDICATOR_HEADER_NOTE_Y,
        key_y=_INDICATOR_HEADER_Y,
        title_size=10,
    )


def _render_stoch_axis(
    axis: Any,
    series: Payload,
    start_index: int,
    visible_len: int,
    stoch_k: int,
    stoch_d: int,
    stoch_smooth: int,
) -> None:
    axis.set_ylim(0, 100)
    axis.axhspan(80, 100, color=_CHART_THEME["red"], alpha=0.08)
    axis.axhspan(0, 20, color=_CHART_THEME["green"], alpha=0.08)
    axis.axhline(80, color=_CHART_THEME["red"], linewidth=0.8, alpha=0.7)
    axis.axhline(20, color=_CHART_THEME["green"], linewidth=0.8, alpha=0.7)
    _line_from_visible(
        axis,
        _visible_series(series.get("stoch_k"), start_index, visible_len),
        _CHART_THEME["yellow"],
        f"%K{stoch_k}",
    )
    _line_from_visible(
        axis,
        _visible_series(series.get("stoch_d"), start_index, visible_len),
        _CHART_THEME["magenta"],
        f"%D{stoch_d}",
    )
    _draw_axis_header(
        axis,
        f"Stochastic {stoch_k}-{stoch_d}-{stoch_smooth}",
        [
            (f"%K{stoch_k}", _CHART_THEME["yellow"]),
            (f"%D{stoch_d}", _CHART_THEME["magenta"]),
        ],
        note="zones: 20 / 80",
        key_x=0.26,
        header_y=_INDICATOR_HEADER_Y,
        note_y=_INDICATOR_HEADER_NOTE_Y,
        key_y=_INDICATOR_HEADER_Y,
        title_size=10,
    )


def _render_macd_axis(
    axis: Any,
    series: Payload,
    start_index: int,
    visible_len: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
) -> None:
    macd = _visible_series(series.get("macd"), start_index, visible_len)
    signal = _visible_series(series.get("macd_signal"), start_index, visible_len)
    histogram = _visible_series(series.get("macd_histogram"), start_index, visible_len)
    axis.axhline(0, color=_CHART_THEME["muted"], linewidth=0.8)
    _line_from_visible(axis, macd, _CHART_THEME["cyan"], "MACD")
    _line_from_visible(axis, signal, _CHART_THEME["amber"], "Signal")
    bars = [
        (index, value) for index, value in enumerate(histogram) if value is not None
    ]
    if bars:
        colors = [
            _CHART_THEME["green"] if value >= 0 else _CHART_THEME["red"]
            for _, value in bars
        ]
        axis.bar(
            [index for index, _ in bars],
            [value for _, value in bars],
            color=colors,
            alpha=0.55,
            width=0.75,
        )
    _draw_axis_header(
        axis,
        f"MACD {macd_fast}-{macd_slow}-{macd_signal}",
        [
            (f"MACD {macd_fast}/{macd_slow}", _CHART_THEME["cyan"]),
            (f"Signal {macd_signal}", _CHART_THEME["amber"]),
        ],
        note="Histogram bars",
        key_x=0.24,
        header_y=_INDICATOR_HEADER_Y,
        note_y=_INDICATOR_HEADER_NOTE_Y,
        key_y=_INDICATOR_HEADER_Y,
        title_size=10,
    )


def _visible_series(
    values: Any, start_index: int, visible_len: int
) -> list[float | None]:
    if not isinstance(values, list):
        return [None] * visible_len
    sliced = values[start_index : start_index + visible_len]
    if len(sliced) < visible_len:
        sliced = [None] * (visible_len - len(sliced)) + sliced
    return [_chart_float(value) for value in sliced]


def _line_from_visible(
    axis: Any, values: list[float | None], color: str, label: str
) -> None:
    points = [(index, value) for index, value in enumerate(values) if value is not None]
    if points:
        axis.plot(
            [index for index, _ in points],
            [value for _, value in points],
            color=color,
            linewidth=1.25,
            label=label,
        )


def _draw_axis_header(
    axis: Any,
    title: str,
    entries: list[tuple[str, str]],
    note: str | None = None,
    key_x: float = 0.20,
    title_size: int = 10,
    header_y: float = _PRICE_HEADER_Y,
    note_y: float | None = None,
    key_y: float | None = None,
    key_entry_gap: float = _AXIS_KEY_ENTRY_GAP,
) -> None:
    note_y = header_y if note_y is None else note_y
    key_y = header_y if key_y is None else key_y
    axis.text(
        0.0,
        header_y,
        title,
        color=_CHART_THEME["amber"],
        fontsize=title_size,
        fontweight="bold",
        va="center",
        ha="left",
        transform=axis.transAxes,
        clip_on=False,
    )
    _draw_axis_key(axis, entries, x=key_x, y=key_y, entry_gap=key_entry_gap)
    if note:
        axis.text(
            1.0,
            note_y,
            note,
            color=_CHART_THEME["muted"],
            fontsize=8,
            va="center",
            ha="right",
            transform=axis.transAxes,
            clip_on=False,
        )


def _draw_axis_key(
    axis: Any,
    entries: list[tuple[str, str]],
    x: float = 0.70,
    y: float = _PRICE_HEADER_Y,
    entry_gap: float = _AXIS_KEY_ENTRY_GAP,
) -> None:
    cursor = x
    for label, color in entries:
        axis.plot(
            [cursor, cursor + _AXIS_KEY_SWATCH_WIDTH],
            [y, y],
            color=color,
            linewidth=2.2,
            transform=axis.transAxes,
            clip_on=False,
        )
        axis.text(
            cursor + _AXIS_KEY_LABEL_OFFSET,
            y,
            label,
            color=_CHART_THEME["text"],
            fontsize=8,
            va="center",
            ha="left",
            transform=axis.transAxes,
            clip_on=False,
        )
        cursor += entry_gap


def _apply_date_ticks(axis: Any, dates: list[str]) -> None:
    if not dates:
        return
    step = max(1, len(dates) // 6)
    positions = list(range(0, len(dates), step))
    if positions[-1] != len(dates) - 1:
        positions.append(len(dates) - 1)
    axis.set_xticks(positions)
    axis.set_xticklabels(
        [dates[index][-10:] for index in positions],
        rotation=0,
        ha="center",
        color=_CHART_THEME["muted"],
    )


def _render_summary_axis(
    axis: Any,
    data: Payload,
    macro_data: Payload | None,
    timeframe: str,
    technical: Payload,
    ema_fast_p: int,
    ema_slow_p: int,
    rsi_p: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
) -> None:
    axis.set_facecolor(_CHART_THEME["bg"])
    axis.axis("off")
    quote = data.get("quote") or {}
    market = data.get("market_summary") or {}
    moving = technical.get("moving_averages") or {}
    osc = technical.get("oscillators") or {}
    macro_data = macro_data or {}
    halving = macro_data.get("halving", {}) if isinstance(macro_data, dict) else {}
    fear = macro_data.get("fear_greed", {}) if isinstance(macro_data, dict) else {}
    mvrv = macro_data.get("mvrv", {}) if isinstance(macro_data, dict) else {}
    tf_label = "1W" if timeframe == "weekly" else "1D"
    row_one = [
        f"BTC-USDT {tf_label}",
        f"Price {_fmt_usd(market.get('price') or quote.get('price'))}  {_plain_pct(quote.get('change_pct'))}",
        f"Trend {_fmt_label(technical.get('trend_label'))}  Risk {_fmt_label(technical.get('risk_label'))}",
        f"EMA{ema_fast_p} {_fmt_usd(moving.get('ema_20'))}  EMA{ema_slow_p} {_fmt_usd(moving.get('ema_50'))}",
    ]
    row_two = [
        f"RSI{rsi_p} {_fmt_num(osc.get('rsi_14'))}  MACD({macd_fast},{macd_slow},{macd_signal}) {_fmt_num(osc.get('macd'), 3)}",
        f"Halving {halving.get('cycle_progress_pct', 'n/a')}%  Fear/Greed {fear.get('value', 'n/a')} {fear.get('classification', '')}",
        f"MVRV {mvrv.get('zscore', 'n/a')}  {str(mvrv.get('zone', 'n/a')).replace('_', ' ').title()}",
    ]
    axis.axhline(
        _MACRO_TOP_RULE_Y, color=_CHART_THEME["grid"], linewidth=1.0, alpha=0.75
    )
    axis.text(
        0.01,
        _MACRO_TITLE_Y,
        "MACRO SNAPSHOT",
        color=_CHART_THEME["amber"],
        fontsize=12,
        fontweight="bold",
        transform=axis.transAxes,
    )
    axis.text(
        0.01,
        _MACRO_ROW_ONE_Y,
        "  |  ".join(row_one),
        color=_CHART_THEME["text"],
        fontsize=8.7,
        transform=axis.transAxes,
    )
    axis.text(
        0.01,
        _MACRO_ROW_TWO_Y,
        "  |  ".join(row_two),
        color=_CHART_THEME["text"],
        fontsize=8.7,
        transform=axis.transAxes,
    )


def _plain_pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:+.2f}%" if math.isfinite(number) else ""


def _fmt_usd(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"${number:,.0f}" if math.isfinite(number) else "n/a"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:,.{digits}f}" if math.isfinite(number) else "n/a"


def _fmt_label(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, dict):
        label = str(value.get("label") or "n/a")
        score = value.get("score")
        text = label.replace("_", " ").title()
        return f"{text} ({score:+d})" if score is not None else text
    return str(value).replace("_", " ").title()

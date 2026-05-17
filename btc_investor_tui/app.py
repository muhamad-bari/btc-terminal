"""Textual dashboard for long-term Bitcoin investors.

    Terminal dashboard with dynamic indicators, order blocks, and macro intel.
"""

from __future__ import annotations

import math
import sys
import time
import webbrowser
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.reactive import reactive
from textual.widgets import Checkbox, Footer, Header, Input, Static
from textual.worker import get_current_worker

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from btc_investor_tui.data_engine import get_btc_dashboard_data, get_runtime_debug_metadata, recalculate_indicators
from btc_investor_tui.ai_zones import get_order_block_commentary, _get_token, save_token
from btc_investor_tui.macro_intel import get_macro_intel
from btc_investor_tui.pixel_chart import ImageChartCanvas, build_dashboard_png

Payload = dict[str, Any]


@dataclass
class BootResult:
    dashboard_data: Payload | None = None
    macro_data: Payload | None = None
    chart_png: bytes | None = None
    errors: list[str] = field(default_factory=list)


class BootPanel(Vertical):
    """TTY-style startup screen that streams boot status lines."""

    def compose(self) -> ComposeResult:
        yield Static("BTC INVESTOR TERMINAL", id="boot-title")
        yield Static("", id="boot-log")


class DashboardBody(VerticalScroll):
    """Main dashboard layout mounted after the boot sequence finishes."""

    def compose(self) -> ComposeResult:
        yield Static("", id="chart-title", classes="ptitle")
        yield Static("Starting...", id="status-strip")
        with Vertical(id="settings-panel"):
            yield Static("[bold #ff8c00]═══ INDICATOR SETTINGS ═══[/]")
            with Horizontal(classes="settings-row"):
                yield Checkbox("EMA Fast", value=True, id="chk-ema-fast")
                yield Input(value="20", id="inp-ema-fast", placeholder="20")
                yield Checkbox("EMA Slow", value=True, id="chk-ema-slow")
                yield Input(value="50", id="inp-ema-slow", placeholder="50")
            with Horizontal(classes="settings-row"):
                yield Checkbox("RSI", value=True, id="chk-rsi")
                yield Input(value="14", id="inp-rsi", placeholder="14")
                yield Checkbox("Stoch", value=True, id="chk-stoch")
                yield Input(value="5", id="inp-stoch-k", placeholder="K")
                yield Input(value="3", id="inp-stoch-d", placeholder="D")
                yield Input(value="3", id="inp-stoch-smooth", placeholder="Sm")
            with Horizontal(classes="settings-row"):
                yield Static(" MACD (F/S/Sig):")
                yield Input(value="12", id="inp-macd-fast", placeholder="12")
                yield Input(value="26", id="inp-macd-slow", placeholder="26")
                yield Input(value="9", id="inp-macd-sig", placeholder="9")
        yield ImageChartCanvas(id="price-chart")
        yield Static("", id="ai-analysis")
        yield Static("", id="macro-intel")
        yield Static("", id="market-summary", classes="panel")
        yield NewsPanel(id="news-section", classes="panel")


class NewsPanel(Static):
    """Clickable news panel that opens article links in the default browser."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._line_links: list[str | None] = []

    def update_feed(self, text: Text, line_links: list[str | None]) -> None:
        self._line_links = line_links
        self.update(text)

    def on_click(self, event: Click) -> None:
        url = _link_from_click(event, self)
        if not url:
            return
        event.stop()
        if webbrowser.open(url, new=2):
            self.app.notify(f"Opened: {url}", title="News")
        else:
            self.app.notify(f"Could not open browser for: {url}", title="News", severity="warning")

    def link_at_line(self, line_index: int) -> str | None:
        if 0 <= line_index < len(self._line_links):
            return self._line_links[line_index]
        return None


class BTCInvestorApp(App[None]):
    """BTC investor terminal with dynamic indicators."""

    TITLE = "BTC INVESTOR TERMINAL"
    SUB_TITLE = "BTC-USDT · Dynamic Indicators · Order Blocks · Macro Intel"
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("a", "ai_refresh", "AI Notes"),
        ("p", "toggle_settings", "Settings"),
        ("w", "weekly", "1W"),
        ("d", "daily", "1D"),
        ("i", "toggle_indicator", "RSI/MACD"),
        ("q", "quit", "Quit"),
    ]

    CSS = """
    Screen { background: #000000; color: #e0e0e0; layers: base overlay; }
    Header { background: #1a1a1a; color: #ff8c00; }
    Footer { background: #1a1a1a; color: #999999; }
    #app-body { height: 1fr; background: #000000; }
    #boot-panel { layer: overlay; width: 100%; height: 100%; background: #000000; padding: 1 2; }
    #boot-title { height: 3; color: #ff8c00; text-style: bold; }
    #boot-log { height: 1fr; background: #000000; color: #e0e0e0; border: none; }
    #main-scroll { layer: base; height: 1fr; background: #000000; }
    .ptitle { height: 3; padding: 0 1; border: solid #333333; background: #0a0a0a; color: #ff8c00; }
    .panel { border: solid #333333; background: #0a0a0a; color: #e0e0e0; padding: 1; }
    #price-chart { height: 42; padding: 0 1; border: solid #333333; background: #000000; }
    #ai-analysis { height: auto; min-height: 4; padding: 1; border: solid #444400; background: #0a0a00; }
    #macro-intel { height: auto; min-height: 4; padding: 1; border: solid #003344; background: #000a0f; }
    #status-strip { height: 3; padding: 0 1; border: solid #333333; background: #0a0a0a; color: #ff8c00; }
    #market-summary { height: auto; padding: 1; }
    #news-section { height: auto; padding: 1; }
    #settings-panel { height: auto; padding: 1; border: solid #555500; background: #0f0f00; display: none; }
    #settings-panel.visible { display: block; }
    #settings-panel Input { width: 10; }
    #settings-panel Checkbox { width: auto; margin-right: 1; }
    #settings-panel Static { width: auto; margin-right: 1; }
    .settings-row { height: 3; }
    """

    _BOOT_MESSAGE_LIMIT = 9
    _BOOT_TRANSITION_SECONDS = 3
    _AI_WATCHDOG_SECONDS = 35.0
    _AI_CONNECTING_ANALYSIS = "Connecting to GitHub Models..."

    # Reactive indicator parameters
    ema_fast_period: reactive[int] = reactive(20)
    ema_slow_period: reactive[int] = reactive(50)
    rsi_period: reactive[int] = reactive(14)
    macd_fast: reactive[int] = reactive(12)
    macd_slow: reactive[int] = reactive(26)
    macd_signal_p: reactive[int] = reactive(9)
    stoch_k: reactive[int] = reactive(5)
    stoch_d: reactive[int] = reactive(3)
    stoch_smooth: reactive[int] = reactive(3)
    show_ema_fast: reactive[bool] = reactive(True)
    show_ema_slow: reactive[bool] = reactive(True)
    show_rsi: reactive[bool] = reactive(True)
    show_stoch: reactive[bool] = reactive(True)

    def __init__(self) -> None:
        super().__init__()
        self.dashboard_data: Payload | None = None
        self.ai_commentary_data: dict[str, Payload] = {}
        self.macro_data: Payload | None = None
        self.boot_chart_png: bytes | None = None
        self.selected_timeframe = "weekly"
        self.selected_indicator = "rsi"
        self.last_error: str | None = None
        self.boot_complete = False
        self.boot_messages: list[str] = []
        self._boot_transition_remaining = 0
        self._ai_request_serial = 0
        self._ai_active_serial_by_timeframe: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="app-body"):
            yield DashboardBody(id="main-scroll")
            yield BootPanel(id="boot-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._start_boot()

    # ─── Boot sequence ────────────────────────────────────────────────────────

    def _start_boot(self) -> None:
        def boot() -> None:
            worker = get_current_worker()
            result = BootResult()

            self.call_from_thread(self._boot_log_start, "Verifikasi Environment & Struktur Folder")
            try:
                self._verify_boot_environment()
            except Exception as exc:
                result.errors.append(f"Environment: {exc}")
                self.call_from_thread(self._boot_log_failed, "Verifikasi Environment & Struktur Folder", str(exc))
            else:
                self.call_from_thread(self._boot_log_ok, "Verifikasi Environment & Struktur Folder")

            self.call_from_thread(self._boot_log_start, "Koneksi yfinance dan penarikan historis BTC-USDT")
            try:
                result.dashboard_data = get_btc_dashboard_data()
            except Exception as exc:
                result.errors.append(f"Market data: {exc}")
                self.call_from_thread(self._boot_log_failed, "Koneksi yfinance dan penarikan historis BTC-USDT", str(exc))
            else:
                self.call_from_thread(self._boot_log_ok, "Koneksi yfinance dan penarikan historis BTC-USDT")

            self._boot_validate_dashboard_stage(result, "Perhitungan Indikator Teknis Dinamis (EMA, RSI, MACD)", "technical")
            self._boot_validate_dashboard_stage(result, "Pemindaian struktur pasar untuk deteksi Order Blocks (OB)", "order_blocks")

            self.call_from_thread(self._boot_log_start, "Penarikan data Sentimen Makro (Fear & Greed, Halving)")
            try:
                result.macro_data = self._fetch_macro_for_boot(result.dashboard_data)
            except Exception as exc:
                result.errors.append(f"Macro intel: {exc}")
                self.call_from_thread(self._boot_log_failed, "Penarikan data Sentimen Makro (Fear & Greed, Halving)", str(exc))
            else:
                self.call_from_thread(self._boot_log_ok, "Penarikan data Sentimen Makro (Fear & Greed, Halving)")

            self.call_from_thread(self._boot_log_start, "Pembuatan Canvas Gambar Piksel Matplotlib")
            try:
                result.chart_png = self._build_boot_chart(result.dashboard_data, result.macro_data)
            except Exception as exc:
                result.errors.append(f"Pixel canvas: {exc}")
                self.call_from_thread(self._boot_log_failed, "Pembuatan Canvas Gambar Piksel Matplotlib", str(exc))
            else:
                self.call_from_thread(self._boot_log_ok, "Pembuatan Canvas Gambar Piksel Matplotlib")

            if not worker.is_cancelled:
                self.call_from_thread(self._boot_finished, result)

        self.run_worker(boot, name="boot", group="boot", exclusive=True, thread=True, exit_on_error=False)

    def _verify_boot_environment(self) -> None:
        base = Path(__file__).resolve().parent
        required = [base / "data_engine.py", base / "pixel_chart.py", base / "macro_intel.py"]
        missing = [path.name for path in required if not path.exists()]
        if missing:
            raise RuntimeError(f"missing: {', '.join(missing)}")
        debug = get_runtime_debug_metadata()
        if not debug.get("smartmoneyconcepts_file"):
            raise RuntimeError("smartmoneyconcepts dependency unavailable")

    def _boot_validate_dashboard_stage(self, result: BootResult, label: str, key: str) -> None:
        self.call_from_thread(self._boot_log_start, label)
        try:
            data = result.dashboard_data or {}
            sections = [data.get("weekly"), data.get("daily")]
            if not sections or any(not isinstance(section, dict) or not section.get(key) for section in sections):
                raise RuntimeError(f"{key} payload unavailable")
        except Exception as exc:
            result.errors.append(f"{label}: {exc}")
            self.call_from_thread(self._boot_log_failed, label, str(exc))
        else:
            self.call_from_thread(self._boot_log_ok, label)

    def _fetch_macro_for_boot(self, data: Payload | None) -> Payload:
        weekly_closes = None
        if data:
            section = data.get("weekly")
            if isinstance(section, dict):
                candles = section.get("candles", [])
                weekly_closes = [c["close"] for c in candles if isinstance(c, dict) and "close" in c]
        try:
            return get_macro_intel(weekly_closes)
        except Exception:
            from btc_investor_tui.macro_intel import get_halving_info, estimate_mvrv_zscore

            return {
                "halving": get_halving_info(),
                "fear_greed": {"value": None, "classification": "unavailable"},
                "mvrv": estimate_mvrv_zscore(weekly_closes) if weekly_closes else {"zscore": None, "zone": "no_data"},
            }

    def _build_boot_chart(self, data: Payload | None, macro_data: Payload | None) -> bytes:
        if not data:
            raise RuntimeError("dashboard data unavailable")
        section = data.get(self.selected_timeframe)
        order_blocks = section.get("order_blocks") if isinstance(section, dict) else None
        return build_dashboard_png(
            data,
            macro_data,
            self.selected_timeframe,
            self.selected_indicator,
            order_blocks if isinstance(order_blocks, dict) else None,
            self.show_ema_fast,
            self.show_ema_slow,
            self.ema_fast_period,
            self.ema_slow_period,
            self.show_rsi,
            self.show_stoch,
            self.rsi_period,
            self.stoch_k,
            self.stoch_d,
            self.stoch_smooth,
            self.macd_fast,
            self.macd_slow,
            self.macd_signal_p,
        )

    def _boot_log_start(self, label: str) -> None:
        self._boot_log(f"[bold white]•[/] [#ffcc00]..[/] {escape(label)}")

    def _boot_log_ok(self, label: str) -> None:
        self._boot_log(f"[bold #00ff88]✓ OK[/] {escape(label)}")

    def _boot_log_failed(self, label: str, message: str) -> None:
        self._boot_log(f"[bold #ff4444]✗ FAILED[/] {escape(label)} [#777777]({escape(message)})[/]")

    def _boot_log(self, markup: str) -> None:
        self.boot_messages.append(markup)
        self.boot_messages = self.boot_messages[-self._BOOT_MESSAGE_LIMIT:]
        try:
            self.query_one("#boot-log", Static).update("\n".join(self.boot_messages))
        except Exception:
            pass

    def _boot_finished(self, result: BootResult) -> None:
        self.dashboard_data = result.dashboard_data
        self.macro_data = result.macro_data
        self.boot_chart_png = result.chart_png
        self.last_error = "; ".join(result.errors) if result.errors and not result.dashboard_data else None
        self._boot_log("[#666666]Preparing dashboard behind boot screen...[/]")
        self._prepare_dashboard_for_reveal()

    def _prepare_dashboard_for_reveal(self) -> None:
        try:
            self._render_dashboard()
        except Exception as exc:
            self._boot_log_failed("Prepare Dashboard", str(exc))
            return
        self._start_boot_transition_countdown()

    def _start_boot_transition_countdown(self) -> None:
        self._boot_transition_remaining = self._BOOT_TRANSITION_SECONDS
        self._boot_log_transition(self._boot_transition_remaining)

        def countdown() -> None:
            worker = get_current_worker()
            while self._boot_transition_remaining > 0:
                time.sleep(1.0)
                if worker.is_cancelled:
                    return
                self.call_from_thread(self._tick_boot_transition_countdown)

        self.run_worker(countdown, name="boot-transition", group="boot-transition", exclusive=True, thread=True, exit_on_error=False)

    def _tick_boot_transition_countdown(self) -> None:
        self._boot_transition_remaining -= 1
        if self._boot_transition_remaining <= 0:
            self._boot_transition_remaining = 0
            self._reveal_dashboard_after_boot()
            return
        self._boot_log_transition(self._boot_transition_remaining)

    def _boot_log_transition(self, seconds_remaining: int) -> None:
        markup = f"[#666666]Dashboard launch in {seconds_remaining}s...[/]"
        if self.boot_messages and self.boot_messages[-1].startswith("[#666666]Dashboard launch in "):
            self.boot_messages[-1] = markup
            try:
                self.query_one("#boot-log", Static).update("\n".join(self.boot_messages))
            except Exception:
                pass
            return
        self._boot_log(markup)

    def _reveal_dashboard_after_boot(self) -> None:
        try:
            self._remove_boot_overlay()
        except Exception as exc:
            self._boot_log_failed("Mount Dashboard", str(exc))

    def _remove_boot_overlay(self) -> None:
        body = self.query_one("#app-body", Vertical)
        self.boot_complete = True
        for boot_panel in list(body.query("#boot-panel")):
            boot_panel.display = False
        body.refresh(layout=True)
        if self.dashboard_data and _get_token():
            self._start_ai_commentary()

    # ─── Actions ──────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._start_refresh("manual")

    def action_ai_refresh(self) -> None:
        if not _get_token():
            self._show_pat_input()
            return
        self._start_ai_commentary()

    def action_toggle_settings(self) -> None:
        panel = self.query_one("#settings-panel")
        panel.toggle_class("visible")

    def action_weekly(self) -> None:
        self.selected_timeframe = "weekly"
        self._render_dashboard()

    def action_daily(self) -> None:
        self.selected_timeframe = "daily"
        self._render_dashboard()

    def action_toggle_indicator(self) -> None:
        self.selected_indicator = "macd" if self.selected_indicator == "rsi" else "rsi"
        self._render_dashboard()

    # ─── Settings event handlers ──────────────────────────────────────────────

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "chk-ema-fast":
            self.show_ema_fast = event.value
        elif event.checkbox.id == "chk-ema-slow":
            self.show_ema_slow = event.value
        elif event.checkbox.id == "chk-rsi":
            self.show_rsi = event.value
        elif event.checkbox.id == "chk-stoch":
            self.show_stoch = event.value
        self._render_plots()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pat-input":
            token = event.value.strip()
            if token:
                save_token(token)
                self._update_status("Token saved permanently")
            event.input.remove()
            self._start_ai_commentary()
            return
        if event.input.id is None:
            return
        self._apply_settings_input(event.input.id, event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        # Only react to settings inputs, ignore during mount/unmount
        if not event.input.id or not event.input.id.startswith("inp-"):
            return
        if not event.value or not event.value.isdigit():
            return
        self._apply_settings_input(event.input.id, event.value)

    def _apply_settings_input(self, input_id: str, value: str) -> None:
        try:
            v = int(value)
            if v < 2:
                return
        except (ValueError, TypeError):
            return
        if input_id == "inp-ema-fast":
            self.ema_fast_period = v
        elif input_id == "inp-ema-slow":
            self.ema_slow_period = v
        elif input_id == "inp-rsi":
            self.rsi_period = v
        elif input_id == "inp-macd-fast":
            self.macd_fast = v
        elif input_id == "inp-macd-slow":
            self.macd_slow = v
        elif input_id == "inp-macd-sig":
            self.macd_signal_p = v
        elif input_id == "inp-stoch-k":
            self.stoch_k = v
        elif input_id == "inp-stoch-d":
            self.stoch_d = v
        elif input_id == "inp-stoch-smooth":
            self.stoch_smooth = v
        else:
            return
        self._recalculate_and_render()

    def _recalculate_and_render(self) -> None:
        """Recalculate indicators from cached candles and re-render instantly."""
        if not self.dashboard_data:
            return
        for tf in ("weekly", "daily"):
            section = self.dashboard_data.get(tf)
            if not isinstance(section, dict):
                continue
            candles = section.get("candles", [])
            if not candles:
                continue
            new_series = recalculate_indicators(
                candles, self.ema_fast_period, self.ema_slow_period,
                self.rsi_period, self.macd_fast, self.macd_slow, self.macd_signal_p,
                self.stoch_k, self.stoch_d, self.stoch_smooth,
            )
            if new_series and "technical" in section:
                section["technical"]["indicator_series"] = new_series
                self._update_latest_indicator_values(section["technical"], new_series)
        self._render_plots()

    def _update_latest_indicator_values(self, technical: Payload, series: Payload) -> None:
        moving = technical.get("moving_averages")
        if not isinstance(moving, dict):
            moving = {}
            technical["moving_averages"] = moving
        moving["ema_20"] = _latest_series_value(series.get("ema_20"))
        moving["ema_50"] = _latest_series_value(series.get("ema_50"))

        oscillators = technical.get("oscillators")
        if not isinstance(oscillators, dict):
            oscillators = {}
            technical["oscillators"] = oscillators
        oscillators["rsi_14"] = _latest_series_value(series.get("rsi_14"))
        oscillators["macd"] = _latest_series_value(series.get("macd"))
        oscillators["macd_signal"] = _latest_series_value(series.get("macd_signal"))
        oscillators["macd_histogram"] = _latest_series_value(series.get("macd_histogram"))

    # ─── Reactive watchers ────────────────────────────────────────────────────

    def watch_ema_fast_period(self, _: int) -> None:
        self._recalculate_and_render()

    def watch_ema_slow_period(self, _: int) -> None:
        self._recalculate_and_render()

    def watch_rsi_period(self, _: int) -> None:
        self._recalculate_and_render()

    def watch_macd_fast(self, _: int) -> None:
        self._recalculate_and_render()

    def watch_macd_slow(self, _: int) -> None:
        self._recalculate_and_render()

    def watch_macd_signal_p(self, _: int) -> None:
        self._recalculate_and_render()

    # ─── Data fetching ────────────────────────────────────────────────────────

    def _show_pat_input(self) -> None:
        try:
            self.query_one("#pat-input", Input)
            return
        except Exception:
            pass
        inp = Input(placeholder="Paste GitHub PAT (models:read)...", id="pat-input")
        self.query_one("#main-scroll").mount(inp, before=self.query_one("#status-strip"))
        inp.focus()

    def _start_refresh(self, reason: str) -> None:
        self.last_error = None
        self._update_status(f"Refreshing ({reason})...")

        def fetch() -> None:
            worker = get_current_worker()
            try:
                data = get_btc_dashboard_data()
            except Exception as exc:
                if not worker.is_cancelled:
                    self.call_from_thread(self._refresh_failed, str(exc))
            else:
                if not worker.is_cancelled:
                    self.call_from_thread(self._refresh_succeeded, data)

        self.run_worker(fetch, name="refresh", group="refresh", exclusive=True, thread=True, exit_on_error=False)

    def _start_ai_commentary(self) -> None:
        if not self.dashboard_data:
            return
        self._update_status("AI commentary request sent; terminal remains live...")
        tf = self.selected_timeframe
        data = self.dashboard_data
        self._ai_request_serial += 1
        request_serial = self._ai_request_serial
        self._ai_active_serial_by_timeframe[tf] = request_serial
        self.ai_commentary_data[tf] = {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": self._AI_CONNECTING_ANALYSIS,
            "commentary": "",
        }
        self._render_ai_analysis()
        self.set_timer(
            self._AI_WATCHDOG_SECONDS,
            lambda tf=tf, serial=request_serial: self._ai_commentary_watchdog(tf, serial),
        )

        def fetch_ai() -> None:
            worker = get_current_worker()
            try:
                section = data.get(tf)
                candles = section.get("candles", []) if isinstance(section, dict) else []
                order_blocks = section.get("order_blocks", {}) if isinstance(section, dict) else {}
                if not candles:
                    commentary = {
                        "buy_zones": [],
                        "sell_zones": [],
                        "analysis": "AI commentary unavailable: no candle data for this timeframe.",
                        "commentary": "",
                    }
                else:
                    commentary = get_order_block_commentary(
                        candles,
                        "1W" if tf == "weekly" else "1D",
                        order_blocks if isinstance(order_blocks, dict) else {},
                    )
            except Exception as exc:
                commentary = {
                    "buy_zones": [],
                    "sell_zones": [],
                    "analysis": f"AI commentary error: {type(exc).__name__}: {exc}",
                    "commentary": "",
                }
            if not worker.is_cancelled:
                self.call_from_thread(self._ai_commentary_received, tf, request_serial, commentary)

        self.run_worker(fetch_ai, name="ai", group="ai", exclusive=True, thread=True, exit_on_error=False)

    def _start_macro_fetch(self) -> None:
        """Fetch macro intel in background."""
        def fetch_macro() -> None:
            worker = get_current_worker()
            weekly_closes = None
            data = self.dashboard_data
            if data:
                section = data.get("weekly")
                if isinstance(section, dict):
                    candles = section.get("candles", [])
                    weekly_closes = [c["close"] for c in candles if "close" in c]
            try:
                data = get_macro_intel(weekly_closes)
            except Exception:
                # Fallback: at least show halving + MVRV (no network needed)
                from btc_investor_tui.macro_intel import get_halving_info, estimate_mvrv_zscore
                data = {
                    "halving": get_halving_info(),
                    "fear_greed": {"value": None, "classification": "unavailable"},
                    "mvrv": estimate_mvrv_zscore(weekly_closes) if weekly_closes else {"zscore": None, "zone": "no_data"},
                }
            if not worker.is_cancelled:
                self.call_from_thread(self._macro_received, data)

        self.run_worker(fetch_macro, name="macro", group="macro", exclusive=True, thread=True, exit_on_error=False)

    def _ai_commentary_watchdog(self, timeframe: str, request_serial: int) -> None:
        if self._ai_active_serial_by_timeframe.get(timeframe) != request_serial:
            return
        commentary = self.ai_commentary_data.get(timeframe, {})
        analysis = str(commentary.get("analysis") or "") if isinstance(commentary, dict) else ""
        if analysis != self._AI_CONNECTING_ANALYSIS:
            return
        self.ai_commentary_data[timeframe] = {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": (
                f"AI commentary still has no response after {int(self._AI_WATCHDOG_SECONDS)}s. "
                "Press A to retry; check token/network if this repeats."
            ),
            "commentary": "",
        }
        self._render_dashboard()
        tf_label = "1W" if timeframe == "weekly" else "1D"
        self._update_status(f"{tf_label} AI commentary timed out locally; press A to retry")

    def _ai_commentary_received(self, timeframe: str, request_serial: int, commentary: Payload) -> None:
        if self._ai_active_serial_by_timeframe.get(timeframe) != request_serial:
            return
        self.ai_commentary_data[timeframe] = commentary
        self._render_dashboard()
        analysis = str(commentary.get("analysis") or "") if isinstance(commentary, dict) else ""
        tf_label = "1W" if timeframe == "weekly" else "1D"
        if (
            analysis.startswith("AI commentary")
            or analysis.startswith("AI connection failed")
            or analysis.startswith("⚠")
        ):
            self._update_status(f"{tf_label} AI commentary unavailable: {analysis}")
        else:
            self._update_status(f"{tf_label} AI commentary ready")

    def _macro_received(self, data: Payload) -> None:
        self.macro_data = data
        self._render_plots()
        self._render_macro()

    def _refresh_succeeded(self, data: Payload) -> None:
        self.dashboard_data = data
        self.last_error = None
        self._render_dashboard()
        if _get_token():
            self._start_ai_commentary()
        self._start_macro_fetch()

    def _refresh_failed(self, message: str) -> None:
        self.last_error = message
        self._render_dashboard()

    # ─── Rendering ────────────────────────────────────────────────────────────

    def _render_dashboard(self) -> None:
        self._render_title()
        self._render_plots()
        self._render_ai_analysis()
        self._render_macro()
        self._render_summary()
        self._render_feed()
        self._render_status()

    def _render_plots(self) -> None:
        order_blocks: Payload | None = None
        if self.dashboard_data:
            section = self.dashboard_data.get(self.selected_timeframe)
            if isinstance(section, dict):
                blocks = section.get("order_blocks")
                order_blocks = blocks if isinstance(blocks, dict) else None
        self.query_one("#price-chart", ImageChartCanvas).set_state(
            self.dashboard_data, self.macro_data, self.selected_timeframe, self.selected_indicator,
            order_blocks, self.show_ema_fast, self.show_ema_slow,
            self.ema_fast_period, self.ema_slow_period, self.show_rsi, self.show_stoch,
            self.rsi_period, self.stoch_k, self.stoch_d, self.stoch_smooth,
            self.macd_fast, self.macd_slow, self.macd_signal_p,
            self.boot_chart_png,
        )
        self.boot_chart_png = None

    def _render_title(self) -> None:
        w = self.query_one("#chart-title", Static)
        if not self.dashboard_data:
            w.update("[bold #ff8c00]BTC INVESTOR[/]  [#666666]waiting...[/]")
            return
        section = self.dashboard_data.get(self.selected_timeframe)
        technical = section.get("technical", {}) if isinstance(section, dict) else {}
        tf = "1W" if self.selected_timeframe == "weekly" else "1D"
        close = _fmt_usd(technical.get("latest_close"))
        signal = _fmt_label(technical.get("composite_signal"))
        w.update(f"[bold #ff8c00]BTC-USDT {tf}[/]  [bold #ffffff]{close}[/]  [bold #00ff88]{escape(signal)}[/]")

    def _render_ai_analysis(self) -> None:
        panel = self.query_one("#ai-analysis", Static)
        if not self.dashboard_data:
            panel.update("[bold #ff8c00]═══ ORDER BLOCKS ═══[/]\n[#666666]Waiting...[/]")
            return
        section = self.dashboard_data.get(self.selected_timeframe)
        blocks = section.get("order_blocks", {}) if isinstance(section, dict) else {}
        if not isinstance(blocks, dict):
            blocks = {}
        commentary = self.ai_commentary_data.get(self.selected_timeframe, {})
        lines = ["[bold #ff8c00]═══ ORDER BLOCKS / AI COMMENTARY ═══[/]"]
        debug = self.dashboard_data.get("runtime_debug") if isinstance(self.dashboard_data, dict) else None
        if isinstance(debug, dict):
            mode = "repo" if debug.get("running_from_project") else "external"
            smc_version = debug.get("smartmoneyconcepts_version") or "missing"
            lines.append(f"[#555555]runtime: {escape(mode)} | smc: {escape(str(smc_version))}[/]")
        unmitigated = blocks.get("unmitigated") if isinstance(blocks.get("unmitigated"), list) else []
        if unmitigated:
            for block in unmitigated[:6]:
                if not isinstance(block, dict):
                    continue
                color = "#00ff88" if block.get("type") == "bullish" else "#ff4444"
                side = "DEMAND" if block.get("type") == "bullish" else "SUPPLY"
                label = escape(str(block.get("origin_date") or ""))
                meta = _format_order_block_meta(block)
                suffix = f" {meta}" if meta else ""
                lines.append(f"  [{color}]█ {side}[/] {_fmt_usd(block.get('price_low'))} - {_fmt_usd(block.get('price_high'))}  [#666]{label}{suffix}[/]")
        else:
            lines.append("[#666666]No recent unmitigated order blocks detected.[/]")
        analysis = commentary.get("analysis", "") if isinstance(commentary, dict) else ""
        if analysis:
            lines.append(f"[#cccccc]{escape(analysis)}[/]")
        elif _get_token():
            lines.append("[#666666]Press A to refresh AI commentary about these blocks.[/]")
        else:
            lines.append("[#666666]Press A to add a token and enable AI commentary.[/]")
        panel.update("\n".join(lines))

    def _render_macro(self) -> None:
        panel = self.query_one("#macro-intel", Static)
        if not self.macro_data:
            panel.update("[bold #ff8c00]═══ MACRO INTEL ═══[/]\n[#666666]Loading...[/]")
            return
        h = self.macro_data.get("halving", {})
        fg = self.macro_data.get("fear_greed", {})
        mv = self.macro_data.get("mvrv", {})

        # Progress bar for halving
        pct = h.get("cycle_progress_pct", 0)
        bar_len = 20
        filled = int(pct / 100 * bar_len)
        bar = f"[#00ff88]{'█' * filled}[/][#333]{'░' * (bar_len - filled)}[/]"

        fng_val = fg.get("value")
        fng_color = "#ff4444" if fng_val and fng_val < 30 else "#00ff88" if fng_val and fng_val > 60 else "#ffcc00"

        lines = [
            "[bold #ff8c00]═══ MACRO INTEL ═══[/]",
            "",
            f" [bold]Halving #5[/]  {bar} {pct:.1f}%",
            f"   Block ~{h.get('current_block_est',0):,} / {h.get('next_halving_block',0):,}  │  [bold]{h.get('days_remaining',0)}d[/] remaining",
            "",
            f" [bold]Fear & Greed[/]  [{fng_color}]{fng_val or 'n/a'}[/] — {fg.get('classification', 'n/a')}",
            "",
            f" [bold]MVRV Z-Score[/]  [bold #00ccff]{mv.get('zscore', 'n/a')}[/]  │  Zone: {escape(str(mv.get('zone', 'n/a')).replace('_', ' ').title())}",
        ]
        panel.update("\n".join(lines))

    def _render_summary(self) -> None:
        panel = self.query_one("#market-summary", Static)
        if not self.dashboard_data:
            panel.update("[bold #ff8c00]MARKET[/]\n[#666666]Waiting...[/]")
            return
        data = self.dashboard_data
        market = data.get("market_summary") or {}
        quote = data.get("quote") or {}
        section = data.get(self.selected_timeframe) or {}
        technical = section.get("technical", {}) if isinstance(section, dict) else {}
        moving = technical.get("moving_averages") or {}
        osc = technical.get("oscillators") or {}

        lines = [
            "[bold #ff8c00]═══ MARKET ═══[/]",
            f" Price  [bold #fff]{_fmt_usd(market.get('price') or quote.get('price'))}[/]  {_fmt_pct(quote.get('change_pct'))}",
            f" Trend  [#ffcc00]{escape(_fmt_label(technical.get('trend_label')))}[/]  Risk [#ff6666]{escape(_fmt_label(technical.get('risk_label')))}[/]",
            f" EMA{self.ema_fast_period} [#fff]{_fmt_usd(moving.get('ema_20'))}[/]  EMA{self.ema_slow_period} [#fff]{_fmt_usd(moving.get('ema_50'))}[/]",
            f" RSI{self.rsi_period} [#00ccff]{_fmt_num(osc.get('rsi_14'))}[/]  MACD({self.macd_fast},{self.macd_slow},{self.macd_signal_p}) [#fff]{_fmt_num(osc.get('macd'))}[/]",
        ]
        panel.update("\n".join(lines))

    def _render_feed(self) -> None:
        feed = self.query_one("#news-section", NewsPanel)
        if not self.dashboard_data:
            text = Text.from_markup("[bold #ff8c00]NEWS[/]\n[#666666]Waiting...[/]")
            feed.update_feed(text, [None, None])
            return
        news = self.dashboard_data.get("news") or {}
        items = news.get("items", []) if isinstance(news, dict) else []
        sentiment = self.dashboard_data.get("reddit_sentiment") or {}
        posts = sentiment.get("top_posts", []) if isinstance(sentiment, dict) else []

        text = Text()
        line_links: list[str | None] = []
        text.append("═══ NEWS ═══\n", style="bold #ff8c00")
        line_links.append(None)
        for i, item in enumerate(items[:6], 1):
            if not isinstance(item, dict):
                continue
            title = _shorten(str(item.get("title") or ""), 110)
            url = str(item.get("url") or "")
            text.append(f" {i} ", style="bold #ffffff")
            text.append(f"{title}\n", style=f"underline link {url}" if url.startswith("http") else "")
            line_links.append(url if url.startswith("http") else None)

        text.append("\n═══ REDDIT ═══\n", style="bold #ff8c00")
        line_links.extend([None, None])
        sentiment_label = str(sentiment.get("sentiment_label") or "unavailable") if isinstance(sentiment, dict) else "unavailable"
        posts_analyzed = sentiment.get("posts_analyzed") if isinstance(sentiment, dict) else 0
        text.append(f" sentiment: {sentiment_label} | posts: {posts_analyzed or 0}\n", style="#888888")
        line_links.append(None)
        if posts:
            for post in posts[:3]:
                if not isinstance(post, dict):
                    continue
                title = _shorten(str(post.get("title") or ""), 80)
                url = str(post.get("url") or "")
                text.append(f" {title}\n", style=f"underline link {url}" if url.startswith("http") else "")
                line_links.append(url if url.startswith("http") else None)
        else:
            error = sentiment.get("error") if isinstance(sentiment, dict) else None
            message = f"Reddit unavailable: {error}" if error else "No Reddit posts returned right now."
            text.append(f" {message}\n", style="#666666")
            line_links.append(None)

        if not items and not posts:
            text.append("No news available\n", style="#666666")
            line_links.append(None)

        feed.update_feed(text, line_links)

    def _render_status(self) -> None:
        if self.last_error:
            self._update_status(f"ERR: {self.last_error}")
            return
        if not self.dashboard_data:
            return
        tf = "1W" if self.selected_timeframe == "weekly" else "1D"
        ind = self.selected_indicator.upper()
        self._update_status(f"{tf} | {ind} | EMA{self.ema_fast_period}/{self.ema_slow_period} | R A P W D I Q")

    def _update_status(self, msg: str) -> None:
        self.query_one("#status-strip", Static).update(f"[bold #ff8c00]▶[/] {escape(msg)}")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _format_order_block_meta(block: Payload) -> str:
    parts: list[str] = []
    age = block.get("age_candles")
    distance = block.get("distance_pct")
    if isinstance(age, int):
        parts.append(f"{age} bars")
    distance_value = float(distance) if isinstance(distance, (int, float, str)) else math.nan
    if math.isfinite(distance_value):
        parts.append(f"{distance_value * 100:.0f}% away")
    return f"({' · '.join(parts)})" if parts else ""


def _fmt_usd(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return f"${n:,.0f}" if math.isfinite(n) else "n/a"


def _fmt_pct(v: Any) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(n):
        return ""
    c = "#00ff88" if n >= 0 else "#ff4444"
    return f"[bold {c}]{n:+.2f}%[/]"


def _fmt_num(v: Any, d: int = 2) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return f"{n:,.{d}f}" if math.isfinite(n) else "n/a"


def _latest_series_value(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    for value in reversed(values):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _fmt_label(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, dict):
        label = str(v.get("label") or "n/a")
        score = v.get("score")
        s = label.replace("_", " ").title()
        return f"{s} ({score:+d})" if score is not None else s
    return str(v).replace("_", " ").title()


def _shorten(s: str, limit: int) -> str:
    t = " ".join(s.split())
    return t if len(t) <= limit else f"{t[:limit-3].rstrip()}..."


def _link_from_click(event: Click, panel: NewsPanel) -> str | None:
    style = event.style
    if style is not None and style.link and style.link.startswith("http"):
        return style.link
    offset = event.get_content_offset(panel)
    if offset is None:
        return None
    return panel.link_at_line(offset.y)


def main() -> None:
    BTCInvestorApp().run()


if __name__ == "__main__":
    main()

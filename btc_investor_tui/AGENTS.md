# BTC TUI KNOWLEDGE BASE

**Generated:** 2026-05-17 10:30:16 Asia/Jakarta
**Parent:** `../AGENTS.md`

## OVERVIEW

Standalone Textual terminal app for long-term BTC investors. It shares data services with `tradingview_mcp`, but it is not an MCP tool surface.

## STRUCTURE

```text
btc_investor_tui/
|-- app.py            # Textual app, CSS, reactive settings, worker orchestration
|-- data_engine.py    # Yahoo/yfinance candles, TA, news, Reddit, macro aggregation
|-- chart_renderer.py # plotille Braille candlesticks, EMAs, AI zone bands, indicators
|-- ai_zones.py       # GitHub Models JSON-only buy/sell zone analysis
|-- macro_intel.py    # halving, Fear & Greed, MVRV estimate
`-- __init__.py
```

## WHERE TO LOOK

| Task | Location | Notes |
|---|---|---|
| Keybindings/layout/style | `app.py` | `BTCInvestorApp.BINDINGS` and inline `CSS`. |
| Dashboard refresh flow | `app.py` | `_start_refresh`, `_refresh_succeeded`, `_render_dashboard`. |
| Settings panel | `app.py` | Reactive fields plus `_apply_settings_input`. |
| Candle/indicator data | `data_engine.py` | `get_btc_dashboard_data`, `recalculate_indicators`. |
| Terminal chart output | `chart_renderer.py` | ANSI/Braille strings via plotille canvas. |
| AI zone analysis | `ai_zones.py` | GitHub Models endpoint, token loading, JSON parsing. |
| Macro panel | `macro_intel.py` | Local halving math and external Fear & Greed data. |

## CONVENTIONS

- Display symbol is `BTC-USDT`; Yahoo source symbol is `BTC-USD`.
- `data_engine.py` inserts repo `src/` into `sys.path` so it can import MCP service modules when run as a script.
- Textual workers use `exclusive=True` groups for refresh, AI, and macro fetches; keep network work off the UI thread.
- Thread workers must publish UI changes through Textual-safe callbacks such as `call_from_thread`; cancellation is cooperative, so check worker cancellation before applying stale results.
- Renderer functions return strings; widgets call `Text.from_ansi` or `Text(...)` to display them.
- Settings changes recalculate indicators from existing candles instead of refetching network data.

## ANTI-PATTERNS

- Do not register MCP tools here.
- Do not move UI formatting into `tradingview_mcp/core/services`.
- Do not block Textual event handlers with network calls; use worker helpers.
- Do not assume `GITHUB_TOKEN` exists. The current UX can prompt and save `.github_pat` at repo root.
- Do not replace Braille/ANSI chart output with web or matplotlib assumptions.
- Do not use `recompose=True` casually around stateful widgets like `Input`; preserve user-entered state in settings flows.

## COMMANDS

```bash
./.venv/bin/python btc_investor_tui/app.py
uv run python btc_investor_tui/app.py
```

## NOTES

- README is primarily TUI-focused and includes Indonesian copy.
- `pyproject.toml` runtime deps do not list all TUI imports seen here (`textual`, `plotille`, `pandas`, `yfinance`, `ta`); `uv.lock` does.
- `ai_zones.py` asks GitHub Models for strict JSON but strips markdown fences defensively before `json.loads`.

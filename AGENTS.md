# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-17 10:30:16 Asia/Jakarta
**Commit:** 8fd9095
**Branch:** main

## OVERVIEW

Python MCP server for TradingView/Yahoo-backed market analysis, plus a separate Textual BTC investor terminal. Core server exposes FastMCP tools; business logic lives in service modules, not in MCP handlers.

## STRUCTURE

```text
tradingview-mcp/
|-- pyproject.toml              # package metadata, uv dependency groups, console script
|-- README.md                   # currently documents the BTC TUI more than the MCP package
|-- src/tradingview_mcp/
|   |-- server.py               # FastMCP tool/resource registry and CLI transport entrypoint
|   |-- coinlist/*.txt          # packaged exchange symbol lists
|   `-- core/
|       |-- services/           # market, TA, news, sentiment, backtest business logic
|       |-- utils/validators.py # exchange/timeframe/symbol canonicalization
|       |-- data/               # EGX static sectors/indices
|       `-- types.py            # shared row/indicator helpers
`-- btc_investor_tui/           # standalone Bloomberg-style BTC Textual app
```

## WHERE TO LOOK

| Task | Location | Notes |
|---|---|---|
| Add/modify MCP tool | `src/tradingview_mcp/server.py` | Handler sanitizes/clamps, then delegates. |
| Add market logic | `src/tradingview_mcp/core/services/` | Read child `AGENTS.md` first. |
| Change exchange aliases | `src/tradingview_mcp/core/utils/validators.py` | Keep Yahoo symbols and TradingView prefixes separate. |
| Update packaged symbols | `src/tradingview_mcp/coinlist/*.txt` | `pyproject.toml` packages these as `tradingview_mcp = ["coinlist/*.txt"]`. |
| EGX mappings | `src/tradingview_mcp/core/data/egx_indices.py`, `egx_sectors.py` | Static market metadata used by EGX services. |
| Portfolio persistence | `src/tradingview_mcp/core/portfolio.py` | Local SQLite state in `~/.tradingview_mcp_data/`; isolated from main MCP flow. |
| BTC terminal UI | `btc_investor_tui/app.py` | Textual reactive app; read child `AGENTS.md`. |
| BTC data aggregation | `btc_investor_tui/data_engine.py` | Imports MCP service modules via local `src` insertion. |

## CODE MAP

| Symbol | Type | Location | Role |
|---|---|---|---|
| `mcp` | `FastMCP` | `src/tradingview_mcp/server.py:73` | Server instance and tool registry. |
| `main()` | function | `src/tradingview_mcp/server.py:695` | CLI: `stdio` default, `streamable-http` optional. |
| `top_gainers`..`stock_extended_hours` | MCP tools | `src/tradingview_mcp/server.py` | 30+ tool handlers; keep as routing layer. |
| `resilient_get_multiple_analysis` | function | `core/services/screener_provider.py:157` | TradingView TA retry/cache/throttle shim. |
| `fetch_screener_indicators` | function | `core/services/screener_provider.py:221` | tradingview-screener query adapter. |
| `run_backtest` | function | `core/services/backtest_service.py:345` | Yahoo-backed strategy backtests. |
| `walk_forward_backtest` | function | `core/services/backtest_service.py:481` | Overfitting check across folds. |
| `BTCInvestorApp` | Textual app | `btc_investor_tui/app.py:112` | TUI state, keybindings, rendering orchestration. |
| `get_btc_dashboard_data` | function | `btc_investor_tui/data_engine.py:297` | BTC quote/candles/news/macro aggregation. |

## CONVENTIONS

- Source layout is `src/`; console script is `tradingview-mcp = "tradingview_mcp.server:main"`.
- `server.py` docstring is policy: validate/sanitize parameters, call services, return payloads.
- Timeframes normalize to exactly `5m`, `15m`, `1h`, `4h`, `1D`, `1W`, `1M` in `validators.py`.
- Stock exchange identifiers are lower-case internally; TradingView prefixes are uppercase and sometimes alias-specific (`nysearca` -> `AMEX`).
- BTC TUI is not packaged in `pyproject.toml`; README run path is `./.venv/bin/python btc_investor_tui/app.py`.
- `README.md` describes the BTC terminal; `pyproject.toml` describes the MCP server. Treat them as currently divergent, not interchangeable.
- `mcp[cli]` is locked around 1.12.x; verify newer FastMCP docs/API examples exist in the locked version before copying them.

## ANTI-PATTERNS (THIS PROJECT)

- Do not put computation in `server.py`; add or update service functions instead.
- Do not read `coinlist/*.txt` ad hoc from feature code; use `core/services/coinlist.py`.
- Do not bypass `screener_provider.py` for TradingView batch calls; it owns retry/cache/throttle behavior.
- Do not treat `BTC-USDT` display symbols and Yahoo `BTC-USD` symbols as the same contract.
- Do not commit `.github_pat`; the TUI writes it at repo root for local GitHub Models access.
- Do not turn existing `{ "error": ... }` payloads into FastMCP protocol errors unless intentionally migrating client contracts.

## UNIQUE STYLES

- Market payloads are plain `dict`/`list` structures, not framework objects.
- Live-network paths usually degrade to `{ "error": ... }` payloads instead of raising through MCP tools.
- Service modules use broad upstream exception handling around provider calls; avoid widening it outside provider boundaries.
- TUI uses dark Bloomberg/TradingView terminal styling and Braille charts, not web UI patterns.

## COMMANDS

```bash
uv sync
uv pip install -e .
uv run tradingview-mcp
uv run tradingview-mcp streamable-http --host 127.0.0.1 --port 8000
uv run pytest
./.venv/bin/python btc_investor_tui/app.py
```

## NOTES

- No `tests/` directory is present in this checkout; existing service AGENTS test commands reference expected future/adjacent tests.
- `uv.lock` contains packages beyond declared runtime deps, including TUI/data-analysis libraries used by `btc_investor_tui`.
- `README.md` says Python 3.12+, while `pyproject.toml` requires `>=3.10`; preserve the distinction until reconciled.
- No CI workflow, lint config, typecheck config, Dockerfile, Makefile, or Nix files were found in this checkout.
- External calls hit TradingView, Yahoo Finance, RSS feeds, Reddit, alternative.me, CoinGecko, and GitHub Models depending on surface.

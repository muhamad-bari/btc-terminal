# AGENTS.md

## Scope

Applies to `src/tradingview_mcp/core/services`.

## Service layer role

- This directory contains the business logic behind MCP tools.
- `server.py` should only sanitize parameters and call these functions.
- Service functions should accept normalized inputs and return plain `dict`, `list`, or typed row payloads.
- Do not register MCP tools here.
- Do not add UI, CLI, or OpenClaw-specific formatting here.

## Shared dependencies

- Use `core/utils/validators.py` for exchange, timeframe, Yahoo symbol, and TradingView symbol normalization.
- Load static symbol lists through `coinlist.load_symbols`; do not read `coinlist/*.txt` ad hoc.
- Use EGX static maps from `core/data/egx_sectors.py` and `core/data/egx_indices.py`.
- Use `proxy_manager.build_opener_with_proxy` for urllib flows that need proxy support.

## TradingView access

- Do not call `tradingview_ta.get_multiple_analysis` directly from feature services.
- Use `screener_provider.resilient_get_multiple_analysis` or related screener-provider helpers.
- Preserve retry, cache, throttle, and semaphore behavior in `screener_provider.py`.
- If editing throttle code, pair `_ta_throttle_acquire()` with `_ta_throttle_release()` in a `finally` block.
- Relevant env knobs: `TRADINGVIEW_MCP_CACHE_TTL`, `TRADINGVIEW_MCP_RETRY_DELAYS`, `TRADINGVIEW_MCP_MAX_INFLIGHT`, `TRADINGVIEW_MCP_MIN_INTERVAL_S`.

## Module map

- `screener_service.py`: generic multi-exchange TA and scan orchestration.
- `screener_provider.py`: resilient TradingView fetch/cache/throttle shim.
- `scanner_service.py`: volume breakout and confirmation scans.
- `multi_agent_service.py`: consensus, risk, and sentiment scoring pipeline.
- `egx_service.py`: EGX market, sector, index, stock, trade plan, and Fibonacci workflows.
- `indicators.py`: TA extraction, scoring, trade setup, Fibonacci interpretation.
- `indicators_calc.py`: pure math indicators used by backtesting.
- `backtest_service.py`: Yahoo-backed strategy tests, comparisons, and walk-forward runs.
- `yahoo_finance_service.py`, `extended_hours_service.py`: Yahoo market data access.
- `sentiment_service.py`, `news_service.py`, `bitcoin_market_service.py`: external content and market context.
- `proxy_manager.py`: env/local `.env` proxy configuration only.

## Backtesting

- `backtest_service.py` is Yahoo-backed and separate from TradingView TA flows.
- Supported strategies include `rsi`, `bollinger`, `macd`, `ema_cross`, `supertrend`, and `donchian`.
- Keep supported periods to the current contract unless intentionally changing tests/docs: `1mo`, `3mo`, `6mo`, `1y`, `2y`.
- Keep supported intervals to `1d` and `1h` unless intentionally changing tests/docs.

## Hotspots

- Treat `egx_service.py`, `indicators.py`, `screener_service.py`, `screener_provider.py`, and `backtest_service.py` as high-risk modules.
- When changing a hotspot, read the calling server tool and adjacent tests first.
- Prefer adding focused helpers over expanding already-large orchestration functions.

## Test expectations

- Exchange and symbol changes must run `uv run pytest tests/unit/test_exchange_aliases.py`.
- Validator changes must run `uv run pytest tests/unit/test_validators.py`.
- Avoid live-network unit tests; isolate pure normalization, scoring, and transformation behavior.

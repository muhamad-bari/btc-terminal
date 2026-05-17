# SERVICES KNOWLEDGE BASE

**Generated:** 2026-05-17 10:30:16 Asia/Jakarta
**Parent:** `../../../AGENTS.md`

## OVERVIEW

Business logic behind the MCP tools. `server.py` should sanitize inputs and call here; this layer returns plain payloads and owns provider-specific quirks.

## SERVICE LAYER ROLE

- This directory contains the business logic behind MCP tools.
- `server.py` should only sanitize parameters and call these functions.
- Service functions should accept normalized inputs and return plain `dict`, `list`, or typed row payloads.
- Do not register MCP tools here.
- Do not add UI, CLI, TUI, or OpenClaw-specific formatting here.

## WHERE TO LOOK

| Task | Location | Notes |
|---|---|---|
| TradingView batch access | `screener_provider.py` | Retry/cache/throttle wrapper; safest entry for provider calls. |
| Generic TA scans | `screener_service.py` | Multi-exchange Bollinger, trend, candle, MTF analysis. |
| Volume scanners | `scanner_service.py` | Breakouts, confirmation, smart volume. |
| EGX workflows | `egx_service.py` | Market overview, sectors, index, screener, trade plans, Fibonacci. |
| TA extraction/scoring | `indicators.py` | Large hotspot: extended indicators, stock score, setup quality, Fibonacci. |
| Pure math indicators | `indicators_calc.py` | EMA/SMA/RSI/Bollinger/MACD/ATR/Supertrend/Donchian. |
| Backtesting | `backtest_service.py` | Yahoo OHLCV, strategies, metrics, walk-forward. |
| Yahoo quotes | `yahoo_finance_service.py`, `extended_hours_service.py` | Market snapshot, price, pre/post-market. |
| External context | `sentiment_service.py`, `news_service.py`, `bitcoin_market_service.py` | Reddit/RSS/crypto macro. |
| Proxy support | `proxy_manager.py` | Env/local `.env` proxy configuration only. |

## SHARED DEPENDENCIES

- Use `core/utils/validators.py` for exchange, timeframe, Yahoo symbol, and TradingView symbol normalization.
- Load static symbol lists through `coinlist.load_symbols`; do not read `coinlist/*.txt` ad hoc.
- Use EGX static maps from `core/data/egx_sectors.py` and `core/data/egx_indices.py`.
- Use `proxy_manager.build_opener_with_proxy` for urllib flows that need proxy support.

## TRADINGVIEW ACCESS

- Do not call `tradingview_ta.get_multiple_analysis` directly from feature services.
- Use `screener_provider.resilient_get_multiple_analysis` or related screener-provider helpers.
- Preserve retry, cache, throttle, and semaphore behavior in `screener_provider.py`.
- If editing throttle code, pair `_ta_throttle_acquire()` with `_ta_throttle_release()` in a `finally` block.
- `tradingview-ta` is not historical-data API; keep historical/backtest flows on Yahoo-backed services.
- `tradingview-screener` queries are load-sensitive and can be delayed without realtime cookies; keep local limits/batching.
- Relevant env knobs: `TRADINGVIEW_MCP_CACHE_TTL`, `TRADINGVIEW_MCP_RETRY_DELAYS`, `TRADINGVIEW_MCP_MAX_INFLIGHT`, `TRADINGVIEW_MCP_MIN_INTERVAL_S`.

## EXTERNAL DATA GOTCHAS

- Yahoo chart/quote endpoints are unofficial and can return null/missing OHLC rows; filter invalid candles before metrics.
- `extended_hours_service.py` depends on `includePrePost`, `currentTradingPeriod`, and short-interval Yahoo candles.
- `news_service.py` preserves feed-specific workarounds: Reuters RSS is deprecated here, and Yahoo/CNBC need browser-like `User-Agent` headers.
- Proxy credentials belong in env/local `.env`; never hardcode them in services or docs.

## MODULE MAP

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
- `proxy_manager.py`: env/local `.env` proxy configuration only; used by urllib paths needing proxy fallback.

## BACKTESTING

- `backtest_service.py` is Yahoo-backed and separate from TradingView TA flows.
- Supported strategies include `rsi`, `bollinger`, `macd`, `ema_cross`, `supertrend`, and `donchian`.
- Keep supported periods to the current contract unless intentionally changing tests/docs: `1mo`, `3mo`, `6mo`, `1y`, `2y`.
- Keep supported intervals to `1d` and `1h` unless intentionally changing tests/docs.

## HOTSPOTS

- Treat `egx_service.py`, `indicators.py`, `screener_service.py`, `screener_provider.py`, and `backtest_service.py` as high-risk modules.
- When changing a hotspot, read the calling server tool and adjacent tests first.
- Prefer adding focused helpers over expanding already-large orchestration functions.

## TEST EXPECTATIONS

- Exchange and symbol changes must run `uv run pytest tests/unit/test_exchange_aliases.py`.
- Validator changes must run `uv run pytest tests/unit/test_validators.py`.
- Avoid live-network unit tests; isolate pure normalization, scoring, and transformation behavior.

## NOTES

- This checkout has no `tests/` directory; if tests are absent, run focused import/compile checks and document the gap.
- `screener_provider.py` intentionally catches broad provider exceptions but re-raises non-transient errors.
- `egx_service.py` and `screener_service.py` batch provider calls; preserve limit clamps in `server.py` when changing them.

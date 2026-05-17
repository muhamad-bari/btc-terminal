# BTC Investor Terminal

Bloomberg-style Bitcoin terminal dashboard untuk investor, dibangun dengan Python + Textual TUI.

![Python](https://img.shields.io/badge/python-3.12+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

```
┌─────────────────────────────────────────────────────────────────┐
│  BTC-USDT 1W  $78,123  Strong Bullish (+3)                      │
├─────────────────────────────────────────────────────────────────┤
│  ⣿⣷⣾⡆    ⣿⣿⢹⢹⣿⢰⣷⣾⡆         Candlestick + EMA overlay  │
│  ⢿⢧⡤⡄⡄⣿⡇⠙⢹⣿⣇⣿⢹⢹⣿⢰⣷⣾⡆     + AI Buy/Sell zones       │
├─────────────────────────────────────────────────────────────────┤
│  RSI14 ── 70 ── 30          │  ═══ MARKET ═══               │
│  Stochastic %K %D            │  Price  $78,123  -1.2%        │
├─────────────────────────────────────────────────────────────────┤
│  ═══ AI ZONES ═══            │  ═══ BLOOMBERG MACRO ═══      │
│  █ BUY  $72,000 - $74,000   │  Halving #5  ████░░░░  58%   │
│  █ SELL $85,000 - $87,000   │  Fear & Greed  27 — Fear      │
│                              │  MVRV Z-Score  0.52           │
├─────────────────────────────────────────────────────────────────┤
│  ═══ NEWS ═══                                                   │
│  1 Gold Falls Toward $4,550 as Fed-Cut Hopes Fade               │
│  2 Bitcoin ETF Inflows Hit Record...                            │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Candlestick Chart** — High-density Braille rendering (plotille), EMA overlay, AI zone bands
- **Dynamic Indicators** — RSI, Stochastic (5,3,3), MACD, semua parameter bisa di-custom live
- **AI Buy/Sell Zones** — Analisis via GitHub Models API (GPT-4.1-mini), spot trading only
- **Bloomberg Macro Intel** — Halving countdown, Fear & Greed Index, MVRV Z-Score
- **News & Reddit** — RSS headlines + Reddit sentiment, clickable links (Ctrl+Click)
- **Settings Panel** — Toggle & customize semua indikator tanpa restart (hotkey `P`)
- **Scrollable** — Semua section bisa di-scroll

## Keybindings

| Key | Action |
|-----|--------|
| `R` | Refresh data |
| `A` | AI zone analysis (input PAT jika belum ada) |
| `P` | Toggle settings panel |
| `W` | Weekly timeframe |
| `D` | Daily timeframe |
| `I` | Toggle RSI/Stoch ↔ MACD |
| `Q` | Quit |

## Installation

```bash
# Clone
git clone https://github.com/muhamad-bari/btc-terminal.git
cd btc-terminal

# Setup lokal
uv venv
uv pip install .
# development
uv pip install -e .

# Run
btc-tui
```

Setelah `uv pip install -e .`, command `btc-tui` tersedia di virtualenv project (`.venv/bin/btc-tui`). Kalau shell belum otomatis memakai `.venv/bin`, jalankan salah satu:

```bash
source .venv/bin/activate
#fish
source .venv/bin/activate.fish
btc-tui

# atau tanpa activate
./.venv/bin/btc-tui
```

### Install sebagai command global

Jika ingin bisa mengetik `btc-tui` dari terminal mana saja setelah pindah PC/install baru:

```bash
git clone https://github.com/muhamad-bari/btc-terminal.git
cd btc-terminal
uv tool install .
btc-tui
```

Pastikan folder binary `uv tool` sudah ada di `PATH`. Jika belum, jalankan `uv tool update-shell` lalu buka terminal baru.

## AI Zones Setup

Untuk fitur AI buy/sell zone analysis, butuh GitHub Personal Access Token dengan scope `models:read`:

1. Buat PAT di https://github.com/settings/tokens
2. Jalankan app, tekan `A`, paste token
3. Token otomatis tersimpan di `.github_pat` (gitignored)

Atau set environment variable:
```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
```

## Indicator Settings

Tekan `P` untuk buka panel settings:

| Indicator | Default | Customizable |
|-----------|---------|--------------|
| EMA Fast | 20 | ✓ (toggle + period) |
| EMA Slow | 50 | ✓ (toggle + period) |
| RSI | 14 | ✓ (toggle + period) |
| Stochastic | 5,3,3 | ✓ (toggle + K/D/Smooth) |
| MACD | 12,26,9 | ✓ (Fast/Slow/Signal) |

Perubahan parameter langsung re-render chart tanpa fetch ulang data.

## Data Sources

| Data | Source |
|------|--------|
| Price & OHLCV | Yahoo Finance (yfinance) |
| Fear & Greed | alternative.me API |
| News | RSS feeds (Yahoo Finance, CoinDesk) |
| Reddit Sentiment | Reddit API |
| AI Analysis | GitHub Models (GPT-4.1-mini) |
| Halving/MVRV | Calculated locally |

## Tech Stack

- **TUI Framework**: [Textual](https://textual.textualize.io/)
- **Charts**: [plotille](https://github.com/tammoippen/plotille) (Braille Unicode)
- **Indicators**: [ta-lib](https://github.com/bukosabino/ta) (EMA, RSI, MACD, Stochastic, Bollinger)
- **Data**: [yfinance](https://github.com/ranaroussi/yfinance)
- **AI**: GitHub Models API

## Structure

```
btc_investor_tui/
├── app.py            # Textual TUI app, reactive state, UI layout
├── chart_renderer.py # Plotille Braille chart rendering
├── data_engine.py    # Yahoo Finance data + indicator calculation
├── ai_zones.py       # GitHub Models AI buy/sell zone analysis
└── macro_intel.py    # Halving tracker, Fear&Greed, MVRV Z-Score
```

## License

MIT

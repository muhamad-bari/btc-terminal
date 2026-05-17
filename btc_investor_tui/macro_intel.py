"""Bloomberg-style macro intelligence module.

Provides:
- Bitcoin Halving Tracker (block-based countdown)
- Crypto Fear & Greed Index (alternative.me API)
- MVRV Z-Score estimation
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ─── Halving Tracker ──────────────────────────────────────────────────────────
# Bitcoin halves every 210,000 blocks. Known halvings:
#   0: block 0       (2009-01-03)
#   1: block 210000  (2012-11-28)
#   2: block 420000  (2016-07-09)
#   3: block 630000  (2020-05-11)
#   4: block 840000  (2024-04-20)
#   5: block 1050000 (~2028)

_HALVING_INTERVAL = 210_000
_LAST_HALVING_BLOCK = 840_000
_LAST_HALVING_DATE = datetime(2024, 4, 20, tzinfo=timezone.utc)
_NEXT_HALVING_BLOCK = 1_050_000
_AVG_BLOCK_TIME_MINUTES = 10.0


def get_halving_info() -> dict[str, Any]:
    """Estimate days until next halving and cycle progress."""
    now = datetime.now(timezone.utc)
    minutes_since_last = (now - _LAST_HALVING_DATE).total_seconds() / 60
    blocks_since_last = int(minutes_since_last / _AVG_BLOCK_TIME_MINUTES)
    current_block_est = _LAST_HALVING_BLOCK + blocks_since_last
    blocks_remaining = max(0, _NEXT_HALVING_BLOCK - current_block_est)
    days_remaining = int(blocks_remaining * _AVG_BLOCK_TIME_MINUTES / 1440)
    progress_pct = round(blocks_since_last / _HALVING_INTERVAL * 100, 1)

    return {
        "current_block_est": current_block_est,
        "next_halving_block": _NEXT_HALVING_BLOCK,
        "blocks_remaining": blocks_remaining,
        "days_remaining": days_remaining,
        "cycle_progress_pct": min(100.0, progress_pct),
        "halving_number": 5,
    }


# ─── Fear & Greed Index ───────────────────────────────────────────────────────

_FNG_URL = "https://api.alternative.me/fng/?limit=1"


def get_fear_greed() -> dict[str, Any]:
    """Fetch Crypto Fear & Greed Index from alternative.me."""
    try:
        req = urllib.request.Request(_FNG_URL, headers={"User-Agent": "btc-investor-tui/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        entry = data["data"][0]
        return {
            "value": int(entry["value"]),
            "classification": entry["value_classification"],
            "timestamp": entry.get("timestamp"),
        }
    except Exception as e:
        return {"value": None, "classification": "unavailable", "error": str(e)}


# ─── MVRV Z-Score Estimation ─────────────────────────────────────────────────
# Simplified estimation based on price vs 200-week SMA as proxy.
# Real MVRV requires on-chain realized cap data (paid APIs).
# This uses: Z ≈ (market_price - 200w_sma) / std_dev(price)


def estimate_mvrv_zscore(closes: list[float]) -> dict[str, Any]:
    """Estimate MVRV Z-Score proxy from weekly closes.

    Uses (price - 200w_mean) / 200w_std as approximation.
    Requires at least 200 weekly closes.
    """
    if len(closes) < 200:
        return {"zscore": None, "zone": "insufficient_data", "note": "Need 200+ weekly closes"}

    window = closes[-200:]
    mean = sum(window) / len(window)
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    std = variance ** 0.5
    current = closes[-1]

    if std == 0:
        return {"zscore": 0.0, "zone": "neutral"}

    zscore = round((current - mean) / std, 2)

    if zscore >= 7:
        zone = "EXTREME_OVERVALUED"
    elif zscore >= 4:
        zone = "OVERVALUED"
    elif zscore >= 2:
        zone = "ELEVATED"
    elif zscore >= -0.5:
        zone = "FAIR_VALUE"
    elif zscore >= -2:
        zone = "UNDERVALUED"
    else:
        zone = "EXTREME_UNDERVALUED"

    return {"zscore": zscore, "zone": zone, "mean_200w": round(mean, 2), "std_200w": round(std, 2)}


def get_macro_intel(weekly_closes: list[float] | None = None) -> dict[str, Any]:
    """Aggregate all macro intelligence data."""
    halving = get_halving_info()
    fng = get_fear_greed()
    mvrv = estimate_mvrv_zscore(weekly_closes) if weekly_closes else {"zscore": None, "zone": "no_data"}

    return {
        "halving": halving,
        "fear_greed": fng,
        "mvrv": mvrv,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

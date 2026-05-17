"""AI-powered buy/sell zone analysis via GitHub Models API."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

_ENDPOINT = "https://models.github.ai/inference/chat/completions"
_MODEL = "openai/gpt-4.1-mini"
_TIMEOUT = 30
_PAT_FILE = Path(__file__).resolve().parent.parent / ".github_pat"


def _get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or ""
    if not token:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or ""
        except ImportError:
            pass
    if not token and _PAT_FILE.exists():
        token = _PAT_FILE.read_text().strip()
    return token


def save_token(token: str) -> None:
    """Persist token to local file for reuse across sessions."""
    _PAT_FILE.write_text(token)
    os.environ["GITHUB_TOKEN"] = token


def get_ai_zones(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    """Call GitHub Models API to get buy/sell zones based on candle data.

    Returns dict with keys: buy_zones, sell_zones, analysis
    Each zone: {start_idx, end_idx, price_low, price_high}
    """
    token = _get_token()
    if not token:
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": "⚠ Set GITHUB_TOKEN env var with models:read scope to enable AI zone analysis.",
        }

    # Send last 60 candles for context
    recent = candles[-60:] if len(candles) > 60 else candles
    candle_summary = [
        {"d": c["date"], "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}
        for c in recent
    ]

    prompt = f"""You are a professional spot trading analyst. Analyze these BTC-USD {timeframe} candles and identify buy zones and sell zones.

Rules:
- Spot trading only (no leverage/shorts)
- Buy zones: price ranges where accumulation is favorable (support, oversold, demand zones)
- Sell zones: price ranges where taking profit is favorable (resistance, overbought, supply zones)
- Use the LAST 60 candles context, but zones should be relevant to CURRENT price action
- Return 1-3 buy zones and 1-3 sell zones

Candles (date, open, high, low, close):
{json.dumps(candle_summary)}

Respond ONLY with valid JSON (no markdown, no explanation outside JSON):
{{
  "buy_zones": [{{"price_low": number, "price_high": number, "label": "short reason"}}],
  "sell_zones": [{{"price_low": number, "price_high": number, "label": "short reason"}}],
  "analysis": "2-4 sentences explaining your reasoning for these zones"
}}"""

    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 800,
    }

    req = urllib.request.Request(
        _ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        result = json.loads(content)
        return {
            "buy_zones": result.get("buy_zones", []),
            "sell_zones": result.get("sell_zones", []),
            "analysis": result.get("analysis", "No analysis provided."),
        }
    except Exception as e:
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": f"AI analysis error: {type(e).__name__}: {e}",
        }

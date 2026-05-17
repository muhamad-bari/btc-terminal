"""AI commentary for deterministic BTC order blocks via GitHub Models API."""

from __future__ import annotations

import json
import importlib
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
            load_dotenv = importlib.import_module("dotenv").load_dotenv
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


def get_order_block_commentary(
    candles: list[dict[str, Any]],
    timeframe: str,
    order_blocks: dict[str, Any],
) -> dict[str, Any]:
    """Return AI commentary about deterministic order blocks only."""
    token = _get_token()
    if not token:
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": "⚠ Set GITHUB_TOKEN env var with models:read scope to enable AI order block commentary.",
            "commentary": "",
        }

    recent = candles[-60:] if len(candles) > 60 else candles
    candle_summary = [
        {"d": c["date"], "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}
        for c in recent
    ]
    block_summary = _summarize_order_blocks(order_blocks)

    prompt = f"""You are a professional spot BTC market analyst. The order blocks below were detected locally by deterministic volume-pivot logic. Do not invent, alter, add, or remove zones.

Rules:
- Spot trading only (no leverage/shorts)
- Discuss only the provided deterministic BTC-USD {timeframe} order blocks
- Prefer recent unmitigated blocks when describing relevance
- Mention mitigation status plainly when useful
- Do not output buy_zones or sell_zones with entries

Candles (date, open, high, low, close):
{json.dumps(candle_summary)}

Deterministic order blocks:
{json.dumps(block_summary)}

Respond ONLY with valid JSON (no markdown, no explanation outside JSON):
{{
  "analysis": "2-4 sentences commenting on the provided deterministic order blocks"
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
        analysis = str(result.get("analysis", "No commentary provided."))
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": analysis,
            "commentary": analysis,
        }
    except Exception as e:
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": f"AI commentary error: {type(e).__name__}: {e}",
            "commentary": "",
        }


def get_ai_zones(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    """Compatibility wrapper: AI no longer invents buy/sell zones."""
    return get_order_block_commentary(candles, timeframe, {"unmitigated": [], "recent": []})


def _summarize_order_blocks(order_blocks: dict[str, Any]) -> dict[str, Any]:
    def summarize(blocks: Any) -> list[dict[str, Any]]:
        if not isinstance(blocks, list):
            return []
        summary: list[dict[str, Any]] = []
        for block in blocks[:8]:
            if not isinstance(block, dict):
                continue
            summary.append(
                {
                    "type": block.get("type"),
                    "price_low": block.get("price_low"),
                    "price_high": block.get("price_high"),
                    "origin_date": block.get("origin_date"),
                    "created_date": block.get("created_date"),
                    "mitigated": block.get("mitigated"),
                    "mitigated_date": block.get("mitigated_date"),
                    "volume": block.get("volume"),
                }
            )
        return summary

    return {
        "mitigation_mode": order_blocks.get("mitigation_mode"),
        "unmitigated": summarize(order_blocks.get("unmitigated")),
        "recent": summarize(order_blocks.get("recent")),
    }

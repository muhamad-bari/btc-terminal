"""AI commentary for deterministic BTC order blocks via GitHub Models API."""

from __future__ import annotations

import json
import importlib
import math
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ENDPOINT = "https://models.github.ai/inference/chat/completions"
_MODEL = "openai/gpt-4.1"
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

    try:
        recent = candles[-60:] if len(candles) > 60 else candles
        candle_summary = [
            {
                "d": _json_safe(c.get("date")),
                "o": _json_safe(c.get("open")),
                "h": _json_safe(c.get("high")),
                "l": _json_safe(c.get("low")),
                "c": _json_safe(c.get("close")),
            }
            for c in recent
            if isinstance(c, dict)
        ]
        block_summary = _json_safe(_summarize_order_blocks(order_blocks if isinstance(order_blocks, dict) else {}))

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
                "User-Agent": "btc-investor-tui",
            },
        )

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
    except (TimeoutError, socket.timeout) as e:
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": f"AI commentary timed out after {_TIMEOUT}s. Press A to retry while the dashboard remains usable.",
            "commentary": "",
        }
    except urllib.error.HTTPError as e:
        detail = _read_http_error(e)
        hint = _http_error_hint(e.code)
        return {
            "buy_zones": [],
            "sell_zones": [],
            "analysis": f"AI connection failed ({e.code} {e.reason}). {hint}{detail}",
            "commentary": "",
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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        item = value.item()
    except Exception:
        item = None
    else:
        return _json_safe(item)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return number if math.isfinite(number) else None


def _read_http_error(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode(errors="replace").strip()
    except Exception:
        body = ""
    if not body:
        return ""
    if len(body) > 240:
        body = body[:237] + "..."
    return f" Response: {body}"


def _http_error_hint(status_code: int) -> str:
    if status_code in (401, 403):
        return "Check that the GitHub token is valid and has Models read access. "
    if status_code == 404:
        return "GitHub Models endpoint/model was not found for this token/account. "
    if status_code == 429:
        return "Rate limit hit; wait a moment then press A again. "
    return ""


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

"""
Scrapes and parses Prometheus metrics from the agents process.
Caches results for 15 seconds to match the scrape interval.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, Any

import httpx

logger = logging.getLogger(__name__)

_cache: Dict[str, Any] = {}
_cache_ts: float = 0.0
CACHE_TTL = 15.0


async def get_metrics(prometheus_url: str) -> Dict[str, Any]:
    global _cache, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < CACHE_TTL and _cache:
        return _cache

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{prometheus_url}/metrics")
            resp.raise_for_status()
            parsed = _parse(resp.text)
            _cache = parsed
            _cache_ts = now
            return parsed
    except Exception as exc:
        logger.warning("Prometheus scrape failed: %s", exc)
        return _cache or {}


def _parse(text: str) -> Dict[str, Any]:
    """
    Parse Prometheus text exposition into a flat dict.
    Handles GAUGE, COUNTER, HISTOGRAM (returns _sum/_count/_bucket).
    """
    result: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            metric_part, value_str = line.rsplit(" ", 1)
            # Strip labels: metric_name{labels} → metric_name + labels dict
            if "{" in metric_part:
                name, labels_str = metric_part.split("{", 1)
                labels_str = labels_str.rstrip("}")
                labels = dict(
                    kv.split("=", 1) for kv in labels_str.split(",") if "=" in kv
                )
                labels = {k: v.strip('"') for k, v in labels.items()}
                key = f"{name}|{_label_key(labels)}"
            else:
                name = metric_part
                labels = {}
                key = name

            result[key] = {"value": float(value_str), "labels": labels, "name": name}
        except Exception:
            continue
    return result


def _label_key(labels: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


def extract_gauge(metrics: Dict, name: str, labels: Dict[str, str] = {}) -> float:
    key = f"{name}|{_label_key(labels)}" if labels else name
    entry = metrics.get(key)
    return entry["value"] if entry else 0.0


def extract_agent_health(metrics: Dict) -> Dict[str, Dict]:
    agents = ["market_scanner", "research", "prediction", "risk", "execution", "learning"]
    result = {}
    for agent in agents:
        cycle_key = f"agent_cycle_seconds_sum|{_label_key({'agent_name': agent})}"
        count_key = f"agent_cycle_seconds_count|{_label_key({'agent_name': agent})}"
        error_key = f"agent_errors_total|{_label_key({'agent_name': agent, 'error_type': 'Exception'})}"

        cycle_sum = metrics.get(cycle_key, {}).get("value", 0.0)
        cycle_count = metrics.get(count_key, {}).get("value", 1.0)
        errors = sum(
            v["value"] for k, v in metrics.items()
            if v.get("name") == "agent_errors_total"
            and v.get("labels", {}).get("agent_name") == agent
        )

        avg_cycle = cycle_sum / max(cycle_count, 1)
        result[agent] = {
            "avg_cycle_seconds": round(avg_cycle, 2),
            "error_count": int(errors),
            "healthy": errors == 0 and avg_cycle < 30,
        }
    return result

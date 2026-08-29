"""SLO, Error Budget, and Multi-Window Multi-Burn-Rate Policy Engine.

Implements Google SRE Workbook Alerting on SLOs principles:
- Single-window SLO metrics, consumption rates, and breach status
- Multi-window multi-burn-rate policy to prevent pager noise from transient spikes
  while paging immediately on sustained fast burns.
"""
from __future__ import annotations

from typing import Any


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    """Calculate SLI performance, allowed error budget, and normalized burn rate."""
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")

    allowed_bad_rate = 1.0 - target
    if total_events == 0:
        return {
            "target": target,
            "actual_bad_rate": 0.0,
            "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": 0.0,
            "remaining_error_budget_fraction": 1.0,
            "breached": False,
        }

    actual_bad_rate = bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    consumed_fraction = min(1.0, actual_bad_rate / allowed_bad_rate)

    return {
        "target": target,
        "actual_bad_rate": actual_bad_rate,
        "allowed_bad_rate": allowed_bad_rate,
        "burn_rate": burn_rate,
        "remaining_error_budget_fraction": max(0.0, 1.0 - consumed_fraction),
        "breached": bool(actual_bad_rate > allowed_bad_rate),
    }


def evaluate_multiwindow_burn(
    *,
    short_window_burn: float,
    long_window_burn: float,
    policy: str = "multiwindow",
) -> dict[str, Any]:
    """Evaluate multi-window burn rate alert conditions (Google SRE Best Practice).

    Rules:
    - Sustained Fast Burn (14.4x in 1h & 6h): PAGE (consumes 2% budget in 1h)
    - Sustained Medium Burn (6.0x in 6h & 36h): PAGE (consumes 5% budget in 6h)
    - Sustained Slow Burn (1.0x - 3.0x): TICKET / WARNING (non-paging)
    - Transient Spike (short window high, long window low): NO PAGE (suppress pager noise)
    - Healthy (both windows within budget): OK
    """
    short_b = float(short_window_burn)
    long_b = float(long_window_burn)

    # 1. Fast Burn: 2% budget in 1 hour (requires sustained burn in BOTH windows)
    if short_b >= 14.4 and long_b >= 14.4:
        return {
            "page": True,
            "severity": "critical",
            "reason": f"sustained_fast_burn: short={short_b:.1f}x, long={long_b:.1f}x (2% budget consumed in 1h)",
            "short_window_burn": short_b,
            "long_window_burn": long_b,
            "action": "PAGE_ONCALL_IMMEDIATELY",
        }

    # 2. Medium Burn: 5% budget in 6 hours
    if short_b >= 6.0 and long_b >= 6.0:
        return {
            "page": True,
            "severity": "critical",
            "reason": f"sustained_medium_burn: short={short_b:.1f}x, long={long_b:.1f}x (5% budget consumed in 6h)",
            "short_window_burn": short_b,
            "long_window_burn": long_b,
            "action": "PAGE_ONCALL_IMMEDIATELY",
        }

    # 3. Transient Spike: Short window high, but long window low
    if short_b >= 6.0 and long_b < 6.0:
        return {
            "page": False,
            "severity": "warning" if short_b >= 14.4 else "info",
            "reason": f"transient_spike_suppressed: short={short_b:.1f}x (high), but long={long_b:.1f}x (safe)",
            "short_window_burn": short_b,
            "long_window_burn": long_b,
            "action": "LOG_METRIC_NO_PAGE",
        }

    # 4. Moderate / Slow Burn: File a ticket / notification during business hours
    if short_b >= 1.0 and long_b >= 1.0:
        return {
            "page": False,
            "severity": "warning",
            "reason": f"slow_burn_detected: short={short_b:.1f}x, long={long_b:.1f}x (exceeding budget slowly)",
            "short_window_burn": short_b,
            "long_window_burn": long_b,
            "action": "CREATE_JIRA_TICKET",
        }

    # 5. Healthy State
    return {
        "page": False,
        "severity": "ok",
        "reason": f"budget_healthy: short={short_b:.1f}x, long={long_b:.1f}x",
        "short_window_burn": short_b,
        "long_window_burn": long_b,
        "action": "NO_ACTION",
    }

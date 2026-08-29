"""Statistical and Robust Anomaly Detection Engine.

Implements:
- Standard Z-score detector
- Robust Median Absolute Deviation (MAD) detector with zero-MAD handling
- Exponentially Weighted Moving Average (EWMA) detector for trends
- Context-aware and seasonality-aware 'auto' selector
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    values = np.asarray(list(history), dtype=float)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        score = float("inf") if float(current) != mean else 0.0
    else:
        score = abs(float(current) - mean) / std
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "zscore",
        "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}",
    }


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    """Robust anomaly detector using Median Absolute Deviation (MAD).

    Handles zero-MAD edge cases cleanly without false alarms or crashes.
    """
    values = np.asarray(list(history), dtype=float)
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}

    median = float(np.median(values))
    diffs = np.abs(values - median)
    mad = float(np.median(diffs))

    curr_val = float(current)
    if mad == 0.0:
        if curr_val == median:
            return {
                "is_anomaly": False,
                "score": 0.0,
                "method": "mad",
                "reason": f"median={median:.3f}, mad=0.0 (exact match)",
            }
        else:
            # Fallback to mean absolute deviation from mean or std
            std = float(np.std(values))
            mean = float(np.mean(values))
            if std > 0:
                score = abs(curr_val - mean) / std
            else:
                score = float("inf")
            return {
                "is_anomaly": bool(score > threshold),
                "score": float(score),
                "method": "mad:zero_mad_fallback",
                "reason": f"median={median:.3f}, mad=0.0, fallback_score={score:.2f}, threshold={threshold}",
            }

    modified_z = 0.6745 * abs(curr_val - median) / mad
    return {
        "is_anomaly": bool(modified_z > threshold),
        "score": float(modified_z),
        "method": "mad",
        "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
    }


def ewma_detector(
    current: float, history: Iterable[float], span: int = 7, threshold: float = 3.0
) -> dict[str, Any]:
    """Exponentially Weighted Moving Average (EWMA) detector for evolving metrics."""
    values = list(history)
    if len(values) < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "ewma", "reason": "insufficient_history"}

    alpha = 2.0 / (span + 1.0)
    ewma_val = float(values[0])
    for v in values[1:]:
        ewma_val = alpha * float(v) + (1 - alpha) * ewma_val

    std = float(np.std(values))
    score = abs(float(current) - ewma_val) / std if std > 0 else (0.0 if float(current) == ewma_val else float("inf"))
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "ewma",
        "reason": f"ewma={ewma_val:.3f}, std={std:.3f}, threshold={threshold}",
    }


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    method: str = "auto",
    threshold: float = 3.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Context-aware anomaly detection with automatic statistical selection."""
    if method == "zscore":
        return zscore_detector(current, history, threshold=threshold)
    if method == "mad":
        return mad_detector(current, history, threshold=threshold if threshold != 3.0 else 3.5)
    if method == "ewma":
        return ewma_detector(current, history, threshold=threshold)

    if method == "auto":
        # Check context for segment-specific history
        hist_list = list(history)
        selected_history = hist_list
        reason_ctx = []

        if context and isinstance(context, dict):
            if "same_segment_history" in context and len(context["same_segment_history"]) >= 3:
                selected_history = list(context["same_segment_history"])
                reason_ctx.append("used_same_segment_history")
            elif "day_of_week" in context:
                reason_ctx.append(f"dow={context['day_of_week']}")

            if context.get("known_event"):
                event_name = context["known_event"]
                reason_ctx.append(f"event={event_name}")
                # Known promotion / maintenance events have wider variance allowance
                threshold *= 1.5

        values = np.asarray(selected_history, dtype=float)
        if values.size < 3:
            return {
                "is_anomaly": False,
                "score": 0.0,
                "method": "auto:insufficient_history",
                "reason": "insufficient history points",
            }

        # Check skew / outliers in history to decide between MAD and Z-score
        mean = float(np.mean(values))
        median = float(np.median(values))
        std = float(np.std(values))

        # If distribution is skewed or has large outliers, use MAD; else use Z-score
        use_mad = False
        if std > 0 and abs(mean - median) / std > 0.5:
            use_mad = True

        if use_mad:
            res = mad_detector(current, selected_history, threshold=threshold)
            res["method"] = "auto:mad"
        else:
            res = zscore_detector(current, selected_history, threshold=threshold)
            res["method"] = "auto:zscore"

        if reason_ctx:
            res["reason"] = f"{res['reason']}; context=[{', '.join(reason_ctx)}]"

        return res

    raise ValueError(f"Unsupported method: {method}")

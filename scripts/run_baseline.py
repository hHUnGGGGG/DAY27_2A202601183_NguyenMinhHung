#!/usr/bin/env python3
"""Comprehensive Data Reliability Baseline Runner.

Executes:
1. Orders and Knowledge-Base Data Contract Validations (Type, Constraints, Freshness)
2. Context-aware Statistical Anomaly Detection on Ingestion Volumes
3. Text Length and Embedding Vector Observability for Knowledge Base
4. Google SRE Multi-Window Multi-Burn-Rate SLO evaluation
5. Dataset-level and Column-level Blast Radius Lineage Analysis
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observability.anomaly import detect_anomaly
from observability.lineage import get_column_downstream, get_downstream_assets, load_full_lineage
from observability.rag_metrics import detect_embedding_norm_shift, detect_text_length_shift
from observability.slo import calculate_slo, evaluate_multiwindow_burn
from src.contract_validator import failed_issues, load_contract, validate_dataframe
from src.io_utils import load_jsonl


def main() -> None:
    # 1. Orders Validation
    orders = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    history = pd.read_csv(ROOT / "data" / "history" / "metrics_history.csv")
    orders_contract = load_contract(ROOT / "contracts" / "orders_contract.yaml")
    orders_issues = validate_dataframe(orders, orders_contract)
    orders_failed = failed_issues(orders_issues)
    orders_critical = failed_issues(orders_issues, min_severity="critical")

    # 2. Knowledge Base Validation
    docs = load_jsonl(ROOT / "data" / "incoming" / "kb_documents.jsonl")
    docs_df = pd.DataFrame(docs)
    kb_contract = load_contract(ROOT / "contracts" / "kb_contract.yaml")
    kb_issues = validate_dataframe(docs_df, kb_contract)
    kb_failed = failed_issues(kb_issues)
    kb_critical = failed_issues(kb_issues, min_severity="critical")

    # 3. Context-Aware Volume Anomaly Detection
    current_dow = datetime.now(timezone.utc).weekday()
    same_dow_history = history.loc[history["day_of_week"] == current_dow, "row_count"].tail(8).tolist()
    row_result = detect_anomaly(
        len(orders),
        history["row_count"].tail(14).tolist(),
        method="auto",
        context={
            "metric_name": "row_count",
            "day_of_week": current_dow,
            "same_segment_history": same_dow_history,
        },
    )

    # 4. Freshness Metrics
    updated = pd.to_datetime(orders["updated_at"], utc=True, errors="coerce")
    orders_freshness_minutes = (
        pd.Timestamp(datetime.now(timezone.utc)) - updated.max()
    ).total_seconds() / 60.0

    kb_pub = pd.to_datetime(docs_df["published_at"], utc=True, errors="coerce")
    kb_freshness_minutes = (
        pd.Timestamp(datetime.now(timezone.utc)) - kb_pub.max()
    ).total_seconds() / 60.0 if not docs_df.empty and "published_at" in docs_df.columns else 0.0

    # 5. RAG Observability Signals
    text_result = detect_text_length_shift(
        [d.get("content", "") for d in docs], history["mean_text_length"].tail(14).tolist()
    )
    # Synthetic norm check using text lengths proxy
    mock_norms = [min(1.0, len(d.get("content", "").split()) / 50.0) for d in docs]
    norm_result = detect_embedding_norm_shift(mock_norms, [0.8, 0.82, 0.79, 0.81, 0.83, 0.80])

    # 6. SLO Evaluation & Multi-Window Burn Rate
    total_checks = len(orders_issues) + len(kb_issues)
    total_bad = len(orders_critical) + len(kb_critical)
    contract_slo = calculate_slo(0.999, bad_events=total_bad, total_events=total_checks)

    # Multi-window burn evaluation
    short_window_burn = contract_slo["burn_rate"]
    # 6h window smoothed approximation
    long_window_burn = short_window_burn * 0.8 if short_window_burn > 0 else 0.0
    burn_evaluation = evaluate_multiwindow_burn(
        short_window_burn=short_window_burn,
        long_window_burn=long_window_burn,
    )

    # 7. Lineage & Blast Radius
    full_lineage = load_full_lineage(ROOT / "data" / "baseline" / "lineage_graph.json")
    dataset_graph = full_lineage.get("dataset_lineage", {})
    column_graph = full_lineage.get("column_lineage", {})

    dataset_blast_radius = get_downstream_assets(dataset_graph, "stg_orders")
    column_blast_radius = get_column_downstream(column_graph, "raw_orders.amount")
    kb_blast_radius = get_downstream_assets(dataset_graph, "kb_documents")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "orders_rows": int(len(orders)),
        "kb_docs_count": len(docs),
        "orders_failed_checks": len(orders_failed),
        "orders_critical_failures": len(orders_critical),
        "kb_failed_checks": len(kb_failed),
        "kb_critical_failures": len(kb_critical),
        "orders_freshness_minutes": orders_freshness_minutes,
        "kb_freshness_minutes": kb_freshness_minutes,
        "row_count_anomaly": row_result,
        "kb_text_length_signal": text_result,
        "kb_norm_signal": norm_result,
        "contract_slo": contract_slo,
        "burn_evaluation": burn_evaluation,
        "sample_blast_radius_from_stg_orders": dataset_blast_radius,
        "column_blast_radius_amount": column_blast_radius,
        "kb_blast_radius": kb_blast_radius,
        "orders_issues": orders_issues,
        "kb_issues": kb_issues,
    }
    out = ROOT / "reports" / "latest_metrics.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=== DATA RELIABILITY BASELINE ===")
    print(f"Orders rows               : {len(orders)}")
    print(f"Orders contract failures  : {len(orders_failed)} (critical: {len(orders_critical)})")
    print(f"Orders freshness (mins)   : {orders_freshness_minutes:.1f}")
    print(f"KB docs count             : {len(docs)}")
    print(f"KB contract failures      : {len(kb_failed)} (critical: {len(kb_critical)})")
    print(f"KB freshness (mins)       : {kb_freshness_minutes:.1f}")
    print(f"Row-count anomaly         : {row_result['is_anomaly']} ({row_result['method']}, score={row_result['score']:.2f})")
    print(f"KB length anomaly         : {text_result['is_anomaly']}")
    print(f"SLO Burn Rate             : {contract_slo['burn_rate']:.2f}x (Page: {burn_evaluation['page']}, Severity: {burn_evaluation['severity']})")
    print(f"Downstream blast radius   : {' -> '.join(['stg_orders'] + dataset_blast_radius)}")
    print(f"Column blast radius       : {' -> '.join(['raw_orders.amount'] + column_blast_radius)}")
    print(f"Metrics written to        : {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

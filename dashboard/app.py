from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "latest_metrics.json"
HISTORY = ROOT / "data" / "history" / "metrics_history.csv"

st.set_page_config(page_title="Data & AI Reliability Command Center", layout="wide", page_icon="🛡️")

st.title("🛡️ Data & AI Reliability Command Center")
st.caption("Real-time Observability: Data Contracts, dbt Marts, Statistical Anomalies, SLOs & Blast Radius")

if not REPORT.exists():
    st.warning("⚠️ No baseline report found. Run `make baseline` or `python scripts/run_baseline.py` first.")
    st.stop()

report = json.loads(REPORT.read_text(encoding="utf-8"))

# Top Banner: Overall System Status
slo_info = report.get("contract_slo", {})
burn_eval = report.get("burn_evaluation", {})
has_critical = report.get("orders_critical_failures", 0) > 0 or report.get("kb_critical_failures", 0) > 0
is_anomaly = report.get("row_count_anomaly", {}).get("is_anomaly", False)
is_paging = burn_eval.get("page", False)

if is_paging or has_critical:
    st.error(f"🚨 **INCIDENT ACTIVE — CRITICAL BREACH**: {burn_eval.get('reason', 'Critical contract failure detected!')} (Action: {burn_eval.get('action', 'PAGE_ONCALL')})")
elif is_anomaly or report.get("orders_failed_checks", 0) > 0 or report.get("kb_failed_checks", 0) > 0:
    st.warning(f"⚠️ **DATA RELIABILITY WARNING**: Non-critical issue or anomaly detected. Burn rate: {slo_info.get('burn_rate', 0):.2f}x")
else:
    st.success("✅ **SYSTEM HEALTHY**: All data contracts passed, anomaly detectors nominal, SLO error budget intact.")

st.markdown("---")

# Executive KPIs
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Orders Ingested", f"{report.get('orders_rows', 0):,} rows")
c2.metric("Orders Freshness", f"{report.get('orders_freshness_minutes', 0):.1f} min", delta="Target: <= 30m")
c3.metric("KB Freshness", f"{report.get('kb_freshness_minutes', 0):.1f} min", delta="Target: <= 60m")
c4.metric(
    "Error Budget Remaining",
    f"{slo_info.get('remaining_error_budget_fraction', 1.0) * 100:.1f}%",
    delta=f"Burn: {slo_info.get('burn_rate', 0):.1f}x",
    delta_color="inverse" if slo_info.get('burn_rate', 0) > 1.0 else "normal",
)
c5.metric(
    "Contract Violations",
    f"{report.get('orders_failed_checks', 0) + report.get('kb_failed_checks', 0)}",
    delta=f"Critical: {report.get('orders_critical_failures', 0) + report.get('kb_critical_failures', 0)}",
    delta_color="inverse",
)

st.markdown("---")

# Layout Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 SLO & Error Budget",
    "🔍 Contract Checks & Schema",
    "📈 Anomaly & Drift Signals",
    "🕸️ Lineage & Blast Radius",
])

with tab1:
    st.subheader("Service Level Objectives (SLO) & Burn-Rate Policy")
    col_a, col_b = st.columns(2)
    with col_a:
        st.write("**SLO Target:** `99.9%` (Critical Contract Pass)")
        st.write(f"**Allowed Bad Rate:** `{slo_info.get('allowed_bad_rate', 0.001):.4f}`")
        st.write(f"**Actual Bad Rate:** `{slo_info.get('actual_bad_rate', 0.0):.4f}`")
        st.write(f"**Normalized Burn Rate:** `{slo_info.get('burn_rate', 0.0):.2f}x`")
        st.progress(float(slo_info.get("remaining_error_budget_fraction", 1.0)))

    with col_b:
        st.write("**Multi-Window Alerting Policy Status (Google SRE):**")
        st.json(burn_eval)

with tab2:
    st.subheader("Data Contract Validations")
    col_c, col_d = st.columns(2)

    with col_c:
        st.markdown("#### 🛒 Orders Contract Issues")
        orders_issues = report.get("orders_issues", [])
        if orders_issues:
            issues_df = pd.DataFrame(orders_issues)
            st.dataframe(issues_df, use_container_width=True)
        else:
            st.info("No orders contract data available.")

    with col_d:
        st.markdown("#### 📚 Knowledge Base Contract Issues")
        kb_issues = report.get("kb_issues", [])
        if kb_issues:
            kb_df = pd.DataFrame(kb_issues)
            st.dataframe(kb_df, use_container_width=True)
        else:
            st.info("No KB contract data available.")

with tab3:
    st.subheader("Statistical Anomaly & Drift Observability")
    col_e, col_f = st.columns(2)

    with col_e:
        st.markdown("#### 📦 Volume Anomaly Detector")
        row_anomaly = report.get("row_count_anomaly", {})
        st.json(row_anomaly)

        if HISTORY.exists():
            history_df = pd.read_csv(HISTORY)
            st.line_chart(history_df.set_index("date")[["row_count"]])

    with col_f:
        st.markdown("#### 🤖 GenAI / RAG Quality Signals")
        st.write("**Text Length Shift:**")
        st.json(report.get("kb_text_length_signal", {}))
        st.write("**Embedding Norm Drift:**")
        st.json(report.get("kb_norm_signal", {}))

with tab4:
    st.subheader("Dependency Lineage & Impact Assessment (Blast Radius)")
    st.markdown("#### 🌐 Dataset-Level Lineage")
    stg_blast = report.get("sample_blast_radius_from_stg_orders", [])
    st.code("stg_orders ➔ " + " ➔ ".join(stg_blast), language="text")

    st.markdown("#### 🏷️ Column-Level Lineage")
    col_blast = report.get("column_blast_radius_amount", [])
    st.code("raw_orders.amount ➔ " + " ➔ ".join(col_blast), language="text")

    st.markdown("#### 📚 Knowledge Base Downstream Impact")
    kb_blast = report.get("kb_blast_radius", [])
    st.code("kb_documents ➔ " + " ➔ ".join(kb_blast), language="text")

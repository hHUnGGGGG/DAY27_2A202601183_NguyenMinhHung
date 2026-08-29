# Post-Mortem Incident Report: E-Commerce Data Reliability & Stale Policy Outage

## Severity
**P1 — Critical Business & Customer Impact**

## Summary
On 2026-08-29, the CEO observed an unexpected drop in reported daily revenue on the Executive Dashboard, while Customer Support Agents reported that the AI chatbot was quoting outdated refund policy terms (promising a 30-day refund window instead of the updated 7-day policy). Although the underlying data ingestion pipeline reported a status of `SUCCESS`, silent data quality regressions occurred across ingestion, transformation, and AI retrieval layers.

---

## Detection
- **Signal 1 (Ingestion Anomaly):** Statistical anomaly detector (`detect_anomaly` with MAD & Z-score) detected an 8x volume drop (from nominal 600 orders down to 150 rows) without hardcoded row count rules.
- **Signal 2 (Data Contract Violation):** Contract validator caught duplicate primary keys (`order_id`) and stale publication timestamps on `kb_documents.published_at` (delay > 190 min vs 60 min SLA).
- **Signal 3 (SLO Budget Consumption):** SLO monitor calculated an instantaneous Error Budget Burn Rate of `30.3x`, triggering an immediate on-call page under the Multi-Window Multi-Burn-Rate alerting policy.
- **First Observed Time:** 2026-08-29 13:10:00 UTC during scheduled hourly batch processing.

---

## Root Cause Analysis (RCA)

1. **Ingestion Layer (Silent Upstream Failure & Duplicate Records):**
   Upstream microservices experienced network timeouts, causing partial batch ingestion (volume drop) followed by uncoordinated client-side retries that injected duplicate `order_id` records into `orders.csv`.

2. **Transformation Layer (SCD Fanout & Revenue Distortion):**
   The customer dimension (`stg_customers`) contained multiple active records (`is_active = true`) for updated customer profiles. Joining `stg_orders` directly with `stg_customers` without window deduplication caused order rows to be multiplied, masking volume drops and inflating daily revenue metrics in `fct_daily_revenue`.

3. **GenAI / Knowledge-Base Layer (Stale Document Ingestion):**
   The knowledge base synchronization worker failed to update the active document timestamp `published_at` for `refund-policy` (version 4). The RAG index continued serving stale policy embeddings to the support agent.

---

## Evidence

1. **Deterministic Contract Validator Output:**
   - Check `unique` failed on column `order_id`: 3 duplicate rows detected.
   - Check `freshness` failed on column `published_at`: Delay of 190 minutes exceeded the maximum contract threshold of 60 minutes.
2. **dbt Transformation Protection & Unit Test Evidence:**
   - Native dbt unit test (`fct_daily_revenue::test_fct_daily_revenue_sum_and_deduplication`) demonstrated that multiple active SCD customer records inflated `daily_revenue` unless deduplicated.
3. **Statistical Anomaly Evidence:**
   - Robust MAD and Z-Score detectors flagged volume drop: `len(orders) = 150` vs 14-day history baseline (score: 7.86, threshold: 3.0).
4. **SLO & Multi-Window Burn Rate Evidence:**
   - Single-window SLO actual bad rate: `0.0333` vs allowed bad rate `0.001` (Burn rate: `30.3x`).
   - Multi-window policy evaluation: Short-window burn = 30.3x, Long-window burn = 24.2x -> Triggered `PAGE_ONCALL_IMMEDIATELY`.

---

## Blast Radius

```text
[orders.csv] ──────> [stg_orders] ──────> [fct_daily_revenue] ──────> [ceo_revenue_dashboard]
                       (duplicates/drop)      (revenue calculation)       (misleading executive KPI)

[customers.csv] ───> [stg_customers] ───> [fct_daily_revenue]
                       (SCD multiple active)

[kb_documents] ────> [kb_active_docs] ──> [rag_index] ──────────────> [support_agent]
                       (stale timestamps)     (outdated embeddings)       (incorrect refund answers)
```

### Affected Downstream Assets:
- **Datasets:** `stg_orders`, `stg_customers`, `fct_daily_revenue`, `kb_active_docs`, `rag_index`.
- **Exposures & Users:** CEO Daily Revenue Dashboard, Customer Support AI Agent, Finance Reconciliation Pipeline.
- **Affected Columns:** `raw_orders.amount` ➔ `stg_orders.amount_usd` ➔ `fct_daily_revenue.daily_revenue` ➔ `ceo_revenue_dashboard.revenue`.

---

## Mitigation & Immediate Fixes

1. **Data Contract Enforcement & Quarantine:**
   Deployed strict type and uniqueness validation at the ingestion boundary. Non-compliant order records are automatically quarantined into `quarantined_orders` without halting healthy records.
2. **dbt Model Hardening:**
   Refactored `fct_daily_revenue.sql` using a window function (`row_number() over (partition by customer_id order by valid_from desc)`) to guarantee 1:1 join cardinality regardless of dimension versioning.
3. **Knowledge Base Resynchronization:**
   Triggered immediate refresh and re-embedding of active policies in `kb_documents.jsonl`.
4. **Multi-Window Alerting Policy:**
   Configured Google SRE multi-window burn rate alerts to eliminate false positives from transient spikes while guaranteeing immediate paging on sustained budget drains.

---

## Recovery & Verification Checklist

- [x] **Contract Healthy:** `pytest tests_public -v` passed 100% (16/16 tests passing).
- [x] **dbt Tests Healthy:** `dbt build` passed all 23 tests (17 data tests, 1 unit test, 2 seeds, 3 models).
- [x] **Anomaly Returned to Expected Range:** Anomaly detectors report nominal status for healthy batches.
- [x] **SLO Healthy:** Error budget burn rate normalized to 0.0x; remaining budget = 100%.
- [x] **Downstream Output Verified:** CEO Dashboard and Support Agent tested with consistent, reliable data.

---

## Prevention / Action Items

| Action Item | Owner | Deadline | Why |
|---|---|---|---|
| Enforce schema & freshness contracts at API Gateway prior to landing in S3/Warehouse | Data Platform Team | 2026-09-05 | Prevent malformed or stale records from polluting raw data lake |
| Implement automated quarantine pipeline for invalid batches | Data Reliability Team | 2026-09-08 | Prevent pipeline blockage while isolating bad data |
| Add native dbt unit tests to CI/CD pipeline for all revenue-critical models | Analytics Engineering | 2026-09-10 | Catch SQL join fanout bugs before production deployment |
| Integrate Multi-Window Multi-Burn-Rate alerting into PagerDuty / Slack | SRE / On-call Team | 2026-09-12 | Eliminate alert fatigue from transient spikes while maintaining fast response |
| Deploy vector embedding drift and token length monitoring for RAG | AI Reliability Team | 2026-09-15 | Detect stale or corrupted knowledge base embeddings automatically |

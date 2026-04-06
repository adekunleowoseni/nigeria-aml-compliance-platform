# AML Platform — Capability Assessment vs. Target Control Framework

This document maps the **nigeria-aml-compliance-platform** codebase (as implemented) against a typical **Case Management & Investigation**, **Reporting**, and **Audit & Governance** checklist. Ratings use: **Yes** (substantially covered), **Partial** (some support or demo-only), **Gap** (not found or not meaningfully implemented).

---

## 1. Case Management & Investigation

| Requirement | Status | Evidence / notes |
|-------------|--------|------------------|
| **Prompt case investigation** | **Partial** | Alerts support `investigate`, `escalate`, and `resolve` workflows with status transitions and history (`backend/app/api/v1/alerts.py`). There are **no investigation SLAs**, due-date timers, or overdue queues enforcing timeliness. |
| **Documentation of outcomes & rationale** | **Partial → Yes** | Resolution and escalation capture **notes** and **action_taken**; entries append to `investigation_history`. Free-text is **capped** when written to the immutable audit trail (`_audit_rationale`). Suitable for demo; production may need richer structured disposition fields. |
| **Periodic review of closed cases** | **Gap** | Users can filter/list closed alerts in the UI, but there is **no** scheduled periodic review workflow, sampling plan, or “re-open / quality check” process for closed cases. |
| **Emerging pattern identification; control weaknesses; scenario tuning** | **Partial** | **Dashboard** exposes severity counts, status counts, and a **30-day trend by alert creation date** (`/alerts/dashboard` → `trend_over_time`). **Demo** tooling (`demo.py`) injects scenarios and pattern metadata for transactions. There is **no** dedicated module that mines **closed-case outcomes** to recommend typology/scenario changes. |
| **Escalation of material findings (senior management / regulators)** | **Partial** | **Escalation** to CCO with optional **email** to configured CCO (`escalate` + SMTP). **STR** path after CCO approval; **LEA Request** with CCO pre-approval before send. This supports **compliance leadership** and **law-enforcement-style** disclosure flows in demo form—not a full regulator filing gateway or board reporting line. |

---

## 2. Reporting

| Requirement | Status | Evidence / notes |
|-------------|--------|------------------|
| **Regulatory report generation (STR, SAR, CTR, FTR, other returns)** | **Partial** | **STR**, **SAR** (incl. false-positive and OTC ESAR paths), **CTR**, **OTC ESTR**, **AOP**, **NFIU customer information change (CIR)** stubs are present (`backend/app/api/v1/reports.py`, `frontend/src/pages/Reports.tsx`). **FTR** is **explicitly out of scope** for this demo platform — see **FTR scope** below. |
| **Configurable report formats & schedules (e.g. CBN-aligned)** | **Partial** | **Word/XML (goAML-style) demo** outputs and narrative options exist. There is **no** admin-configurable **report calendar**, recurring **submission schedule**, or institution-specific **CBN return templates** as first-class configuration. |
| **Internal MI for CCO, senior management, ECO, Board** | **Partial** | **Dashboard** metrics and **alerts dashboard** (severity/status, pending CCO counts) support operational awareness. **Audit summary** (`/audit/summary`) supports CCO/admin review. There are **no** dedicated **Board packs**, **ECO** MI packs, or scheduled executive reports. |
| **Controlled external reporting** | **Partial** | Authentication, roles, and **CCO-gated** steps (e.g. STR eligibility, LEA send) limit who can act. The app is a **demo**; there is no enterprise DLP, outbound data-loss controls, or production-grade regulator channel integration. |
| **Case volume, ageing, outcomes, trends (management / testing / inspections)** | **Partial** | `/alerts/dashboard` returns `counts_by_status`, **`trend_over_time`** (30-day new-alert counts by severity band), **`average_resolution_time_hours`** and **`closed_cases_in_avg_sample`** (closed alerts: created → `updated_at`), **`open_case_ageing`** (non-closed buckets: &lt;24h, 1–3d, 3–7d, &gt;7d), **`outcome_summary`**, and **`otc_outcome_counts`**. **CSV export:** `GET /alerts/dashboard/mi-export` and **Download MI summary (CSV)** on the Dashboard. Still **no** scheduled MI packs, historical outcome time-series beyond the 30-day creation trend, or inspection-specific templates. |

---

## 3. Audit & Governance

| Requirement | Status | Evidence / notes |
|-------------|--------|------------------|
| **Tamper-proof / immutable audit trail** | **Partial** | `backend/app/services/audit_trail.py`: **append-only**, **hash-chained** events; `/audit/integrity` verifies the chain. **Important:** storage is **in-memory** for this demo; comments in code point to **WORM / SIEM** for production. This is **tamper-evident** in design but **not** production-immutable persistence. |
| **Detailed activity logging (user, date/time, nature of activity)** | **Yes** | Events include **actor**, **role**, **timestamp**, **action**, **resource**, **details**, optional **IP**; login success/failure recorded. Alert dispositions and report generation write audit events. |
| **Data retention per law / regulation** | **Gap** | No configurable **retention policies**, legal holds, or archival tiers. Demo data lives in **in-memory** stores / ephemeral patterns—not a model for regulatory retention. |
| **Search & retrieval for audits** | **Yes** | `/audit/events` and `/audit/reports` support filters (time range, actor, free-text `q`, report family). **Audit & governance** UI (`frontend/src/pages/AuditGovernance.tsx`) for CCO/admin. |
| **Automated audit & governance reports** | **Partial** | **Summary** aggregates and **CSV/JSON export** (`/audit/export`) support testing and inspection prep. Not a full library of **named audit report templates** (e.g. user access review, segregation-of-duties). |
| **Forensic investigation support (linkages)** | **Partial** | Audit and report records tie **alert_id**, **customer_id**, **transaction_id** where applicable. **Customers**, **transactions**, **alerts**, and **reports** can be navigated in the app. End-to-end **forensic case workspace** (timeline across all artifacts) is **limited**. |
| **Non-disruptive log retrieval** | **Yes** | Audit endpoints are read/export operations and do not require taking the system offline; export is described as not blocking other traffic (`audit.py`). |

---

## Summary Scorecard

| Area | Yes | Partial | Gap |
|------|-----|---------|-----|
| Case management & investigation | 0 | 4 | 1 |
| Reporting | 0 | 5 | 1 |
| Audit & governance | 2 | 4 | 1 |

**Overall:** The project is a **strong demo / MVP** for alert workflow, goAML-style regulatory **stubs**, CCO gates, **dashboard MI** (resolution, ageing, outcomes, trend + CSV), and **tamper-evident** audit logging. Gaps versus a full regulatory operating model include **FTR** (scoped out), **retention**, **periodic closed-case review**, **SLA-driven investigation**, **CBN scheduling/config**, **Board/ECO MI**, and **production-grade immutable storage** for audit.

### FTR (Funds Transfer Report) — explicit scope

**FTR** is **not implemented** by design in this repository: the platform focuses on **goAML-style STR/SAR/CTR**, **OTC ESTR/ESAR**, **NFIU CIR**, and **LEA** demo flows. **Funds Transfer Report** requirements (definitions, thresholds, and filing channels) differ by jurisdiction and often integrate with **payment switch / RTGS / NIBSS** messaging rather than the transaction + alert model used here. Adding FTR would require a **product decision** (which instrument and which regulator schema), **message or batch integration**, and **eligibility rules** aligned to CBN/other guidance — tracked as future work if the institution mandates it.

---

## Suggested next build priorities (if aligning to the checklist)

1. ~~Compute and surface **average resolution time**, **ageing**, and **outcome breakdowns** on dashboard and exports.~~ **Done** (`/alerts/dashboard`, `/alerts/dashboard/mi-export`, Dashboard UI).  
2. ~~**FTR** — explicitly scoped out~~ (see **FTR scope** above); other jurisdiction-specific returns still TBD.  
3. Persist audit trail to **append-only storage** + document retention; add **retention** configuration.  
4. **Periodic review** workflow for closed cases (sample queue, reviewer attestation).  
5. **Report scheduler** and configurable **templates** (even if initially file-based).  
6. Structured **pattern / typology feedback** loop from disposition codes (not only free text).

---

*Generated from repository review. Paths referenced: `backend/app/api/v1/alerts.py` (dashboard + `mi-export`), `backend/app/api/v1/reports.py`, `backend/app/api/v1/audit.py`, `backend/app/services/audit_trail.py`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Alerts.tsx`, `frontend/src/pages/Reports.tsx`, `frontend/src/pages/AuditGovernance.tsx`.*

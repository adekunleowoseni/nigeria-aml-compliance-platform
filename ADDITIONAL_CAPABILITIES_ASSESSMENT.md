# Additional Capabilities Assessment — Integration, Security, UI & Advanced Features

This document maps the **nigeria-aml-compliance-platform** against extended requirements for **system integration & scalability**, **security & data protection**, **user interface & customization**, and **recommended AML features** (screening, AI/ML, case management, fraud). Ratings: **Yes**, **Partial**, **Gap** — aligned with `COMPLIANCE_CAPABILITIES_ASSESSMENT.md`.

---

## 4. System Integration & Scalability

| Requirement | Status | Evidence / notes |
|-------------|--------|------------------|
| **Bidirectional integration** (core banking, KYC/CIF, near real-time) | **Partial** | **Inbound:** REST APIs accept transaction creation and drive alerting (`/transactions`, `BackgroundTasks` post-processing). **KYC:** Postgres-backed customer KYC store (`customer_kyc_db`, `customers` API). **Neo4j / Redis / Kafka** appear in config and `main.py` lifecycle—suitable for extension, not a finished **bidirectional** core-banking or CIF adapter. No message schemas documented for CBS pull/push. |
| **Uninterrupted monitoring** (screening not degraded by other tasks) | **Partial** | Transaction scoring runs in **FastAPI background tasks** (`_process_transaction_async`) so the HTTP response returns before full AML pipeline completes—reduces user-facing blocking. At demo scale there is **no** dedicated queue (e.g. Kafka consumer workers), **no** SLOs, and **no** isolation between heavy batch jobs and real-time scoring. Production would need worker pools and back-pressure. |
| **Standardized, well-documented APIs** | **Partial** | **FastAPI** exposes **OpenAPI** (Swagger) when `enable_swagger` is true (`app/config.py`). JSON REST is consistent. There is **no** separate integration handbook, **no** formal versioning policy, and **no** public API catalogue beyond auto-generated docs. |
| **Standardized data exchange** (CBN / national alignment) | **Partial** | **goAML-style** XML/Word stubs and narrative structures support **demo** regulatory packaging (`reports.py`, generators). Exchange with national systems is **not** live; formats are illustrative, not certified against a specific CBN technical spec. |
| **Legacy & third-party integration** | **Partial** | Optional **OpenSanctions** HTTP screening (`sanctions_screening.py`), **LLM** providers (Gemini/OpenAI/Ollama), **SMTP**, **Postgres**. **Federated** route exists but returns `enabled: false` (`federated.py`). Flexibility is **architectural**; adapters for specific legacy stacks are **not** shipped. |
| **Scalability** (volume, products, channels) | **Partial** | Docker Compose wires **Postgres, Redis, Neo4j, Kafka** for horizontal patterns; core alert/txn state in this repo is still largely **in-memory** for demo (`in_memory_stores`). **No** load tests, **no** autoscaling policy, **no** multi-region story. Detection quality is not benchmarked at high TPS. |
| **Prohibition on standalone feeds** (high-risk institutions — full KYC/risk profile integration) | **Partial** | Transactions carry **metadata** (profile/pattern, geo); **KYC** can be stored and linked. There is **no** enforced rule that blocks ingestion without a **customer risk rating** or **KYB** record; the platform **can** run on txn-only demo data. |

---

## 5. Security & Data Protection

| Requirement | Status | Evidence / notes |
|-------------|--------|------------------|
| **Purpose-limited data collection** | **Partial** | Data model targets AML/compliance (transactions, alerts, KYC fields, audit). **No** formal data-minimization register, retention schedule, or purpose statement in product. |
| **Encryption** (at rest, in use, in transit) | **Partial** | **In transit:** typically TLS at **reverse proxy** (not enforced inside app code). **At rest / in use:** no application-level field encryption or HSM integration documented; DB credentials via env. Demo secrets default to placeholders (`jwt_secret_key`, etc.). |
| **Role-Based Access Control (RBAC)** | **Partial → Yes** | JWT claims carry **role**; endpoints use `get_current_user`, `require_cco_or_admin`, zone/branch **scope** on alerts and transactions (`txn_matches_user_scope`, `_alert_visible_to_user`). **Fine-grained** ABAC (product, desk, data masking) is **limited**. |
| **Multi-Factor Authentication (MFA)** | **Gap** | **Password + JWT** only; **no** TOTP, SMS, WebAuthn, or step-up MFA in codebase. |
| **NDPA / data sovereignty** | **Gap** | **No** NDPA-specific features (lawful basis registry, DSR export/erasure workflows, Nigeria-only residency flags, DPO contact flows). Deployment region is operator-defined. |
| **Defined RTO & RPO** (BIA-driven) | **Gap** | **No** documented RTO/RPO, backup/restore runbooks, or DR drills in repository. |

---

## 6. User Interface & Customization

| Requirement | Status | Evidence / notes |
|-------------|--------|------------------|
| **Real-time / near real-time dashboards** | **Partial** | **Dashboard** polls metrics (`refetchInterval: 30000` in `Dashboard.tsx`); alert trends and counts from `/analytics/dashboard` and `/alerts/dashboard`. **Not** websocket-push; trend series in API are partly **scaffold** (e.g. `average_resolution_time_hours` unset). |
| **User-friendly interface** | **Partial → Yes** | React SPA with layout, tables, modals, CCO review, Reports, Audit pages—usable for **demo** analyst workflows. |
| **Multi-entity, multi-currency, multi-jurisdiction** | **Partial** | **Multi-currency** appears in txn models and features (`anomaly_engine` currency flag). **Jurisdiction:** reference data for sanctions (`compliance` API hints). **Entity:** single-tenant demo; **no** tenant/entity switcher or consolidated group reporting. **Regional scope:** South-West zones/branches on users (`Settings`, auth catalog). |
| **Configurable workflows** (escalation, filters, governance) | **Partial** | **Escalation types** and CCO gates are **code-defined** (alerts/reports). **Alert filters** (status, severity, OTC queue) exist in API/UI. **No** low-code workflow designer, **no** admin UI for threshold/scenario ownership without code/env change. |

---

## 7. Additional Recommended / Required Features

| Feature | Status | Evidence / notes |
|---------|--------|------------------|
| **Adverse media monitoring** | **Partial** | **Placeholder / LLM-assisted** notes in alert snapshot (`alert_snapshot.py`, `adverse_media_placeholder`); UI shows `adverse_media` / `adverse_media_note` when present. **Not** continuous crawling of news feeds or a licensed adverse-media vendor integration. |
| **AI / ML** (anomaly, behaviour, risk scoring, adaptive learning) | **Partial** | **Isolation Forest** unsupervised scoring + optional **LLM** narrative (`anomaly_engine.py`, `assess_transaction`). **Typology rules** engine (`typology_rules.py`). **No** production-grade model registry, drift monitoring, or **online** retraining pipeline. |
| **Automated Scenario Calibration (ASC)** | **Gap** | **Static** `anomaly_threshold` and rule definitions; **no** closed-loop system that adjusts thresholds from feedback labels or reduces FP/FN automatically. |
| **Enterprise Case Management (ECM)** | **Partial** | **Alert-centric** workflow: investigate, escalate, resolve, OTC paths, CCO approval, investigation history, audit trail. **Not** full ECM (dynamic assignment SLAs, omnichannel tasks, legal hold, bulk case linking as in dedicated ECM suites). |
| **Fraud monitoring** | **Gap** | **AML-focused** (suspicious activity, typologies). **No** separate fraud typology catalogue, payment fraud scoring, or card/channel fraud analytics. |
| **Real-time screening** (pre-authorization / pre-onboarding) | **Partial** | **On-demand** sanctions name screen (`/compliance/sanctions/screen`) and snapshot-time **OpenSanctions** lookup in `build_alert_snapshot`. **Not** wired as a **synchronous** gate before every payment auth or account opening in a core banking sense. |
| **Real-time monitoring** (transactions as they occur; alert within stipulated time) | **Partial** | New transactions trigger **background** AML pipeline and can create alerts immediately **after** ingest. **No** contractual latency SLA, **no** clock for “alert within X minutes.” |
| **Watchlist screening** | **Partial** | **OpenSanctions** (online consolidated dataset) as **watchlist-style** screening; optional API key. **No** internal maintained watchlist DB, **no** PEP-only list, **no** custom institution lists with versioning/audit of list changes. |

---

## Summary Scorecard

| Area | Yes | Partial | Gap |
|------|-----|---------|-----|
| System integration & scalability | 0 | 7 | 0 |
| Security & data protection | 0 | 3 | 3 |
| User interface & customization | 0 | 4 | 0 |
| Additional recommended features | 0 | 6 | 2 |

**Overall:** The platform demonstrates **API-first AML processing**, **scoped RBAC**, **ML + rules + LLM assist**, and **external sanctions lookup**, suitable as a **prototype or pilot**. It does **not** yet satisfy enterprise expectations for **MFA**, **NDPA tooling**, **DR/RTO/RPO**, **adaptive calibration**, **dedicated fraud**, **continuous adverse media**, or **certified national data exchange**.

---

## Suggested enhancement roadmap (high level)

1. **Integration:** Document OpenAPI + example CBS/KYC integration patterns; add async **queue** (Kafka/Redis) workers for scoring isolation.  
2. **Security:** MFA (TOTP/WebAuthn), secrets management, TLS enforcement guide, field-level encryption for sensitive PII where required.  
3. **Compliance:** NDPA data inventory, retention, subject rights; define **RTO/RPO** and backup.  
4. **Screening:** Local watchlist store with change audit; optional vendor adapters; synchronous screening hook contract for onboarding.  
5. **ASC:** Feedback loop from alert outcomes to threshold/rule tuning (even if manual approval first).  
6. **Multi-entity:** Tenant model, entity-level config, consolidated reporting.

---

*Evidence paths include: `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/v1/transactions.py`, `backend/app/services/anomaly_engine.py`, `backend/app/services/alert_snapshot.py`, `backend/app/services/sanctions_screening.py`, `backend/app/core/security.py`, `backend/app/api/v1/federated.py`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Settings.tsx`.*

# Risk Scoring Report — CT-2026-001

| Field | Value |
|---|---|
| **Contract** | `CT-2026-001` |
| **Generated** | 2026-03-10 |
| **Scoring Version** | 1.0 |
| **Total Clauses** | 10 |
| 🔴 HIGH Priority | **3** |
| 🟡 MEDIUM Priority | **5** |
| 🟢 LOW Priority | **2** |

---

## Clause Risk Scores

| Clause | Score | Priority | Severity | Topic | SR-Matches | Obligation |
|---|:---:|:---:|:---:|---|---|---|
| `CL-103` | **10.0** | 🔴 HIGH | 🔴 HIGH | `REGULATORY_COMPLIANCE` | ✅`SR-NIS2-01`(95%) | NON_TRANSFERABLE_REGULATION |
| `CL-108` | **10.0** | 🔴 HIGH | 🔴 HIGH | `REGULATORY_COMPLIANCE` | ✅`SR-DORA-02`(90%) ⚠️`SR-DORA-01`(68%) | NON_TRANSFERABLE_REGULATION |
| `CL-104` | **8.8** | 🔴 HIGH | 🔴 HIGH | `AUDIT_RIGHTS` | ⚠️`SR-ISO27001-03`(78%) | OPERATIONAL_RISK |
| `CL-105` | **6.2** | 🟡 MEDIUM | 🟡 MEDIUM | `DATA_PROTECTION` | ⚠️`SR-GDPR-02`(65%) | SCOPE_UNDEFINED |
| `CL-106` | **6.2** | 🟡 MEDIUM | 🟡 MEDIUM | `DATA_PROTECTION` | ⚠️`SR-GDPR-02`(65%) | CUSTOMER_RESPONSIBILITY |
| `CL-102` | **6.0** | 🟡 MEDIUM | 🟡 MEDIUM | `REGULATORY_COMPLIANCE` | — | SCOPE_UNDEFINED |
| `CL-107` | **6.0** | 🟡 MEDIUM | 🟡 MEDIUM | `INCIDENT_MANAGEMENT` | — | OPERATIONAL_RISK |
| `CL-109` | **6.0** | 🟡 MEDIUM | 🟡 MEDIUM | `SECURITY_CONTROLS` | — | AMBIGUOUS_REQUIREMENT |
| `CL-101` | **1.5** | 🟢 LOW | 🟢 LOW | — | — | VALID |
| `CL-110` | **1.5** | 🟢 LOW | 🟢 LOW | — | — | VALID |

---

## Topic Risk Summary

| Topic | Clauses | Max Score | Avg Score | Total | Priority |
|---|:---:|:---:|:---:|:---:|:---:|
| **Regulatory Compliance** | 3 | **10.0** | 8.7 | 26.0 | 🔴 HIGH |
| **Audit Rights** | 1 | **8.8** | 8.8 | 8.8 | 🔴 HIGH |
| **Data Protection** | 2 | **6.2** | 6.2 | 12.5 | 🟡 MEDIUM |
| **Incident Management** | 1 | **6.0** | 6.0 | 6.0 | 🟡 MEDIUM |
| **Security Controls** | 1 | **6.0** | 6.0 | 6.0 | 🟡 MEDIUM |
| **—** | 2 | **1.5** | 1.5 | 3.0 | 🟢 LOW |

---

## Scoring Rules

| Component | Weight |
|---|---|
| Severity HIGH | base 7.0 (floor 7.0) |
| Severity MEDIUM | base 4.0 |
| Severity LOW / VALID | base 1.5 |
| Topic: REGULATORY_COMPLIANCE / DATA_PROTECTION | +1.5 |
| Topic: SECURITY_CONTROLS / AUDIT_RIGHTS | +1.0 |
| Topic: INCIDENT_MANAGEMENT | +0.5 |
| SR DIRECT_MATCH | +1.5 per match (cap 2.0) |
| SR PARTIAL_MATCH | +0.75 per match (cap 2.0) |
| NO_MATCH (non-VALID) | floor 6.0 |
| AMBIGUOUS_REQUIREMENT | score = max(severity+topic, best_confidence×10) |

---

## Score Breakdown per Clause

### `CL-103` — Score **10.0** · 🔴 HIGH

> *As the Provider constitutes an essential entity under the NIS2 Directive (EU 2022/2555) as implemented by the NIS2UmsuCG, the Provider shall submit incident rep…*

| | |
|---|---|
| **Obligation** | `NON_TRANSFERABLE_REGULATION` |
| **Severity** | 🔴 HIGH |
| **Topic** | Regulatory Compliance |
| **Page** | 4 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 7.0 |
| + Topic Bonus | +1.5 |
| + SR-Match Bonus | +1.5 |
| Raw | 10.0 |
| **Final (clamped 1–10)** | **10.0** |
| Floors applied | `None` |

**SR Evidence:**

> ✅ `SR-NIS2-01` — NIS2 · **DIRECT_MATCH** 95% · solid `-->`

**Suggested Replacement (excerpt):**

```
The Customer acknowledges that all reporting and notification obligations owed to any competent supervisory authority (including but not lim…
```

### `CL-108` — Score **10.0** · 🔴 HIGH

> *As the Customer is a financial entity regulated under DORA (Regulation EU 2022/2554), the Provider shall assume all ICT-related regulatory reporting obligations…*

| | |
|---|---|
| **Obligation** | `NON_TRANSFERABLE_REGULATION` |
| **Severity** | 🔴 HIGH |
| **Topic** | Regulatory Compliance |
| **Page** | 9 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 7.0 |
| + Topic Bonus | +1.5 |
| + SR-Match Bonus | +2.0 |
| Raw | 10.5 |
| **Final (clamped 1–10)** | **10.0** |
| Floors applied | `None` |

**SR Evidence:**

> ✅ `SR-DORA-02` — DORA · **DIRECT_MATCH** 90% · solid `-->`
> ⚠️ `SR-DORA-01` — DORA · **PARTIAL_MATCH** 68% · dashed `-.->` 

**Suggested Replacement (excerpt):**

```
The Customer acknowledges that all reporting and notification obligations owed to any competent supervisory authority (including but not lim…
```

### `CL-104` — Score **8.8** · 🔴 HIGH

> *Security incident response obligations:
• The Provider shall notify the Customer of any detected security incident within 15 minutes of internal detection, rega…*

| | |
|---|---|
| **Obligation** | `OPERATIONAL_RISK` |
| **Severity** | 🔴 HIGH |
| **Topic** | Audit Rights |
| **Page** | 5 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 7.0 |
| + Topic Bonus | +1.0 |
| + SR-Match Bonus | +0.75 |
| Raw | 8.75 |
| **Final (clamped 1–10)** | **8.75** |
| Floors applied | `None` |

**SR Evidence:**

> ⚠️ `SR-ISO27001-03` — ISO27001 · **PARTIAL_MATCH** 78% · dashed `-.->` 

**Suggested Replacement (excerpt):**

```
Incident Notification: The Provider shall notify the Customer of any confirmed security incident materially affecting Customer data within f…
```

### `CL-105` — Score **6.2** · 🟡 MEDIUM

> *The Provider shall ensure compliance with relevant data protection standards and applicable security frameworks at all times. All data processing activities mus…*

| | |
|---|---|
| **Obligation** | `SCOPE_UNDEFINED` |
| **Severity** | 🟡 MEDIUM |
| **Topic** | Data Protection |
| **Page** | 6 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 4.0 |
| + Topic Bonus | +1.5 |
| + SR-Match Bonus | +0.75 |
| Raw | 6.25 |
| **Final (clamped 1–10)** | **6.25** |
| Floors applied | `None` |

**SR Evidence:**

> ⚠️ `SR-GDPR-02` — GDPR · **PARTIAL_MATCH** 65% · dashed `-.->` 

**Suggested Replacement (excerpt):**

```
The Provider shall comply with the data protection, security, and operational resilience standards enumerated in Schedule [A] (Applicable Re…
```

### `CL-106` — Score **6.2** · 🟡 MEDIUM

> *The Provider shall determine the sensitivity classification of all Customer data processed under this Agreement and shall define appropriate data retention peri…*

| | |
|---|---|
| **Obligation** | `CUSTOMER_RESPONSIBILITY` |
| **Severity** | 🟡 MEDIUM |
| **Topic** | Data Protection |
| **Page** | 7 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 4.0 |
| + Topic Bonus | +1.5 |
| + SR-Match Bonus | +0.75 |
| Raw | 6.25 |
| **Final (clamped 1–10)** | **6.25** |
| Floors applied | `None` |

**SR Evidence:**

> ⚠️ `SR-GDPR-02` — GDPR · **PARTIAL_MATCH** 65% · dashed `-.->` 

**Suggested Replacement (excerpt):**

```
The Customer, acting as data controller within the meaning of GDPR Art. 4(7), shall remain solely responsible for: (i) determining and docum…
```

### `CL-102` — Score **6.0** · 🟡 MEDIUM

> *The Provider shall at all times comply with all applicable laws, regulations, and industry best practices relevant to the provision of the services, including b…*

| | |
|---|---|
| **Obligation** | `SCOPE_UNDEFINED` |
| **Severity** | 🟡 MEDIUM |
| **Topic** | Regulatory Compliance |
| **Page** | 3 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 4.0 |
| + Topic Bonus | +1.5 |
| + SR-Match Bonus | +0.0 |
| Raw | 6.0 |
| **Final (clamped 1–10)** | **6.0** |
| Floors applied | `NO_MATCH_FLOOR` |

> ⚪ No direct SR-match — unknown-gap floor applied.

**Suggested Replacement (excerpt):**

```
The Provider shall comply with the data protection, security, and operational resilience standards enumerated in Schedule [A] (Applicable Re…
```

### `CL-107` — Score **6.0** · 🟡 MEDIUM

> *In the event of a data breach or any security incident potentially affecting Customer data, the Provider shall immediately notify all affected parties, relevant…*

| | |
|---|---|
| **Obligation** | `OPERATIONAL_RISK` |
| **Severity** | 🟡 MEDIUM |
| **Topic** | Incident Management |
| **Page** | 8 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 4.0 |
| + Topic Bonus | +0.5 |
| + SR-Match Bonus | +0.0 |
| Raw | 6.0 |
| **Final (clamped 1–10)** | **6.0** |
| Floors applied | `NO_MATCH_FLOOR` |

> ⚪ No direct SR-match — unknown-gap floor applied.

**Suggested Replacement (excerpt):**

```
Incident Notification: The Provider shall notify the Customer of any confirmed security incident materially affecting Customer data within f…
```

### `CL-109` — Score **6.0** · 🟡 MEDIUM

> *The Provider shall implement appropriate technical and organizational measures to ensure the security of all data processed. The Provider shall apply industry b…*

| | |
|---|---|
| **Obligation** | `AMBIGUOUS_REQUIREMENT` |
| **Severity** | 🟡 MEDIUM |
| **Topic** | Security Controls |
| **Page** | 10 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 4.0 |
| + Topic Bonus | +1.0 |
| + SR-Match Bonus | +0.0 |
| Raw | 6.0 |
| **Final (clamped 1–10)** | **6.0** |
| Floors applied | `AMBIGUOUS_OVERRIDE, NO_MATCH_FLOOR` |

> ⚪ No direct SR-match — unknown-gap floor applied.

**Suggested Replacement (excerpt):**

```
The Provider shall implement and maintain information security controls in accordance with ISO/IEC 27001:2022. Compliance shall be evidenced…
```

### `CL-101` — Score **1.5** · 🟢 LOW

> *The Provider shall maintain a monthly uptime SLA of 99.9% as measured by a mutually agreed third-party monitoring service. Service credits for SLA breaches shal…*

| | |
|---|---|
| **Obligation** | `VALID` |
| **Severity** | 🟢 LOW |
| **Topic** | — |
| **Page** | 2 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 1.5 |
| + Topic Bonus | +0.0 |
| + SR-Match Bonus | +0.0 |
| Raw | 1.5 |
| **Final (clamped 1–10)** | **1.5** |
| Floors applied | `None` |

> ⚪ No direct SR-match — unknown-gap floor applied.

### `CL-110` — Score **1.5** · 🟢 LOW

> *Encryption Standard | Algorithm | Scope | Review Cycle
Data at rest | AES-256-GCM | All Customer data on Provider infrastructure | Annual
Data in transit | TLS …*

| | |
|---|---|
| **Obligation** | `VALID` |
| **Severity** | 🟢 LOW |
| **Topic** | — |
| **Page** | 11 |

**Score components:**

| Component | Value |
|---|---|
| Base (Severity) | 1.5 |
| + Topic Bonus | +0.0 |
| + SR-Match Bonus | +0.0 |
| Raw | 1.5 |
| **Final (clamped 1–10)** | **1.5** |
| Floors applied | `None` |

> ⚪ No direct SR-match — unknown-gap floor applied.

# Remediation Action Plan — CT-2026-001

| Field | Value |
|---|---|
| **Contract** | `CT-2026-001` |
| **Generated** | 2026-03-10 |
| **Pipeline Stage** | Stage 12 — Remediation Action Plan |
| **Total Actions** | 5 |
| 🔴 HIGH Priority | **2** |
| 🟡 MEDIUM Priority | **3** |
| 🟢 LOW Priority | **0** |
| Excluded (VALID) | `CL-101`, `CL-110` |

---

## Executive Summary

| Action | Priority | Topic(s) | Clauses | Max Score | Owner |
|---|:---:|---|---|:---:|---|
| [ACT-2026-001](#act2026001) | 🔴 **HIGH** | Regulatory Compliance | `CL-103`, `CL-108` | **10.0** | Legal / Compliance Officer |
| [ACT-2026-002](#act2026002) | 🔴 **HIGH** | Audit Rights / Incident Management | `CL-104`, `CL-107` | **8.8** | Legal / Compliance Officer |
| [ACT-2026-003](#act2026003) | 🟡 **MEDIUM** | Data Protection | `CL-106` | **6.2** | Data Protection Officer (DPO) |
| [ACT-2026-004](#act2026004) | 🟡 **MEDIUM** | Regulatory Compliance / Data Protection | `CL-102`, `CL-105` | **6.2** | Legal / Compliance Officer |
| [ACT-2026-005](#act2026005) | 🟡 **MEDIUM** | Security Controls | `CL-109` | **6.0** | CISO / Security Officer |

---

## Action Detail Cards

---

### ACT-2026-001 — Non-transferable regulatory obligation

| Field | Value |
|---|---|
| **Action ID** | `ACT-2026-001` |
| **Priority** | 🔴 **HIGH** |
| **Topic(s)** | `Regulatory Compliance` |
| **Affected Clauses** | `CL-103`, `CL-108` |
| **Contract Pages** | 4, 9 |
| **Finding Type** | `NON_TRANSFERABLE_REGULATION` |
| **Max Risk Score** | **10.0** / 10 |
| **Responsible Owner** | Legal / Compliance Officer |
| **Estimated Effort** | 3–5 business days |
| **Expected Risk Reduction** | Eliminates direct regulatory exposure; expected clause score ≤ 3.0 post-remediation. |
| **Merged Clauses** | 2 |

**Risk scores by clause:**

> `CL-103` → **10.0** / 10
> `CL-108` → **10.0** / 10

#### Problem Description

The clause purports to transfer the Customer's own statutory or regulatory reporting obligations directly to the Provider. Regulatory obligations arising from the Customer's status as a regulated entity (e.g. under DORA, NIS2, GDPR) are non-delegable: the regulated entity remains solely responsible to the competent authority. Such a transfer is legally ineffective and exposes the Provider to undefined regulatory liability.

#### Regulatory Evidence

| SR ID | Framework | Match Type | Confidence | Source Clause |
|---|---|---|:---:|---|
| `SR-NIS2-01` | **NIS2** | ✅ DIRECT_MATCH | 95% | `CL-103` |
| `SR-DORA-02` | **DORA** | ✅ DIRECT_MATCH | 90% | `CL-108` |
| `SR-DORA-01` | **DORA** | ⚠️ PARTIAL_MATCH | 68% | `CL-108` |

#### Negotiation Guidance

Reject any clause that makes the Provider the primary obligor toward a regulatory authority on the Customer's behalf. The Provider may agree to support the Customer operationally (e.g. timely incident notifications, supplying audit evidence, providing SIEM-compatible logs), but must not file reports to BaFin, BSI, EBA or any other authority in the Customer's name. Propose an Assistance Model: the Customer retains the obligation; the Provider commits to specific, scoped assistance actions within agreed timeframes. Ensure all reference to 'on behalf of' or 'in the name of' the Customer is removed or limited to duly executed power-of-attorney arrangements that are separately negotiated.

#### Recommended Clause Change

```
The Customer acknowledges that all reporting and notification obligations owed to any competent supervisory authority (including but not limited to BaFin, BSI, and EBA) arising from the Customer's status as a regulated entity are borne exclusively by the Customer. The Provider shall support the Customer in discharging such obligations by: (i) notifying the Customer of any confirmed security incident materially affecting Customer data within four (4) hours of the Provider's internal incident declaration; (ii) providing a detailed incident report, including technical root-cause analysis and remediation measures, within forty-eight (48) hours of such declaration; (iii) supplying evidence, logs, and documentation reasonably required by the Customer to prepare and submit its own regulatory reports; and (iv) making available a designated point of contact to liaise with the Customer's compliance team during any regulatory investigation. The Provider shall have no obligation to submit reports or make representations directly to any regulatory authority on behalf of the Customer unless acting under a separately executed, duly notarised power of attorney that specifically authorises such action.
```

---

### ACT-2026-002 — Operationally unrealistic obligation

| Field | Value |
|---|---|
| **Action ID** | `ACT-2026-002` |
| **Priority** | 🔴 **HIGH** |
| **Topic(s)** | `Audit Rights` · `Incident Management` |
| **Affected Clauses** | `CL-104`, `CL-107` |
| **Contract Pages** | 5, 8 |
| **Finding Type** | `OPERATIONAL_RISK` |
| **Max Risk Score** | **8.8** / 10 |
| **Responsible Owner** | Legal / Compliance Officer |
| **Secondary Owner(s)** | CISO / Security Officer |
| **Estimated Effort** | 3–5 business days |
| **Expected Risk Reduction** | Eliminates direct regulatory exposure; expected clause score ≤ 3.0 post-remediation. |
| **Merged Clauses** | 2 |

**Risk scores by clause:**

> `CL-104` → **8.8** / 10
> `CL-107` → **6.0** / 10

#### Problem Description

The clause imposes operationally unrealistic obligations — such as notification within minutes, unlimited or unscheduled audit access to all systems, or continuous real-time data feeds — that cannot be delivered reliably, create disproportionate security risk, and may be technically infeasible at scale. Undefined scope obligations (e.g. 'all systems', 'all stakeholders') create unbounded liability.

#### Regulatory Evidence

| SR ID | Framework | Match Type | Confidence | Source Clause |
|---|---|---|:---:|---|
| `SR-ISO27001-03` | **ISO27001** | ⚠️ PARTIAL_MATCH | 78% | `CL-104` |

#### Negotiation Guidance

Replace all undefined or unrealistic time obligations with specific, tiered SLAs that reflect the Provider's actual incident management process. Scope all audit rights to Customer-relevant systems only, with scheduled windows and advance notice. Replace real-time or continuous log feed requirements with periodic delivery or on-demand access within a defined SLA. Ensure all obligations are capped: unlimited access to internal infrastructure or source code is a security risk and should be replaced with scoped, third-party-auditor-mediated access. Attach a Technical Feasibility Statement for any sub-4-hour SLA obligations to document the operational basis.

#### Recommended Clause Change

```
Incident Notification: The Provider shall notify the Customer of any confirmed security incident materially affecting Customer data within four (4) business hours of the Provider's internal incident declaration. Notification shall include a preliminary impact assessment. A full incident report shall be delivered within forty-eight (48) hours. Audit Rights: The Customer or its appointed independent auditor may conduct one (1) compliance audit per calendar year upon thirty (30) calendar days' prior written notice, during normal business hours (Monday–Friday, 09:00–17:00 CET), and subject to the Provider's information security and confidentiality requirements. The scope of each audit shall be limited to systems, processes, and records directly related to the services provided under this Agreement. Emergency audits following a declared data breach shall be scoped and scheduled by written agreement between the parties within five (5) business days of the breach notification. Log Access: The Provider shall make available to the Customer, within twenty-four (24) hours of a written request, aggregated security event logs relating to Customer data environments, in a mutually agreed machine-readable format. Continuous or real-time streaming of internal security event data is not included in the standard service scope and may be agreed as a separate, commercially scoped service.
```

---

### ACT-2026-003 — Misassigned controller responsibility

| Field | Value |
|---|---|
| **Action ID** | `ACT-2026-003` |
| **Priority** | 🟡 **MEDIUM** |
| **Topic(s)** | `Data Protection` |
| **Affected Clauses** | `CL-106` |
| **Contract Pages** | 7 |
| **Finding Type** | `CUSTOMER_RESPONSIBILITY` |
| **Max Risk Score** | **6.2** / 10 |
| **Responsible Owner** | Data Protection Officer (DPO) |
| **Estimated Effort** | 1–2 business days |
| **Expected Risk Reduction** | Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation. |
| **Merged Clauses** | 1 |

**Risk scores by clause:**

> `CL-106` → **6.2** / 10

#### Problem Description

The clause assigns to the Provider obligations that are legally the Customer's own controller responsibilities under GDPR — specifically, determining data classification, defining retention periods, establishing lawful bases for processing, and conducting Data Protection Impact Assessments (DPIA). Under GDPR Art. 4(7) and Art. 24, these are non-delegable controller duties. The Provider, acting as processor under Art. 28, cannot lawfully make these determinations on the Customer's behalf.

#### Regulatory Evidence

| SR ID | Framework | Match Type | Confidence | Source Clause |
|---|---|---|:---:|---|
| `SR-GDPR-02` | **GDPR** | ⚠️ PARTIAL_MATCH | 65% | `CL-106` |

#### Negotiation Guidance

Reject all clauses that purport to transfer controller responsibilities to the Provider. Data classification, DPIA execution, lawful-basis determination, and retention policy definition must remain with the Customer. The Provider may offer supporting information (e.g. a description of technical processing operations to assist a DPIA), but cannot carry out the legal assessment. Propose a 'Controller Responsibilities Annex' that explicitly allocates these duties to the Customer and defines the Provider's supporting obligations (information supply, cooperation) with specific, bounded deliverables.

#### Recommended Clause Change

```
The Customer, acting as data controller within the meaning of GDPR Art. 4(7), shall remain solely responsible for: (i) determining and documenting the sensitivity classification of all personal data processed under this Agreement, as set out in the Data Classification Policy referenced in Schedule [B]; (ii) establishing the lawful basis for each category of processing under GDPR Art. 6 (and Art. 9 where special category data is involved) and documenting such basis in the Customer's Records of Processing Activities (RoPA); (iii) defining data retention periods for each category of Customer data, which the Provider shall implement on receipt of written instruction; and (iv) conducting any Data Protection Impact Assessment (DPIA) required under GDPR Art. 35. The Provider shall, upon written request and within fifteen (15) business days, supply the Customer with a description of the Provider's technical and organisational processing operations to assist the Customer in completing a DPIA. The Provider shall not be required to conduct, sign, or submit any DPIA on behalf of the Customer.
```

---

### ACT-2026-004 — Undefined regulatory scope

| Field | Value |
|---|---|
| **Action ID** | `ACT-2026-004` |
| **Priority** | 🟡 **MEDIUM** |
| **Topic(s)** | `Regulatory Compliance` · `Data Protection` |
| **Affected Clauses** | `CL-102`, `CL-105` |
| **Contract Pages** | 3, 6 |
| **Finding Type** | `SCOPE_UNDEFINED` |
| **Max Risk Score** | **6.2** / 10 |
| **Responsible Owner** | Legal / Compliance Officer |
| **Secondary Owner(s)** | Data Protection Officer (DPO) |
| **Estimated Effort** | 1–2 business days |
| **Expected Risk Reduction** | Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation. |
| **Merged Clauses** | 2 |

**Risk scores by clause:**

> `CL-102` → **6.0** / 10
> `CL-105` → **6.2** / 10

#### Problem Description

The clause references 'applicable laws', 'relevant regulations', or 'industry standards' without naming specific legal instruments, frameworks, or supervisory authorities. This creates an open-ended, indeterminate obligation that may expand without mutual agreement as laws change, and makes compliance verification impossible.

#### Regulatory Evidence

| SR ID | Framework | Match Type | Confidence | Source Clause |
|---|---|---|:---:|---|
| `SR-GDPR-02` | **GDPR** | ⚠️ PARTIAL_MATCH | 65% | `CL-105` |

#### Negotiation Guidance

Require the customer to enumerate all referenced legal instruments, standards, and frameworks in a contractual annex (e.g. Schedule A — Applicable Regulatory Frameworks). Any future changes to the applicable set must require written agreement by both parties, with a minimum 90-day implementation notice period and, where changes impose material additional cost, a right to renegotiate fees. Reject dynamic-scope language such as 'as may be amended from time to time' unless accompanied by a change management clause that gives the Provider adequate notice and a price adjustment mechanism.

#### Recommended Clause Change

```
The Provider shall comply with the data protection, security, and operational resilience standards enumerated in Schedule [A] (Applicable Regulatory Frameworks), as agreed by the parties in writing and attached hereto. Schedule [A] as at the Effective Date references the following instruments: [to be completed by the parties]. Where a change in applicable law or regulation requires amendment of Schedule [A], the Customer shall notify the Provider in writing no later than ninety (90) days prior to the effective date of such change. If the required amendment imposes material additional cost or operational burden on the Provider, the parties shall negotiate in good faith a corresponding adjustment to fees and timelines within thirty (30) days of such notification. No amendment to Schedule [A] shall take effect without the written countersignature of both parties.
```

---

### ACT-2026-005 — Vague / unmeasurable requirement

| Field | Value |
|---|---|
| **Action ID** | `ACT-2026-005` |
| **Priority** | 🟡 **MEDIUM** |
| **Topic(s)** | `Security Controls` |
| **Affected Clauses** | `CL-109` |
| **Contract Pages** | 10 |
| **Finding Type** | `AMBIGUOUS_REQUIREMENT` |
| **Max Risk Score** | **6.0** / 10 |
| **Responsible Owner** | CISO / Security Officer |
| **Estimated Effort** | 1–2 business days |
| **Expected Risk Reduction** | Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation. |
| **Merged Clauses** | 1 |

**Risk scores by clause:**

> `CL-109` → **6.0** / 10

#### Problem Description

The clause uses vague, unmeasurable language (e.g. 'industry best practices', 'state of the art', 'appropriate measures') that creates an indeterminate obligation. Without objective criteria, compliance cannot be verified and disputes cannot be resolved.

#### Regulatory Evidence

> ⚪ No direct SR match on record — clause flagged as unknown-gap (NO_MATCH floor applied in risk scoring).

#### Negotiation Guidance

Request that the customer replace all vague performance terms with objectively verifiable criteria, named standards, or defined metrics. Any security or compliance obligation must be measurable to be enforceable. Propose a named-standard model (e.g. ISO/IEC 27001:2022) with certification as evidence of compliance. Reject open-ended language that could expand scope without mutual agreement.

#### Recommended Clause Change

```
The Provider shall implement and maintain information security controls in accordance with ISO/IEC 27001:2022. Compliance shall be evidenced by a valid certification issued by an accredited third-party certification body, or, where certification is not yet obtained, a current Statement of Applicability signed by the Provider's Chief Information Security Officer. Any additional security requirements proposed by the Customer shall be documented in a mutually executed Security Requirements Schedule prior to taking effect and shall not impose obligations on the Provider materially beyond the referenced standard without corresponding adjustment to fees and timelines.
```

---

## Appendix: Excluded Clauses (VALID)

- `CL-101` — obligation assessment: **VALID** · no remediation required
- `CL-110` — obligation assessment: **VALID** · no remediation required

# Negotiation Package — CT-2026-001

| Field | Value |
|---|---|
| **Contract** | `CT-2026-001` |
| **Generated** | 2026-03-10 |
| **Pipeline Stage** | Stage 13 — Negotiation Package |
| **Total Items** | 5 |
| 🔴 HIGH | **2** |
| 🟡 MEDIUM | **3** |
| 🟢 LOW | **0** |
| **Frameworks** | `DORA` · `GDPR` · `ISO27001` · `NIS2` |

---

## Executive Summary

This negotiation package contains **all actionable remediation items** derived from the Stage 11 risk scoring and Stage 12 action plan for contract `CT-2026-001`. Each item maps one-to-one to an action from `action_plan.json` and provides the legal team with:
- the verbatim original clause text,
- a ready-to-use replacement clause,
- a structured negotiation argument (detailed for HIGH-priority items),
- a fallback / compromise position, and
- the full regulatory basis with article-level references.


### Priority Overview

| NEG ID | Action | Priority | Topic(s) | Clauses | Max Score | Owner |
|---|---|:---:|---|---|:---:|---|
| [NEG-2026-001](#neg2026001) | `ACT-2026-001` | 🔴 **HIGH** | Regulatory Compliance | `CL-103` · `CL-108` | **10.0** | Legal / Compliance Officer |
| [NEG-2026-002](#neg2026002) | `ACT-2026-002` | 🔴 **HIGH** | Audit Rights / Incident Management | `CL-104` · `CL-107` | **8.8** | Legal / Compliance Officer |
| [NEG-2026-003](#neg2026003) | `ACT-2026-003` | 🟡 **MEDIUM** | Data Protection | `CL-106` | **6.2** | Data Protection Officer (DPO) |
| [NEG-2026-004](#neg2026004) | `ACT-2026-004` | 🟡 **MEDIUM** | Regulatory Compliance / Data Protection | `CL-102` · `CL-105` | **6.2** | Legal / Compliance Officer |
| [NEG-2026-005](#neg2026005) | `ACT-2026-005` | 🟡 **MEDIUM** | Security Controls | `CL-109` | **6.0** | CISO / Security Officer |

### Key Risks

- 🔴 **NEG-2026-001** (Regulatory Compliance): Non-transferable regulatory obligation — max risk score **10.0 / 10**.
- 🔴 **NEG-2026-002** (Audit Rights / Incident Management): Operationally unrealistic obligation — max risk score **8.8 / 10**.

---

## Negotiation Items

---

### NEG-2026-001 — Non-transferable regulatory obligation
<a name="neg2026001"></a>

| Field | Value |
|---|---|
| **Negotiation ID** | `NEG-2026-001` |
| **Action ID** | `ACT-2026-001` |
| **Priority** | 🔴 **HIGH** |
| **Topic(s)** | `Regulatory Compliance` |
| **Affected Clauses** | `CL-103` · `CL-108` |
| **Finding Type** | `NON_TRANSFERABLE_REGULATION` |
| **Regulatory Basis** | `SR-NIS2-01` · `SR-DORA-02` · `SR-DORA-01` |
| **Max Risk Score** | **10.0** / 10 |
| **Owner** | Legal / Compliance Officer |
| **Estimated Effort** | 3–5 business days |
| **Expected Reduction** | Eliminates direct regulatory exposure; expected clause score ≤ 3.0 post-remediation. |

**Risk scores:**  

> `CL-103` → **10.0** / 10
> `CL-108` → **10.0** / 10

#### Problem Summary

The contract contains 2 HIGH and 3 MEDIUM-severity regulatory compliance issues involving NON_TRANSFERABLE_REGULATION, SCOPE_UNDEFINED, WEAK_MATCH. These clauses attempt to assign the Customer's non-transferable statutory obligations to the Provider and include undefined references to 'applicable law' that create open-ended liability.

**Finding detail**: The clause purports to transfer the Customer's own statutory or regulatory reporting obligations directly to the Provider. Regulatory obligations arising from the Customer's status as a regulated entity (e.g. under DORA, NIS2, GDPR) are non-delegable: the regulated entity remains solely responsible to the competent authority. Such a transfer is legally ineffective and exposes the Provider to undefined regulatory liability.

#### Negotiation Argument

**Position: Reject transfer of regulatory reporting obligations. Replace with Assistance Model.**

Clauses CL-103, CL-108 purport to make the Provider the primary obligor toward supervisory authorities for obligations that arise from the Customer's own regulated status. This is legally untenable on three grounds:

1. **Regulatory non-transferability (SR-NIS2-01 (NIS2) · SR-DORA-02 (DORA) · SR-DORA-01 (DORA))**: The cited instruments (NIS2 Art. 23, DORA Art. 19) impose incident-reporting duties directly on essential entities and financial entities respectively. These obligations are personal to the licensed / designated entity and cannot be reassigned by private contract. Any contractual clause purporting to do so is unenforceable as against the supervisory authority.

2. **Direct supervisory liability for the Provider**: Accepting primary obligor status means the Provider faces direct regulatory fines — up to €10 M or 2 % of global turnover under NIS2, and additional DORA sanctions — for reporting failures that may originate from Customer-side operational decisions, access restrictions, or delayed internal escalation, none of which the Provider controls.

3. **Operational impossibility**: Meeting supervisory notification deadlines (NIS2: 24 h initial / 72 h intermediate; DORA: 4 h initial / 24 h detailed) requires full access to Customer-side incident triage, regulatory correspondence, and decision-making chains. None of these are contractually guaranteed to the Provider, making the obligation structurally unfulfillable.

All clauses that transfer regulatory reporting obligations directly to the Provider must be removed or replaced with an Assistance Model: the Provider supports the Customer's compliance but cannot act as primary obligor to supervisory authorities. All open-ended references to 'applicable law' must be replaced with enumerated instruments in a mutually agreed contractual schedule, subject to a 90-day change notice and fee-adjustment mechanism.

**Non-negotiable floor**: The Provider will not sign any clause that designates it as direct reporting entity to BaFin, BSI, EBA, or any other supervisory authority absent a separately executed, notarised power of attorney.

#### Fallback / Compromise Position

If the Customer insists on some form of Provider involvement, accept an **Assistance and Notification Model** only: the Provider commits to (i) notifying the Customer within 4 business hours of incident declaration, (ii) delivering a full incident report within 48 hours, and (iii) supplying evidence and logs needed for the Customer to prepare its own regulatory filings. The Provider explicitly does NOT submit reports or make representations to any supervisory authority unless acting under a separately executed, duly notarised power of attorney.

---

### NEG-2026-002 — Operationally unrealistic obligation
<a name="neg2026002"></a>

| Field | Value |
|---|---|
| **Negotiation ID** | `NEG-2026-002` |
| **Action ID** | `ACT-2026-002` |
| **Priority** | 🔴 **HIGH** |
| **Topic(s)** | `Audit Rights` · `Incident Management` |
| **Affected Clauses** | `CL-104` · `CL-107` |
| **Finding Type** | `OPERATIONAL_RISK` |
| **Regulatory Basis** | `SR-ISO27001-03` |
| **Max Risk Score** | **8.8** / 10 |
| **Owner** | Legal / Compliance Officer |
| **Estimated Effort** | 3–5 business days |
| **Expected Reduction** | Eliminates direct regulatory exposure; expected clause score ≤ 3.0 post-remediation. |

**Risk scores:**  

> `CL-104` → **8.8** / 10
> `CL-107` → **6.0** / 10

#### Problem Summary

Audit rights clauses contain 1 HIGH and 1 MEDIUM-severity issues. The contract demands unlimited, unscheduled access to all Provider systems, networks, and source code repositories without prior notice — a scope that creates critical security and operational risk for the Provider.

**Finding detail**: The clause imposes operationally unrealistic obligations — such as notification within minutes, unlimited or unscheduled audit access to all systems, or continuous real-time data feeds — that cannot be delivered reliably, create disproportionate security risk, and may be technically infeasible at scale. Undefined scope obligations (e.g. 'all systems', 'all stakeholders') create unbounded liability.

#### Negotiation Argument

**Position: Replace infeasible obligations with a tiered SLA model aligned to SR-ISO27001-03 (ISO27001).**

Clauses CL-104, CL-107 impose notification obligations (e.g. 'within 15 minutes', 'immediately') that are operationally unachievable and create automatic, uncapped breach exposure:

1. **Technical impossibility**: A 15-minute wall-clock notification obligation from first detection requires automated triaging, human escalation, and customer notification to complete within a single human operational cycle. Security operations centres operate on tiered alerting, with P1 (critical) incidents typically declared after 15–30 minutes of investigation. Any earlier notification would convey unverified noise rather than actionable intelligence.

2. **Severity-blind scope**: Applying the same '15 minutes' or 'immediate' obligation to all incidents regardless of severity — from a failed login attempt to a full data exfiltration — creates an undifferentiated, unmanageable notification burden and renders the contractual SLA permanently in breach.

3. **Undefined notification recipients**: 'Immediately notify all affected parties, relevant regulatory authorities, and any other stakeholders' is unbounded. Combined with an immediate obligation, this exposes the Provider to liability for every recipient and every timeline, including direct regulatory authority notification (see ACT-2026-001 for separate treatment).

4. **ISO/IEC 27001:2022 Annex A Control 5.26** establishes a tiered incident response model as best practice. The recommended clause adopts: preliminary notification within 4 business hours, full report within 48 hours.

Unlimited, unscheduled, or unrestricted audit access to all Provider systems, infrastructure, and source code must be replaced with scoped, scheduled rights: one (1) annual compliance audit with thirty (30) calendar days' prior notice, limited to systems directly serving Customer data, conducted during normal business hours by a mutually agreed independent auditor. Emergency audits following a declared breach shall be scoped and scheduled within five (5) business days. Access to source code repositories is not included in standard audit scope. | Replace all undefined notification timeframes ('immediately', 'without delay') with a tiered SLA model: preliminary notification to the Customer within four (4) business hours of incident declaration; full report within forty-eight (48) hours. Direct regulatory authority reporting remains the Customer's obligation. Any obligation to notify 'all affected parties' or 'all stakeholders' must be scoped to named recipients with agreed timelines.

**Non-negotiable floor**: Any numerical obligation of less than 4 business hours for preliminary notification, or less than 48 hours for a full incident report, is not commercially acceptable.

#### Fallback / Compromise Position

If 4 business hours is commercially rejected, accept a maximum fallback of **8 business hours** for preliminary notification, **24 hours** for a detailed incident summary, and **72 hours** for a full root-cause report — provided the obligation is tied to 'confirmed security incidents materially affecting Customer data' (not all alerts) and severity classification is mutually defined in an Incident Severity Schedule annexed to the contract.

---

### NEG-2026-003 — Misassigned controller responsibility
<a name="neg2026003"></a>

| Field | Value |
|---|---|
| **Negotiation ID** | `NEG-2026-003` |
| **Action ID** | `ACT-2026-003` |
| **Priority** | 🟡 **MEDIUM** |
| **Topic(s)** | `Data Protection` |
| **Affected Clauses** | `CL-106` |
| **Finding Type** | `CUSTOMER_RESPONSIBILITY` |
| **Regulatory Basis** | `SR-GDPR-02` |
| **Max Risk Score** | **6.2** / 10 |
| **Owner** | Data Protection Officer (DPO) |
| **Estimated Effort** | 1–2 business days |
| **Expected Reduction** | Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation. |

**Risk scores:**  

> `CL-106` → **6.2** / 10

#### Problem Summary

Data protection provisions contain 3 HIGH and 2 MEDIUM-severity issues (CUSTOMER_RESPONSIBILITY, MISSING, WEAK_MATCH). Controller-level GDPR duties (data classification, DPIA, lawful-basis determination) have been misallocated to the Provider as processor. International data transfer clauses lack explicit transfer mechanisms.

**Finding detail**: The clause assigns to the Provider obligations that are legally the Customer's own controller responsibilities under GDPR — specifically, determining data classification, defining retention periods, establishing lawful bases for processing, and conducting Data Protection Impact Assessments (DPIA). Under GDPR Art. 4(7) and Art. 24, these are non-delegable controller duties. The Provider, acting as processor under Art. 28, cannot lawfully make these determinations on the Customer's behalf.

#### Negotiation Argument

**Position**: Reject all clauses that purport to transfer controller responsibilities to the Provider. Data classification, DPIA execution, lawful-basis determination, and retention policy definition must remain with the Customer. The Provider may offer supporting information (e.g. a description of technical processing operations to assist a DPIA), but cannot carry out the legal assessment. Propose a 'Controller Responsibilities Annex' that explicitly allocates these duties to the Customer and defines the Provider's supporting obligations (information supply, cooperation) with specific, bounded deliverables.

Regulatory basis: SR-GDPR-02 (GDPR).

All GDPR controller obligations — data classification, DPIA execution, lawful-basis determination, and retention-period definition — must be reassigned to the Customer as data controller. The Provider's role is limited to processor obligations under GDPR Art. 28. International data transfer mechanisms must be explicitly named (e.g. Standard Contractual Clauses). Subprocessor provisions must reference a maintained register with minimum 30-day advance notification of changes.

#### Fallback / Compromise Position

If the Customer insists the Provider 'assists' with classification, accept language under which the Provider provides a **technical data inventory** within 15 business days of a written request, describing processing operations and data categories. The Customer retains all classification decisions, lawful basis determinations, and DPIA obligations as data controller. The Provider's input is advisory only and does not constitute assumption of controller duties.

---

### NEG-2026-004 — Undefined regulatory scope
<a name="neg2026004"></a>

| Field | Value |
|---|---|
| **Negotiation ID** | `NEG-2026-004` |
| **Action ID** | `ACT-2026-004` |
| **Priority** | 🟡 **MEDIUM** |
| **Topic(s)** | `Regulatory Compliance` · `Data Protection` |
| **Affected Clauses** | `CL-102` · `CL-105` |
| **Finding Type** | `SCOPE_UNDEFINED` |
| **Regulatory Basis** | `SR-GDPR-02` |
| **Max Risk Score** | **6.2** / 10 |
| **Owner** | Legal / Compliance Officer |
| **Estimated Effort** | 1–2 business days |
| **Expected Reduction** | Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation. |

**Risk scores:**  

> `CL-102` → **6.0** / 10
> `CL-105` → **6.2** / 10

#### Problem Summary

The contract contains 2 HIGH and 3 MEDIUM-severity regulatory compliance issues involving NON_TRANSFERABLE_REGULATION, SCOPE_UNDEFINED, WEAK_MATCH. These clauses attempt to assign the Customer's non-transferable statutory obligations to the Provider and include undefined references to 'applicable law' that create open-ended liability.

**Finding detail**: The clause references 'applicable laws', 'relevant regulations', or 'industry standards' without naming specific legal instruments, frameworks, or supervisory authorities. This creates an open-ended, indeterminate obligation that may expand without mutual agreement as laws change, and makes compliance verification impossible.

#### Negotiation Argument

**Position**: Require the customer to enumerate all referenced legal instruments, standards, and frameworks in a contractual annex (e.g. Schedule A — Applicable Regulatory Frameworks). Any future changes to the applicable set must require written agreement by both parties, with a minimum 90-day implementation notice period and, where changes impose material additional cost, a right to renegotiate fees. Reject dynamic-scope language such as 'as may be amended from time to time' unless accompanied by a change management clause that gives the Provider adequate notice and a price adjustment mechanism.

Regulatory basis: SR-GDPR-02 (GDPR).

All clauses that transfer regulatory reporting obligations directly to the Provider must be removed or replaced with an Assistance Model: the Provider supports the Customer's compliance but cannot act as primary obligor to supervisory authorities. All open-ended references to 'applicable law' must be replaced with enumerated instruments in a mutually agreed contractual schedule, subject to a 90-day change notice and fee-adjustment mechanism. | All GDPR controller obligations — data classification, DPIA execution, lawful-basis determination, and retention-period definition — must be reassigned to the Customer as data controller. The Provider's role is limited to processor obligations under GDPR Art. 28. International data transfer mechanisms must be explicitly named (e.g. Standard Contractual Clauses). Subprocessor provisions must reference a maintained register with minimum 30-day advance notification of changes.

#### Fallback / Compromise Position

If the Customer refuses a Schedule [A], accept a clause that enumerates the four currently applicable frameworks directly in the body of the clause: GDPR (EU) 2016/679, DORA (EU) 2022/2554, NIS2 Directive 2022/2555, and ISO/IEC 27001:2022. Any future additions require 90 days' written notice and, if they impose material cost, trigger a fee-adjustment negotiation within 30 days.

---

### NEG-2026-005 — Vague / unmeasurable requirement
<a name="neg2026005"></a>

| Field | Value |
|---|---|
| **Negotiation ID** | `NEG-2026-005` |
| **Action ID** | `ACT-2026-005` |
| **Priority** | 🟡 **MEDIUM** |
| **Topic(s)** | `Security Controls` |
| **Affected Clauses** | `CL-109` |
| **Finding Type** | `AMBIGUOUS_REQUIREMENT` |
| **Regulatory Basis** | — |
| **Max Risk Score** | **6.0** / 10 |
| **Owner** | CISO / Security Officer |
| **Estimated Effort** | 1–2 business days |
| **Expected Reduction** | Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation. |

**Risk scores:**  

> `CL-109` → **6.0** / 10

#### Problem Summary

Security control obligations contain 2 HIGH and 1 MEDIUM-severity issues (AMBIGUOUS_REQUIREMENT, MISSING). Multiple clauses use unmeasurable language ('state of the art', 'industry best practices') or reference frameworks without naming them. Supply chain security provisions are insufficiently specific for NIS2 compliance.

**Finding detail**: The clause uses vague, unmeasurable language (e.g. 'industry best practices', 'state of the art', 'appropriate measures') that creates an indeterminate obligation. Without objective criteria, compliance cannot be verified and disputes cannot be resolved.

#### Negotiation Argument

**Position**: Request that the customer replace all vague performance terms with objectively verifiable criteria, named standards, or defined metrics. Any security or compliance obligation must be measurable to be enforceable. Propose a named-standard model (e.g. ISO/IEC 27001:2022) with certification as evidence of compliance. Reject open-ended language that could expand scope without mutual agreement.

Regulatory basis: no direct regulatory SR match on record.

All security obligation clauses must reference named, verifiable standards (e.g. ISO/IEC 27001:2022) with defined evidence requirements such as valid third-party certification or a current Statement of Applicability. Terms such as 'state of the art', 'industry best practices', or 'appropriate measures' must be replaced with objective, measurable criteria or a named standard. Supply chain security obligations must enumerate specific controls rather than reference generic frameworks.

#### Fallback / Compromise Position

If the Customer refuses to name ISO/IEC 27001:2022 explicitly, accept 'appropriate technical and organisational measures' **provided** the clause also states: 'For the purposes of this Agreement, compliance with ISO/IEC 27001:2022, as evidenced by a valid third-party certification or a current Statement of Applicability signed by the Provider\'s CISO, shall constitute fulfilment of this obligation.' This binds the standard by reference while preserving the Customer's preferred softer language.


---

## Clause Comparison — Original vs Proposed

> Each section shows the verbatim original clause excerpt(s) followed by the recommended replacement clause.

---

### NEG-2026-001 · 🔴 HIGH · `CL-103` · `CL-108`

#### Current — `CL-103` (p. 4)

```
As the Provider constitutes an essential entity under the NIS2 Directive (EU 2022/2555) as implemented by the NIS2UmsuCG, the Provider shall submit incident reports directly to the competent national …
```

#### Current — `CL-108` (p. 9)

```
As the Customer is a financial entity regulated under DORA (Regulation EU 2022/2554), the Provider shall assume all ICT-related regulatory reporting obligations on behalf of the Customer, including th…
```

#### Proposed Replacement Clause

```
The Customer acknowledges that all reporting and notification obligations owed to any competent supervisory authority (including but not limited to BaFin, BSI, and EBA) arising from the Customer's status as a regulated entity are borne exclusively by the Customer. The Provider shall support the Customer in discharging such obligations by: (i) notifying the Customer of any confirmed security incident materially affecting Customer data within four (4) hours of the Provider's internal incident declaration; (ii) providing a detailed incident report, including technical root-cause analysis and remediation measures, within forty-eight (48) hours of such declaration; (iii) supplying evidence, logs, and documentation reasonably required by the Customer to prepare and submit its own regulatory reports; and (iv) making available a designated point of contact to liaise with the Customer's compliance team during any regulatory investigation. The Provider shall have no obligation to submit reports or make representations directly to any regulatory authority on behalf of the Customer unless acting under a separately executed, duly notarised power of attorney that specifically authorises such action.
```

---

### NEG-2026-002 · 🔴 HIGH · `CL-104` · `CL-107`

#### Current — `CL-104` (p. 5)

```
Security incident response obligations:
• The Provider shall notify the Customer of any detected security incident within 15 minutes of internal detection, regardless of severity classification.
• The…
```

#### Current — `CL-107` (p. 8)

```
In the event of a data breach or any security incident potentially affecting Customer data, the Provider shall immediately notify all affected parties, relevant regulatory authorities, and any other s…
```

#### Proposed Replacement Clause

```
Incident Notification: The Provider shall notify the Customer of any confirmed security incident materially affecting Customer data within four (4) business hours of the Provider's internal incident declaration. Notification shall include a preliminary impact assessment. A full incident report shall be delivered within forty-eight (48) hours. Audit Rights: The Customer or its appointed independent auditor may conduct one (1) compliance audit per calendar year upon thirty (30) calendar days' prior written notice, during normal business hours (Monday–Friday, 09:00–17:00 CET), and subject to the Provider's information security and confidentiality requirements. The scope of each audit shall be limited to systems, processes, and records directly related to the services provided under this Agreement. Emergency audits following a declared data breach shall be scoped and scheduled by written agreement between the parties within five (5) business days of the breach notification. Log Access: The Provider shall make available to the Customer, within twenty-four (24) hours of a written request, aggregated security event logs relating to Customer data environments, in a mutually agreed machine-readable format. Continuous or real-time streaming of internal security event data is not included in the standard service scope and may be agreed as a separate, commercially scoped service.
```

---

### NEG-2026-003 · 🟡 MEDIUM · `CL-106`

#### Current — `CL-106` (p. 7)

```
The Provider shall determine the sensitivity classification of all Customer data processed under this Agreement and shall define appropriate data retention periods for each category of Customer data i…
```

#### Proposed Replacement Clause

```
The Customer, acting as data controller within the meaning of GDPR Art. 4(7), shall remain solely responsible for: (i) determining and documenting the sensitivity classification of all personal data processed under this Agreement, as set out in the Data Classification Policy referenced in Schedule [B]; (ii) establishing the lawful basis for each category of processing under GDPR Art. 6 (and Art. 9 where special category data is involved) and documenting such basis in the Customer's Records of Processing Activities (RoPA); (iii) defining data retention periods for each category of Customer data, which the Provider shall implement on receipt of written instruction; and (iv) conducting any Data Protection Impact Assessment (DPIA) required under GDPR Art. 35. The Provider shall, upon written request and within fifteen (15) business days, supply the Customer with a description of the Provider's technical and organisational processing operations to assist the Customer in completing a DPIA. The Provider shall not be required to conduct, sign, or submit any DPIA on behalf of the Customer.
```

---

### NEG-2026-004 · 🟡 MEDIUM · `CL-102` · `CL-105`

#### Current — `CL-102` (p. 3)

```
The Provider shall at all times comply with all applicable laws, regulations, and industry best practices relevant to the provision of the services, including but not limited to all current and future…
```

#### Current — `CL-105` (p. 6)

```
The Provider shall ensure compliance with relevant data protection standards and applicable security frameworks at all times. All data processing activities must conform to applicable requirements as …
```

#### Proposed Replacement Clause

```
The Provider shall comply with the data protection, security, and operational resilience standards enumerated in Schedule [A] (Applicable Regulatory Frameworks), as agreed by the parties in writing and attached hereto. Schedule [A] as at the Effective Date references the following instruments: [to be completed by the parties]. Where a change in applicable law or regulation requires amendment of Schedule [A], the Customer shall notify the Provider in writing no later than ninety (90) days prior to the effective date of such change. If the required amendment imposes material additional cost or operational burden on the Provider, the parties shall negotiate in good faith a corresponding adjustment to fees and timelines within thirty (30) days of such notification. No amendment to Schedule [A] shall take effect without the written countersignature of both parties.
```

---

### NEG-2026-005 · 🟡 MEDIUM · `CL-109`

#### Current — `CL-109` (p. 10)

```
The Provider shall implement appropriate technical and organizational measures to ensure the security of all data processed. The Provider shall apply industry best practices and state-of-the-art secur…
```

#### Proposed Replacement Clause

```
The Provider shall implement and maintain information security controls in accordance with ISO/IEC 27001:2022. Compliance shall be evidenced by a valid certification issued by an accredited third-party certification body, or, where certification is not yet obtained, a current Statement of Applicability signed by the Provider's Chief Information Security Officer. Any additional security requirements proposed by the Customer shall be documented in a mutually executed Security Requirements Schedule prior to taking effect and shall not impose obligations on the Provider materially beyond the referenced standard without corresponding adjustment to fees and timelines.
```


---

## Regulatory References

All SR identifiers referenced in this package with their full regulation citations and key obligations.

### `SR-NIS2-01` — NIS2

| Field | Value |
|---|---|
| **SR ID** | `SR-NIS2-01` |
| **Regulation** | Directive (EU) 2022/2555 (NIS2 Directive) |
| **Article / Control** | Art. 23 — Reporting obligations for significant incidents |
| **Match Type** | ✅ DIRECT_MATCH · 95% confidence |
| **Source Clause** | `CL-103` |

**Key obligation**: Essential and important entities must notify the competent authority of significant incidents without undue delay. This obligation is personal to the regulated entity and cannot be contractually delegated.

**Enforcement / Penalties**: Administrative fines up to €10 M or 2 % of global annual turnover (essential entities); up to €7 M / 1.4 % (important entities).

### `SR-DORA-02` — DORA

| Field | Value |
|---|---|
| **SR ID** | `SR-DORA-02` |
| **Regulation** | Regulation (EU) 2022/2554 (DORA) |
| **Article / Control** | Art. 19 — Reporting of major ICT-related incidents |
| **Match Type** | ✅ DIRECT_MATCH · 90% confidence |
| **Source Clause** | `CL-108` |

**Key obligation**: Financial entities must submit initial, intermediate, and final reports on major ICT incidents directly to the competent authority. Contractual assignment of this reporting obligation to an ICT third-party provider is not permissible.

**Enforcement / Penalties**: Fines set by national competent authority; EBA / ESMA / EIOPA may issue additional supervisory measures including temporary prohibition of services.

### `SR-DORA-01` — DORA

| Field | Value |
|---|---|
| **SR ID** | `SR-DORA-01` |
| **Regulation** | Regulation (EU) 2022/2554 (DORA) |
| **Article / Control** | Art. 28 — General principles on sound management of ICT third-party risk |
| **Match Type** | ⚠️ PARTIAL_MATCH · 68% confidence |
| **Source Clause** | `CL-108` |

**Key obligation**: ICT third-party service providers must support financial entities in meeting DORA obligations. The financial entity (Customer) remains the primary obligor and cannot transfer regulatory accountability.

**Enforcement / Penalties**: Non-compliance may trigger mandatory contractual termination clauses under Art. 28(7) and enhanced supervisory scrutiny.

### `SR-ISO27001-03` — ISO27001

| Field | Value |
|---|---|
| **SR ID** | `SR-ISO27001-03` |
| **Regulation** | ISO/IEC 27001:2022 |
| **Article / Control** | Annex A — Control 5.26: Response to information security incidents |
| **Match Type** | ⚠️ PARTIAL_MATCH · 78% confidence |
| **Source Clause** | `CL-104` |

**Key obligation**: Organisations must establish, document, and implement a procedure for responding to information security incidents, including defined notification timelines proportionate to incident severity.

**Enforcement / Penalties**: Loss of ISO/IEC 27001 certification; contractual SLA breach exposure.

### `SR-GDPR-02` — GDPR

| Field | Value |
|---|---|
| **SR ID** | `SR-GDPR-02` |
| **Regulation** | Regulation (EU) 2016/679 (GDPR) |
| **Article / Control** | Art. 4(7) controller definition · Art. 24 controller obligations · Art. 28 processor obligations · Art. 35 DPIA |
| **Match Type** | ⚠️ PARTIAL_MATCH · 65% confidence |
| **Source Clause** | `CL-106` |

**Key obligation**: The data controller (Customer) bears sole responsibility for determining lawful bases for processing, conducting DPIAs, and defining data retention periods. These cannot be assigned to the data processor (Provider) by contract.

**Enforcement / Penalties**: Administrative fines up to €20 M or 4 % of global annual turnover for Art. 5/6/9 violations; up to €10 M / 2 % for Art. 24/28.

---

### SR Reference Summary

| SR ID | Framework | Regulation | Article | Match | Used in |
|---|---|---|---|:---:|---|
| `SR-NIS2-01` | **NIS2** | Directive (EU) 2022/2555 (NIS2 Directive)… | Art. 23 — Reporting obligations for sign… | ✅ 95% | `NEG-2026-001` |
| `SR-DORA-02` | **DORA** | Regulation (EU) 2022/2554 (DORA)… | Art. 19 — Reporting of major ICT-related… | ✅ 90% | `NEG-2026-001` |
| `SR-DORA-01` | **DORA** | Regulation (EU) 2022/2554 (DORA)… | Art. 28 — General principles on sound ma… | ⚠️ 68% | `NEG-2026-001` |
| `SR-ISO27001-03` | **ISO27001** | ISO/IEC 27001:2022… | Annex A — Control 5.26: Response to info… | ⚠️ 78% | `NEG-2026-002` |
| `SR-GDPR-02` | **GDPR** | Regulation (EU) 2016/679 (GDPR)… | Art. 4(7) controller definition · Art. 2… | ⚠️ 65% | `NEG-2026-003` · `NEG-2026-004` |

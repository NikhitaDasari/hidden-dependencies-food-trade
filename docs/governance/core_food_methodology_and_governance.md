# Core Food Methodology and Governance

## Analytical purpose

The capability identifies developmental country-food vulnerability signals and observed supplier-food systemic-reach signals for governed review. It is designed for transparent analysis, sensitivity testing, case-study development, and decision support.

## What the methodology measures

### Country-food dimensions

- Import exposure
- Net import dependence
- Supplier concentration
- Dominant-supplier share
- Concentration change
- Material supplier-count change

### Supplier-food dimensions

- Importer breadth
- Elevated-signal importer breadth
- Pooled supplier dependence
- Relationship persistence
- Vulnerability-weighted reach
- Six-scenario systemic stability
- Static supplier-removal consequences

## Population governance

### Primary population

```text
model_readiness_status = READY_FOR_PRIMARY_MODEL
evidence_confidence = HIGH_GOVERNED
```

Primary population size:

```text
661 country-food records
```

### Limited population

```text
model_readiness_status = READY_WITH_LIMITATIONS
evidence_confidence = LIMITED_GOVERNED
```

Limited population size:

```text
816 country-food records
```

Limited records are used only in expanded-population sensitivity analysis. They are not treated as equivalent to primary records.

## Model-stability approach

The methodology avoids selecting a single formula without testing alternatives. Build 3 compares six specifications, multiple transformation methods, alternative weights, and two populations.

Primary interpretation uses within-food-scope normalization because food categories have structurally different distributions. Pooled normalization remains a sensitivity test.

## Stability bands

### Country-food bands

```text
CONSISTENTLY_HIGH
OFTEN_HIGH
MIXED
OFTEN_LOW
CONSISTENTLY_LOW
```

### Supplier-food bands

```text
CONSISTENT_SYSTEMIC_SIGNAL
OFTEN_SYSTEMIC_SIGNAL
MIXED_SYSTEMIC_SIGNAL
OFTEN_LOCALIZED
CONSISTENTLY_LOCALIZED
```

Bands summarize persistence across scenarios. They are not official ranks.

## Observed supplier interpretation

Supplier relationships are labeled:

```text
IMMEDIATE_TRADE_PARTNER
```

The analysis does not infer agricultural production origin. An exporter may represent production, processing, storage, re-export, or commercial routing. Build 4 and Build 5 explicitly preserve this limitation.

## Static removal analysis

A static removal test measures what share of the observed importer-food network is associated with one supplier and what remains after removing that observed edge.

It does not model:

- Supplier substitution
- Inventory drawdown
- Price response
- Logistics response
- Policy response
- Production response
- Consumer response
- Trade rerouting

Static-removal results are stress-test diagnostics, not forecasts.

## Intervention hypotheses

Build 5 creates analyst-review hypotheses such as:

```text
SUPPLIER_DIVERSIFICATION_REVIEW
STRATEGIC_STOCK_POLICY_REVIEW
ALTERNATIVE_IMPORT_CHANNEL_REVIEW
DOMESTIC_RESILIENCE_REVIEW
TRADE_FACILITATION_REVIEW
SUPPLIER_MONITORING_PRIORITY
DATA_QUALITY_INVESTIGATION
NO_ACTION_WITHOUT_ADDITIONAL_EVIDENCE
```

These labels identify questions for review. They do not prove that an intervention is feasible, effective, cost-efficient, or appropriate.

## Prohibited claims

The controlled outputs prohibit:

```text
AGRICULTURAL_ORIGIN
CAUSAL_DISRUPTION
FAILURE_PROBABILITY
INTERVENTION_EFFECTIVENESS
OFFICIAL_COUNTRY_RANK
OFFICIAL_SUPPLIER_RANK
```

## Publication governance

A case can be analytically eligible while still requiring human review. Build 5 routes all eligible cases to a mandatory review queue.

```text
Eligible country-food cases: 143
Eligible supplier-food cases: 283
Total mandatory review cases: 426
```

Eligibility does not equal external approval.

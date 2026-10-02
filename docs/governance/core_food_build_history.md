# Core Food Analytical Build History

## Purpose

This document gives the team a clear record of what was implemented, why each build exists, how the builds connect, and which controls were established.

## End-to-end progression

```text
Build 1
Source-period inventory and temporal controls
        |
        v
Build 2
Historical country-food features
        |
        v
Build 3
Alternative vulnerability specifications and stability
        |
        v
Build 4
Supplier-food systemic chokepoint analysis
        |
        v
Build 5
Governed case studies and decision support
```

## Foundation work before Build 1

The project first established the underlying Core Food analytical foundation:

- Validated Food Balance Sheet inputs
- Built supplier-network inputs from observed trade relationships
- Standardized geography and M49 identifiers
- Defined country and Core Food mapping decisions
- Created model-readiness classifications
- Separated primary, limited, blocked, conversion-required, and sensitivity-only records

Relevant historical commits include:

```text
6868943 Build validated Core Food FBS and supplier network foundations
e00ed33 Implement enterprise Core Food readiness governance
233806c Record Core Food mapping and country governance decisions
```

## Build 1: Source-period inventory and controls

### Commit

```text
a8ced53 Build datathon source-period inventory and controls
```

### Purpose

Build 1 locked the authoritative analytical period and verified that every governed source supported the required years.

### Main implementation

```text
scripts/build_core_food_source_period_inventory.py
config/model_governance/core_food_period_policy.json
```

### Key controls

- Authoritative period fixed to 2021, 2022, and 2023
- Future information prohibited
- Source-period availability inventoried
- Period controls required to pass before downstream builds
- Source provenance preserved
- Official ranking disabled

### Key result

```text
Authoritative years: 2021, 2022, 2023
Period-control issue count: 0
All period controls: Passed
```

## Build 2: Historical feature foundation

### Commit

```text
38af2d0 Build Core Food historical feature panel
```

### Purpose

Build 2 created the annual country-food panel and period-level modeling features needed for vulnerability specification.

### Main implementation

```text
scripts/build_core_food_historical_features.py
config/model_governance/core_food_feature_policy.json
```

### Key outputs

```text
core_food_country_food_year_panel.csv
core_food_country_food_period_features.csv
core_food_primary_feature_dataset.csv
core_food_limited_feature_dataset.csv
core_food_feature_completeness.csv
core_food_feature_distributions.csv
core_food_feature_outlier_review.csv
core_food_temporal_leakage_checks.csv
```

### Validated populations

```text
Annual country-food-year rows: 12,144
Period country-food records: 4,048
Primary records: 661
Limited records: 816
Approved records: 1,477
Observed annual supplier networks: 5,631
```

### Key controls

- Annual country-food-year keys unique
- Primary and limited populations separated
- Blocked records excluded
- Missing supplier networks preserved as unavailable
- Supplier concentration measures bounded and reconciled
- Effective supplier count reconciled to inverse HHI
- First-year change fields left blank
- Temporal leakage checks passed
- Evidence confidence stored separately from analytical features
- No vulnerability score or official rank generated

### Important defect corrected

An initial merge collision caused annual supplier-network fields such as `supplier_count` to be suffixed or unavailable. The readiness merge was restricted to governance fields, and annual supplier-network metrics were merged separately at the correct annual grain.

## Integration of the governed analytical foundation

### Merge commit

```text
ef496a5 Integrate governed Core Food analytical foundation
```

### Purpose

This merge unified the historical feature branch, source-period controls, readiness governance, source documentation, and project structure into `main`.

## Build 3: Developmental model specification

### Commit

```text
6cc8ee2 Implement Core Food vulnerability specification framework
```

### Purpose

Build 3 tested whether country-food vulnerability signals remained stable across reasonable analytical choices.

### Main implementation

```text
scripts/build_core_food_model_specification.py
config/model_governance/core_food_model_specification.json
```

### Scenarios

```text
S1_EXPOSURE_ONLY
S2_EXPOSURE_HHI
S3_EXPOSURE_HHI_CONCENTRATION_TREND
S4_EXPOSURE_TOP1
S5_EXPOSURE_HHI_MATERIAL_SUPPLIER_LOSS
S6_NET_EXPOSURE_HHI
```

### Transformations

```text
WITHIN_SCOPE_PERCENTILE
WITHIN_SCOPE_EMPIRICAL_CDF
WINSORIZED_WITHIN_SCOPE
POOLED_PERCENTILE_SENSITIVITY
```

### Populations

```text
PRIMARY_ONLY
PRIMARY_PLUS_LIMITED
```

### Validated outputs

```text
Developmental scenario rows: 51,312
Primary stability records: 661
Primary records: 661
Limited records: 816
```

### Stability evidence

```text
Exposure-heavy weight correlation: 0.880284
Concentration-heavy weight correlation: 0.863859
Winsorized normalization correlation: 0.999362
Pooled normalization correlation: 0.959662
Primary-plus-limited correlation: 0.983703
```

### Key controls

- Six model specifications evaluated
- Concentration measures not double counted within a scenario
- Transformations externally configured
- Scenario correlations calculated
- Top-decile and top-quintile overlap calculated
- Leave-one-dimension-out sensitivity calculated
- Weight sensitivity calculated
- Normalization sensitivity calculated
- Primary-versus-expanded sensitivity calculated
- Stability bands used instead of official exact rankings

## Build 4: Supplier-food systemic chokepoints

### Commit

```text
d0f460e Build Core Food supplier chokepoint framework
```

### Purpose

Build 4 connected country-food vulnerability signals to observed supplier relationships, producing supplier-food systemic-reach measures and static removal stress tests.

### Main implementation

```text
scripts/build_core_food_supplier_chokepoints.py
config/model_governance/core_food_chokepoint_policy.json
```

### Validated outputs

```text
Annual supplier edges: 73,277
Annual importer-food network keys: 5,631
Period supplier relationships: 34,354
Primary relationship rows: 14,433
Expanded relationship rows: 28,931
Primary supplier-food nodes: 1,358
Expanded supplier-food nodes: 2,190
Scenario supplier-food rows: 8,148
Static removal tests: 73,277
```

### Six-scenario systemic stability

```text
CONSISTENT_SYSTEMIC_SIGNAL: 226
OFTEN_SYSTEMIC_SIGNAL: 57
MIXED_SYSTEMIC_SIGNAL: 46
OFTEN_LOCALIZED: 768
CONSISTENTLY_LOCALIZED: 261
```

### Important defect corrected

The first implementation calculated pooled supplier shares with a relationship-specific denominator that covered only the years in which each supplier appeared. It was corrected to use one common full-period importer-food denominator.

After correction:

```text
Importer-food-population records checked: 2,138
Minimum pooled supplier-share sum: 1.000000000000
Maximum pooled supplier-share sum: 1.000000000000
```

A production guardrail now stops the build if pooled shares do not reconcile to one.

### Static removal interpretation

The removal analysis is a static observed-network stress test. It assumes no substitution, inventory response, price response, logistics response, behavioral response, or trade rerouting.

## Build 5: Governed decision support

### Commit and pull request

```text
71df87e Build governed Core Food decision support
Pull Request #1
5b6b69d Merge pull request #1
```

### Purpose

Build 5 converted governed analytical outputs into traceable country-food cases, supplier-food cases, supporting evidence, intervention hypotheses, review queues, and publication controls.

### Main implementation

```text
scripts/build_core_food_decision_support.py
config/model_governance/core_food_decision_support_policy.json
```

### Validated case portfolio

```text
Primary country-food records: 661
Eligible country-food cases: 143
Primary supplier-food nodes: 1,358
Eligible supplier-food cases: 283
Supporting relationship rows: 14,433
Intervention hypotheses: 143
Mandatory analyst-review cases: 426
Publication-control records: 2,019
```

### Intervention hypotheses

```text
SUPPLIER_DIVERSIFICATION_REVIEW: 135
ALTERNATIVE_IMPORT_CHANNEL_REVIEW: 8
```

These categories are hypotheses for analyst review. They are not implementation recommendations and do not establish effectiveness.

### Sensitivity result

```text
Supplier-food nodes compared: 1,358
Mean absolute percentile movement: 0.032831
Classification changes: 45
```

### Key controls

- Every eligible case requires analyst review
- All supporting relationships remain traceable
- Evidence shares reconcile to one across all 661 primary country-food records
- Limited evidence remains sensitivity-only
- Publication records include limitations and prohibited-claims notices
- Intervention options remain hypotheses
- No official country or supplier rank generated

## Current main-branch milestone

```text
5b6b69d Merge pull request #1 from analysis/core-food-decision-support
```

At this milestone, Builds 1 through 5 are integrated into `main`.

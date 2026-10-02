# Core Food Validation and Controls

## Control philosophy

Each build must fail early when required inputs, grains, population contracts, mathematical identities, or governance restrictions are violated.

## Cross-build controls

- Authoritative period remains 2021–2023
- Country and supplier M49 identifiers are normalized
- Importer and supplier roles remain distinct
- Primary and limited populations remain distinguishable
- Missing networks remain unavailable rather than zero-filled
- Evidence confidence remains separate from analytical weighting
- Official country and supplier rankings remain disabled
- Source hashes and policy hashes are recorded

## Build 1 controls

```text
Authoritative period preserved
Issue count equals zero
All period controls pass
Future information prohibited
```

## Build 2 controls

```text
12,144 annual keys unique
4,048 period keys unique
661 primary records reconcile
816 limited records reconcile
5,631 observed annual network keys reconcile
Annual concentration measures bounded
Effective supplier count equals inverse HHI
First-year changes blank
Temporal leakage checks pass
Missing networks remain unavailable
```

## Build 3 controls

```text
Six scenarios evaluated
Four transformations evaluated
Two populations evaluated separately
Concentration not double counted
Scenario correlations calculated
Top-band overlap calculated
Leave-one-dimension-out sensitivity calculated
Weight sensitivity calculated
Normalization sensitivity calculated
Population sensitivity calculated
Official ranking disabled
```

## Build 4 controls

```text
73,277 annual supplier edges processed
5,631 annual network keys reconciled
Annual supplier shares sum to one
Period pooled supplier shares sum to one
Immediate trade partner labeled
Agricultural origin not inferred
Supplier-food grain preserved
Six-scenario stability calculated
Static removal assumes no substitution
Official supplier ranking disabled
```

## Build 5 controls

```text
661 primary country-food records traceable
1,358 primary supplier-food nodes traceable
14,433 supporting relationships present
143 intervention hypotheses generated
426 eligible cases require analyst review
2,019 publication-control records generated
Prohibited-claims notices attached
Interventions remain hypotheses
Official rankings disabled
```

## Important corrected defects

### Build 2 merge collision

Annual supplier-network metrics collided with pooled readiness fields. The fix restricted the readiness merge to governance context and merged annual network metrics independently.

### Build 4 pooled denominator

Pooled supplier shares initially used relationship-specific denominators. The fix created one common full-period denominator per importer-food record and added an automatic reconciliation guardrail.

## Current integrated validation

The tracked Build 1 through Build 5 scripts pass:

```text
python -m py_compile
ruff check
```

The local `main` branch matches `origin/main`, and the Build 5 pull request was merged successfully.

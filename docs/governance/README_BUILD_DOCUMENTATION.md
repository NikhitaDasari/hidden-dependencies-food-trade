# Core Food Analytical Capability

## Team Documentation Package

This package documents the governed Core Food analytical capability developed for the WomenInData 2026 project. It covers the complete implementation from source-period controls through decision support.

## Current implementation status

| Capability | Status | Main artifact |
|---|---:|---|
| Build 1: Source-period controls | Complete | `build_core_food_source_period_inventory.py` |
| Build 2: Historical features | Complete | `build_core_food_historical_features.py` |
| Build 3: Model specification | Complete | `build_core_food_model_specification.py` |
| Build 4: Supplier chokepoints | Complete | `build_core_food_supplier_chokepoints.py` |
| Build 5: Decision support | Complete | `build_core_food_decision_support.py` |

## Recommended repository placement

Copy the documentation files into:

```text
docs/governance/
```

Recommended structure:

```text
docs/
  governance/
    README_BUILD_DOCUMENTATION.md
    core_food_build_history.md
    core_food_architecture_and_data_flow.md
    core_food_methodology_and_governance.md
    core_food_reproducibility_runbook.md
    core_food_team_onboarding.md
    core_food_validation_and_controls.md
```

## Suggested reading order

1. `core_food_build_history.md`
2. `core_food_architecture_and_data_flow.md`
3. `core_food_methodology_and_governance.md`
4. `core_food_validation_and_controls.md`
5. `core_food_reproducibility_runbook.md`
6. `core_food_team_onboarding.md`

## Core governance position

The capability produces developmental analytical signals for controlled review. It does not produce official country rankings, official supplier rankings, causal disruption estimates, failure probabilities, agricultural-origin inferences, dynamic substitution forecasts, intervention-effectiveness claims, or automatic implementation recommendations.

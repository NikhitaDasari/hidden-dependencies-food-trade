# Core Food Reproducibility Runbook

## Purpose

This runbook describes how a team member can validate and rerun the governed pipeline.

## Prerequisites

- Clone the repository
- Check out `main`
- Create and activate the Python virtual environment
- Install dependencies from `requirements.txt`
- Make governed source files available in their expected paths

## Repository check

```bash
git switch main
git pull --ff-only origin main
git status --short
```

Expected: a clean working tree.

## Validate tracked policies

```bash
for file in \
  config/model_governance/core_food_period_policy.json \
  config/model_governance/core_food_feature_policy.json \
  config/model_governance/core_food_model_specification.json \
  config/model_governance/core_food_chokepoint_policy.json \
  config/model_governance/core_food_decision_support_policy.json
do
  python -m json.tool "$file" >/dev/null \
    && echo "PASS: $file" \
    || exit 1
done
```

## Validate Python scripts

```bash
python -m py_compile \
  scripts/build_core_food_source_period_inventory.py \
  scripts/build_core_food_historical_features.py \
  scripts/build_core_food_model_specification.py \
  scripts/build_core_food_supplier_chokepoints.py \
  scripts/build_core_food_decision_support.py
```

```bash
ruff check \
  scripts/build_core_food_source_period_inventory.py \
  scripts/build_core_food_historical_features.py \
  scripts/build_core_food_model_specification.py \
  scripts/build_core_food_supplier_chokepoints.py \
  scripts/build_core_food_decision_support.py
```

## Run order

Run builds in sequence because each build consumes controlled outputs from the prior builds.

### Build 1

```bash
python -u \
  scripts/build_core_food_source_period_inventory.py \
  2>&1 | tee \
  outputs/tables/core_food_source_inventory/core_food_source_period_inventory.log
```

### Build 2

```bash
python -u \
  scripts/build_core_food_historical_features.py \
  2>&1 | tee \
  outputs/tables/core_food_historical_features/core_food_historical_features.log
```

### Build 3

```bash
python -u \
  scripts/build_core_food_model_specification.py \
  2>&1 | tee \
  outputs/tables/core_food_model_specification/core_food_model_specification.log
```

### Build 4

```bash
python -u \
  scripts/build_core_food_supplier_chokepoints.py \
  2>&1 | tee \
  outputs/tables/core_food_supplier_chokepoints/core_food_supplier_chokepoints.log
```

### Build 5

```bash
python -u \
  scripts/build_core_food_decision_support.py \
  2>&1 | tee \
  outputs/tables/core_food_decision_support/core_food_decision_support.log
```

## Error scan

After each build:

```bash
grep -nE \
  'Traceback|SyntaxError|KeyError|ValueError|TypeError|Error|Exception|PerformanceWarning' \
  PATH_TO_BUILD_LOG
```

Expected: no output.

## Summary validation

Inspect the applicable summary JSON:

```bash
python -m json.tool \
  outputs/model_results/core_food_decision_support_summary.json
```

Confirm:

- Record counts match expected contracts
- All controls are true
- Source commit is recorded
- Input hashes are present
- Policy hash is present
- Output paths are present

## Git workflow for future builds

```bash
git switch main
git pull --ff-only origin main
git switch -c analysis/short-capability-name
```

After implementation and validation:

```bash
git add PATHS_TO_TRACKED_IMPLEMENTATION_AND_POLICY
git diff --cached --stat
git diff --cached --check
git commit -m "Concise governed capability message"
git push -u origin analysis/short-capability-name
```

Open a pull request into `main`, review changed files and checks, merge, delete the feature branch, then synchronize locally.

## Output policy

Generated outputs are ignored by Git. Commit scripts, policies, controlled metadata, tests, and documentation. Do not commit virtual environments, caches, local backups, logs, secrets, or generated analytical outputs unless the repository governance policy changes.

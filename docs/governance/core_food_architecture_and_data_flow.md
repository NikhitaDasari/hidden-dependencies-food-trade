# Core Food Architecture and Data Flow

## Architecture summary

The capability is implemented as a governed, sequential analytical pipeline. Each build validates its input contracts and writes outputs for the next build.

```text
Governed source data
  |
  +-- Food Balance Sheet foundation
  +-- Observed immediate trade-partner network
  +-- Geography and M49 standards
  +-- Country and food mapping decisions
  |
  v
Model readiness layer
  |
  v
Build 1: Period controls
  |
  v
Build 2: Historical features
  |
  v
Build 3: Alternative vulnerability specifications
  |
  v
Build 4: Supplier-food systemic chokepoints
  |
  v
Build 5: Governed decision support
```

## Analytical grains

### Annual country-food grain

```text
entity_m49
analytical_scope_code
year
```

Used for annual exposure, concentration, changes, and temporal controls.

### Period country-food grain

```text
entity_m49
analytical_scope_code
```

Used for period averages, trends, model specifications, and stability bands.

### Annual supplier-edge grain

```text
importer_m49
exporter_m49
analytical_scope_code
year
```

Used for observed supplier shares and static removal tests.

### Period importer-supplier-food grain

```text
importer_m49
exporter_m49
analytical_scope_code
```

Used for pooled supplier shares, persistence, and relationship evidence.

### Supplier-food grain

```text
exporter_m49
analytical_scope_code
```

Used for breadth, vulnerability-weighted reach, scenario stability, and supplier-food cases.

## Policy chain

```text
core_food_period_policy.json
  |
core_food_feature_policy.json
  |
core_food_model_specification.json
  |
core_food_chokepoint_policy.json
  |
core_food_decision_support_policy.json
```

Each policy records the analytical contract, enabled populations, thresholds, permitted interpretation, and prohibited claims.

## Build dependencies

### Build 1 inputs

- Source-period inventory
- Governed period policy
- Existing governed source outputs

### Build 2 inputs

- Period-control summary
- Annual Food Balance Sheet foundation
- Annual supplier-network foundation
- Model-readiness table
- Historical-feature policy

### Build 3 inputs

- Primary feature dataset
- Limited feature dataset
- Historical-feature policy
- Model-specification policy

### Build 4 inputs

- Annual supplier network
- Annual country-food panel
- Primary and limited feature populations
- Build 3 country-food stability
- Build 3 scenario results
- Chokepoint policy

### Build 5 inputs

- Build 3 country-food stability
- Primary and limited historical features
- Build 4 relationship evidence
- Build 4 supplier-food features
- Build 4 supplier-food stability
- Build 4 removal summary
- Decision-support policy

## Output handling

Generated analytical outputs are written below:

```text
outputs/tables/
outputs/model_results/
```

The repository ignores generated outputs while preserving the output directories through `.gitkeep` files. Reproducibility depends on tracked scripts, tracked policies, controlled source inputs, and source hashes recorded in summary JSON files.

## Provenance model

Every build summary records:

- Build timestamp
- Source commit
- Source-file hashes
- Policy hash
- Record counts
- Control results
- Output paths

This supports traceability from a published case back through the decision-support layer, supplier relationships, model stability, historical features, and governed source-period controls.

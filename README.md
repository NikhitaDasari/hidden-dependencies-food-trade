# Hidden Dependencies: Food-Import Vulnerability

**Women in Data 2026 · Trade track · Team Bites vs Bytes**  
Nikhita Dasari · Lalithendra Chowdari Mandava

Where is food-import vulnerability hiding in the global trade network? This project connects persistent country–food exposure with supplier concentration and the wider reach of shared suppliers. It supports prioritizing resilience review using FAOSTAT Food Balance Sheets and the Detailed Trade Matrix for 2021–2023.

## Executive summary

This repository implements a six-build, governance-first analytical pipeline for studying country-food vulnerability and supplier-food systemic reach using governed 2021-2023 data. The pipeline integrates source-period controls, historical features, six-scenario model stability, observed immediate trade-partner networks, static no-substitution removal tests, decision-support case generation, and a fail-closed publication gate.

The analysis identified 143 stable elevated country-food candidates and 283 stable elevated supplier-food candidates. These are developmental analytical signals, not official rankings, forecasts, causal claims, agricultural-origin determinations, or implementation recommendations. The included review registry records 8 cases approved for internal presentation and 418 held cases. Internal approval is not external publication approval.

## Key governed results

- 12,144 annual country-food-year rows
- 4,048 period country-food records
- 661 primary country-food records
- 816 limited-evidence country-food records
- 51,312 developmental scenario rows
- 73,277 annual supplier edges and static removal tests
- 5,631 observed annual importer-food networks
- 1,358 primary supplier-food nodes
- 143 stable elevated country-food candidates
- 283 stable elevated supplier-food candidates
- 14,433 supporting primary importer-supplier-food relationships
- 143 intervention hypotheses: 135 supplier-diversification reviews and 8 alternative-import-channel reviews
- 354 importer-food-year removal tests with no other observed supplier remaining
- 426 candidate cases: 8 approved for internal presentation and 418 held in the included review registry

## Repository architecture

```text
Build 1  Source-period governance and temporal controls
Build 2  Historical country-food features
Build 3  Six-scenario vulnerability specification and stability
Build 4  Supplier-food systemic reach and static removal tests
Build 5  Governed decision support and analyst review queues
Build 6  Fail-closed presentation evidence package
```

## Main code files

- `scripts/build_core_food_source_period_inventory.py`
- `scripts/build_core_food_historical_features.py`
- `scripts/build_core_food_model_specification.py`
- `scripts/build_core_food_supplier_chokepoints.py`
- `scripts/build_core_food_decision_support.py`
- `scripts/build_core_food_evidence_package.py`

## Governance policies

- `config/model_governance/core_food_period_policy.json`
- `config/model_governance/core_food_feature_policy.json`
- `config/model_governance/core_food_model_specification.json`
- `config/model_governance/core_food_chokepoint_policy.json`
- `config/model_governance/core_food_decision_support_policy.json`
- `config/model_governance/core_food_evidence_package_policy.json`

## Review controls

- `config/review_decisions/core_food_case_publication_decisions.csv`
- `docs/governance/core_food_publication_review_guide.md`

The included registry contains 8 `APPROVED_FOR_INTERNAL_PRESENTATION` decisions and 418 `HOLD` decisions. A case enters presentation outputs only after complete reviewer metadata, evidence verification, prohibited-claims verification, and an approved internal or external publication decision.

## Core interpretation rules

- Exporters are interpreted as observed immediate trade partners, not agricultural origin.
- Static removal tests are diagnostics and do not model substitution, inventories, prices, logistics, policy responses, production responses, consumer behavior, or rerouting.
- Percentiles are relative developmental measures, not probabilities.
- Intervention categories are hypotheses for review, not proven recommendations.
- No official country or supplier ranking is generated.

## Documentation

Start with `docs/governance/README_BUILD_DOCUMENTATION.md`, then review the build history, architecture, methodology, controls, reproducibility runbook, onboarding guide, and publication review guide.

## Raw data sources

The raw datasets are public FAOSTAT downloads; large source files are intentionally kept outside this repository.

| Dataset | Official source | Bulk archive used by the download helper |
| --- | --- | --- |
| Food Balance Sheets | [FAOSTAT Food Balances](https://www.fao.org/faostat/en/#data/FBS) | [English normalized ZIP](https://bulks-faostat.fao.org/production/FoodBalanceSheets_E_All_Data_(Normalized).zip) |
| Detailed Trade Matrix | [FAOSTAT Detailed Trade Matrix](https://www.fao.org/faostat/en/#data/TM) | [English normalized ZIP](https://bulks-faostat.fao.org/production/Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip) |

After installing dependencies, run from the repository root:

```bash
python scripts/download_food_balances.py
python scripts/download_trade_matrix.py
```

These helpers save ZIP archives and download manifests under `data/raw/faostat/`. They validate the archive format and record SHA-256 hashes. They do not extract the Food Balance Sheets CSV. See [Data setup](docs/DATA_SETUP.md) for extraction and missing upstream requirements.

The governed analysis covers **2021–2023**. FAOSTAT bulk downloads can be revised; a fresh download is not guaranteed to match the original source snapshot or historical results. If an endpoint changes, use the official dataset page to obtain the current English normalized bulk archive. Attribute the source as FAO / FAOSTAT and consult its applicable data-use terms.

## Local setup

Run from the repository root with Python 3.12 (the version used in the uploaded development cache):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The uploaded dependency list is unpinned; exact original package versions were not supplied.

## Reproducibility

First follow [Data setup](docs/DATA_SETUP.md). The six builds below require upstream foundation outputs; they cannot run on this code-only snapshot by themselves. Once those prerequisites are available, run the builds in sequence after activating the project environment. Each build verifies its input contract and writes a provenance summary under `outputs/model_results/`.

```bash
python -u scripts/build_core_food_source_period_inventory.py
python -u scripts/build_core_food_historical_features.py
python -u scripts/build_core_food_model_specification.py
python -u scripts/build_core_food_supplier_chokepoints.py
python -u scripts/build_core_food_decision_support.py
python -u scripts/build_core_food_evidence_package.py
```

## Included snapshot and validation

This repository preserves the uploaded analytical code and governance configuration. It does not include the original Git history, build tags, raw datasets, intermediate tables, or generated evidence packages. Reported analytical counts above describe the original project; they have not been independently reproduced from this code-only snapshot.

All 27 Python scripts passed syntax validation, all included JSON files parsed successfully, and the publication-decision CSV was checked for the 8 approved / 418 held split. A full analytical run requires the missing inputs described in [Data setup](docs/DATA_SETUP.md).

Earlier governance documents describe the initial all-held state and the original development history. The included review registry is the authoritative decision snapshot for this upload.

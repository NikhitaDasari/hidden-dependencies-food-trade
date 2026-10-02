# Data setup and snapshot limitations

## Source data

Use FAOSTAT Food Balance Sheets and the Detailed Trade Matrix. Download helpers are included:

```bash
python scripts/download_food_balances.py
python scripts/download_trade_matrix.py
```

Run from the repository root. These scripts download large archives and save manifests under `data/raw/faostat/`; they do not extract the source CSVs. Check the original source manifests and actual downloaded coverage before rerunning analysis: current downloads may differ from the original project snapshot.

## Official download links

- Food Balance Sheets: https://www.fao.org/faostat/en/#data/FBS
- Detailed Trade Matrix: https://www.fao.org/faostat/en/#data/TM

Direct bulk ZIP links are listed in the root README and embedded in the download helpers. The archive URLs were taken from the supplied project code; archive downloads were not executed during repository preparation.

## Food Balance Sheets extraction

After downloading `data/raw/faostat/food_balances.zip`, extract its normalized CSV into `data/raw/faostat/food_balances/`. `scripts/profile_complete_food_balances.py` expects:

```text
data/raw/faostat/food_balances/FoodBalanceSheets_E_All_Data_(Normalized).csv
```

For example, from the repository root:

```bash
mkdir -p data/raw/faostat/food_balances
unzip data/raw/faostat/food_balances.zip -d data/raw/faostat/food_balances
```

Confirm the extracted filename matches the expected path. The trade silver builder reads its ZIP directly. Downloading both archives alone does not satisfy all foundation and reviewed-mapping requirements below.

## Upstream requirements

The six governed builds in the README begin after foundation processing. They need the Food Balance Sheets database, trade parquet partitions, reviewed mapping tables, country eligibility outputs, the core-food registry, FBS annual foundation, supplier network, and model readiness outputs.

The upload contains helper scripts for many of these stages, but does not include all required source/reference inputs. Examples:

- `scripts/build_tier1_reconciliation.py` requires `outputs/tables/crosswalk/food_crosswalk_tier1_reconciliation_seed.csv`.
- `scripts/build_core_food_fbs_foundation.py` requires the generated core-food registry and product-channel tables.
- `scripts/build_unified_geography_capability.py` expects reviewed country eligibility data under `outputs/tables/core_food_country_foundation/`.
- The period policy refers to `config/data_sources/core_food_external_source_manifest.csv`, which is absent from this snapshot. Check the builder's admission behavior before adding an external source manifest.

Recover reviewed inputs from the original laptop project before attempting full reproduction. Do not substitute invented mappings or decisions. Follow the existing governance runbook for the stage contracts and provenance checks.

## What is verified

Python syntax, JSON parsing, and the included publication decision counts were checked. Source downloads and a full pipeline run were not performed for this upload. Generated output counts are reported historical project results, not a fresh execution of this snapshot.

## Keeping the repository small

Raw archives, extracted data, databases, parquet partitions, analytical outputs, logs, environments, and caches are excluded by `.gitignore`. Share large inputs separately with appropriate attribution. The source manifest documents FAOSTAT licensing; no new code license is assigned by this packaging step.

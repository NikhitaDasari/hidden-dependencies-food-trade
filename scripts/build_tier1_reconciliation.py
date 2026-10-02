from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/processed/food_balances.duckdb"
SEED_PATH = (
    ROOT / "outputs/tables/crosswalk_discovery/"
    "food_crosswalk_tier1_reconciliation_seed.csv"
)
TRADE_GLOB = str(
    ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported/**/*.parquet"
)
OUTPUT_DIR = ROOT / "outputs/tables/reconciliation"
PANEL_PATH = OUTPUT_DIR / "tier1_country_year_reconciliation.csv"
SUMMARY_PATH = OUTPUT_DIR / "tier1_commodity_reconciliation_summary.csv"
UNMATCHED_PATH = OUTPUT_DIR / "tier1_unmatched_country_years.csv"
REPORT_PATH = ROOT / "outputs/model_results/tier1_reconciliation_report.json"

START_YEAR = 2010
END_YEAR = 2023
FBS_IMPORT_ELEMENT_CODE = 5611
FBS_UNIT = "1000 t"


def scalar(value):
    return value.item() if hasattr(value, "item") else value


def records(frame: pd.DataFrame) -> list[dict]:
    return [
        {key: scalar(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    if not SEED_PATH.exists():
        raise FileNotFoundError(SEED_PATH)
    if not list(
        (ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported").rglob(
            "*.parquet"
        )
    ):
        raise FileNotFoundError("Importer-reported Parquet files were not found")

    seed = pd.read_csv(SEED_PATH)
    if len(seed) != 27:
        raise ValueError(f"Expected 27 seed rows, found {len(seed)}")
    if seed["trade_item_code"].duplicated().any():
        raise ValueError("Duplicate trade_item_code values found in seed")
    if seed["proposed_fbs_item_code"].isna().any():
        raise ValueError("Missing proposed FBS item codes in seed")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.execute(f"ATTACH '{DB_PATH}' AS fbs_db (READ_ONLY)")
    connection.register("seed_input", seed)

    connection.execute(
        """
        CREATE OR REPLACE TEMP VIEW seed AS
        SELECT
            CAST(trade_item_code AS BIGINT) AS trade_item_code,
            trade_item,
            CAST(proposed_fbs_item_code AS BIGINT) AS fbs_item_code,
            proposed_fbs_item AS fbs_item,
            decision,
            processing_status,
            overlap_group,
            review_notes,
            reconciliation_variant
        FROM seed_input
        """
    )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trade_totals AS
        SELECT
            s.trade_item_code,
            s.trade_item,
            s.fbs_item_code,
            s.fbs_item,
            s.decision,
            s.processing_status,
            s.overlap_group,
            s.reconciliation_variant,
            t.importer_code,
            t.importer_m49,
            t.importer,
            t.year,
            SUM(t.value) AS bilateral_import_tonnes,
            COUNT(DISTINCT t.exporter_code) AS positive_suppliers,
            STRING_AGG(DISTINCT COALESCE(t.flag, '[Missing]'), ', ')
                AS trade_flags
        FROM read_parquet(
            '{TRADE_GLOB}',
            union_by_name = true
        ) t
        INNER JOIN seed s
            ON t.item_code = s.trade_item_code
        WHERE t.value_type = 'quantity'
          AND t.unit = 't'
          AND t.value > 0
          AND t.year BETWEEN {START_YEAR} AND {END_YEAR}
        GROUP BY ALL
        """
    )

    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW fbs_imports AS
        SELECT
            CAST("Item Code" AS BIGINT) AS fbs_item_code,
            REPLACE(CAST("Area Code (M49)" AS VARCHAR), '''', '')
                AS area_m49,
            "Area Code" AS area_code,
            "Area" AS area,
            "Year" AS year,
            "Value" * 1000.0 AS fbs_import_tonnes,
            "Flag" AS fbs_flag
        FROM fbs_db.main.food_balances
        WHERE "Element Code" = {FBS_IMPORT_ELEMENT_CODE}
          AND "Unit" = '{FBS_UNIT}'
          AND "Year" BETWEEN {START_YEAR} AND {END_YEAR}
          AND "Item Code" IN (
              SELECT DISTINCT fbs_item_code FROM seed
          )
        """
    )

    panel = connection.execute(
        """
        SELECT
            t.trade_item_code,
            t.trade_item,
            t.fbs_item_code,
            t.fbs_item,
            t.decision,
            t.processing_status,
            t.overlap_group,
            t.reconciliation_variant,
            t.importer_code,
            t.importer_m49,
            t.importer,
            t.year,
            t.bilateral_import_tonnes,
            t.positive_suppliers,
            t.trade_flags,
            f.area_code AS fbs_area_code,
            f.area AS fbs_area,
            f.fbs_import_tonnes,
            f.fbs_flag,
            CASE
                WHEN f.fbs_import_tonnes > 0
                THEN t.bilateral_import_tonnes / f.fbs_import_tonnes
            END AS reconciliation_ratio,
            CASE
                WHEN f.fbs_import_tonnes > 0
                THEN ABS(t.bilateral_import_tonnes - f.fbs_import_tonnes)
                     / f.fbs_import_tonnes
            END AS absolute_percentage_difference,
            CASE
                WHEN f.fbs_import_tonnes IS NULL THEN 'missing_fbs'
                WHEN f.fbs_import_tonnes = 0 THEN 'fbs_zero'
                WHEN t.bilateral_import_tonnes / f.fbs_import_tonnes
                     BETWEEN 0.90 AND 1.10 THEN 'strong_0.90_1.10'
                WHEN t.bilateral_import_tonnes / f.fbs_import_tonnes
                     BETWEEN 0.75 AND 1.25 THEN 'review_0.75_1.25'
                WHEN t.bilateral_import_tonnes / f.fbs_import_tonnes
                     BETWEEN 0.50 AND 1.50 THEN 'weak_0.50_1.50'
                WHEN t.bilateral_import_tonnes / f.fbs_import_tonnes < 0.50
                    THEN 'below_0.50'
                ELSE 'above_1.50'
            END AS reconciliation_band
        FROM trade_totals t
        LEFT JOIN fbs_imports f
          ON t.fbs_item_code = f.fbs_item_code
         AND t.importer_m49 = LPAD(f.area_m49, 3, '0')
         AND t.year = f.year
        ORDER BY t.trade_item_code, t.importer, t.year
        """
    ).fetchdf()

    summary = connection.execute(
        """
        WITH panel AS (
            SELECT
                t.*,
                f.fbs_import_tonnes,
                CASE
                    WHEN f.fbs_import_tonnes > 0
                    THEN t.bilateral_import_tonnes / f.fbs_import_tonnes
                END AS ratio,
                CASE
                    WHEN f.fbs_import_tonnes > 0
                    THEN ABS(t.bilateral_import_tonnes - f.fbs_import_tonnes)
                         / f.fbs_import_tonnes
                END AS ape
            FROM trade_totals t
            LEFT JOIN fbs_imports f
              ON t.fbs_item_code = f.fbs_item_code
             AND t.importer_m49 = LPAD(f.area_m49, 3, '0')
             AND t.year = f.year
        )
        SELECT
            trade_item_code,
            ANY_VALUE(trade_item) AS trade_item,
            fbs_item_code,
            ANY_VALUE(fbs_item) AS fbs_item,
            ANY_VALUE(decision) AS decision,
            ANY_VALUE(processing_status) AS processing_status,
            ANY_VALUE(overlap_group) AS overlap_group,
            ANY_VALUE(reconciliation_variant) AS reconciliation_variant,
            COUNT(*) AS trade_country_years,
            COUNT(*) FILTER (WHERE fbs_import_tonnes IS NOT NULL)
                AS matched_fbs_country_years,
            COUNT(*) FILTER (WHERE fbs_import_tonnes > 0)
                AS comparable_positive_country_years,
            COUNT(DISTINCT importer_code) AS trade_importers,
            COUNT(DISTINCT importer_code) FILTER (
                WHERE fbs_import_tonnes > 0
            ) AS comparable_importers,
            ROUND(
                COUNT(*) FILTER (WHERE fbs_import_tonnes IS NOT NULL)
                * 1.0 / COUNT(*),
                6
            ) AS fbs_match_coverage,
            MEDIAN(ratio) FILTER (WHERE ratio IS NOT NULL)
                AS median_reconciliation_ratio,
            AVG(ratio) FILTER (WHERE ratio IS NOT NULL)
                AS mean_reconciliation_ratio,
            MEDIAN(ape) FILTER (WHERE ape IS NOT NULL)
                AS median_absolute_percentage_difference,
            AVG(ape) FILTER (WHERE ape IS NOT NULL)
                AS mean_absolute_percentage_difference,
            QUANTILE_CONT(ratio, 0.10) FILTER (WHERE ratio IS NOT NULL)
                AS reconciliation_ratio_p10,
            QUANTILE_CONT(ratio, 0.90) FILTER (WHERE ratio IS NOT NULL)
                AS reconciliation_ratio_p90,
            COUNT(*) FILTER (WHERE ratio BETWEEN 0.90 AND 1.10)
                AS strong_band_rows,
            COUNT(*) FILTER (WHERE ratio BETWEEN 0.75 AND 1.25)
                AS acceptable_band_rows,
            COUNT(*) FILTER (WHERE ratio < 0.50)
                AS below_half_rows,
            COUNT(*) FILTER (WHERE ratio > 1.50)
                AS above_one_point_five_rows,
            SUM(bilateral_import_tonnes) AS summed_bilateral_import_tonnes,
            SUM(fbs_import_tonnes) FILTER (WHERE fbs_import_tonnes IS NOT NULL)
                AS summed_fbs_import_tonnes
        FROM panel
        GROUP BY trade_item_code, fbs_item_code
        ORDER BY trade_item_code
        """
    ).fetchdf()

    summary["diagnostic_recommendation"] = "REVIEW"
    strong = (
        summary["fbs_match_coverage"].ge(0.80)
        & summary["comparable_positive_country_years"].ge(100)
        & summary["median_reconciliation_ratio"].between(0.90, 1.10)
        & summary["median_absolute_percentage_difference"].le(0.25)
    )
    acceptable = (
        summary["fbs_match_coverage"].ge(0.70)
        & summary["comparable_positive_country_years"].ge(75)
        & summary["median_reconciliation_ratio"].between(0.75, 1.25)
        & summary["median_absolute_percentage_difference"].le(0.50)
    )
    summary.loc[acceptable, "diagnostic_recommendation"] = "ACCEPTABLE_REVIEW"
    summary.loc[strong, "diagnostic_recommendation"] = "STRONG_CANDIDATE"

    unmatched = panel.loc[
        panel["fbs_import_tonnes"].isna() | panel["fbs_import_tonnes"].eq(0)
    ].copy()

    panel.to_csv(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    unmatched.to_csv(UNMATCHED_PATH, index=False)

    rice = summary.loc[summary["overlap_group"].eq("rice")].copy()
    report = {
        "dataset": "Tier 1 bilateral-to-national import reconciliation",
        "analysis_period": {"start_year": START_YEAR, "end_year": END_YEAR},
        "trade_filters": {
            "reporting_perspective": "importer_reported",
            "value_type": "quantity",
            "unit": "t",
            "value_rule": "value > 0",
        },
        "food_balance_filters": {
            "element_code": FBS_IMPORT_ELEMENT_CODE,
            "element": "Import quantity",
            "unit": FBS_UNIT,
            "conversion_to_tonnes": "Value * 1000",
            "canonical_alias_policy": {
                "Eggs": {"canonical": 2744, "excluded_alias": 2949},
                "Milk - Excluding Butter": {
                    "canonical": 2848,
                    "excluded_alias": 2948,
                },
            },
        },
        "seed_rows": len(seed),
        "panel_rows": len(panel),
        "summary_rows": len(summary),
        "unmatched_or_zero_fbs_rows": len(unmatched),
        "recommendation_counts": {
            str(key): int(value)
            for key, value in summary["diagnostic_recommendation"]
            .value_counts()
            .items()
        },
        "rice_variant_summary": records(rice),
        "important_method_note": (
            "Recommendations are diagnostic only. Gold approval still requires "
            "manual overlap review, country-crosswalk validation, and stability review."
        ),
        "outputs": {
            "country_year_panel": str(PANEL_PATH.relative_to(ROOT)),
            "commodity_summary": str(SUMMARY_PATH.relative_to(ROOT)),
            "unmatched_country_years": str(UNMATCHED_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print("=" * 72)
    print("TIER 1 RECONCILIATION COMPLETE")
    print("=" * 72)
    print(f"Seed rows: {len(seed):,}")
    print(f"Country-year panel rows: {len(panel):,}")
    print(f"Commodity summaries: {len(summary):,}")
    print(f"Unmatched or zero-FBS rows: {len(unmatched):,}")
    print()
    print("Diagnostic recommendations:")
    print(summary["diagnostic_recommendation"].value_counts().to_string())
    print()
    print("Rice variants:")
    print(
        rice[
            [
                "trade_item_code",
                "trade_item",
                "reconciliation_variant",
                "fbs_match_coverage",
                "median_reconciliation_ratio",
                "median_absolute_percentage_difference",
                "diagnostic_recommendation",
            ]
        ].to_string(index=False)
    )
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")

    connection.close()


if __name__ == "__main__":
    main()

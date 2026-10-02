from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
IMPORT_GLOB = str(
    ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported/**/*.parquet"
)
EXPORT_GLOB = str(
    ROOT / "data/interim/faostat/detailed_trade_matrix/exporter_reported/**/*.parquet"
)
OUTPUT_DIR = ROOT / "outputs/tables/trade_matrix_overview"
REPORT_PATH = ROOT / "outputs/model_results/trade_matrix_silver_validation.json"


def one_row(df):
    return {
        key: (value.item() if hasattr(value, "item") else value)
        for key, value in df.iloc[0].to_dict().items()
    }


def main() -> None:
    if not list(
        (ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported").rglob(
            "*.parquet"
        )
    ):
        raise FileNotFoundError("Importer-reported Silver Parquet files were not found")
    if not list(
        (ROOT / "data/interim/faostat/detailed_trade_matrix/exporter_reported").rglob(
            "*.parquet"
        )
    ):
        raise FileNotFoundError("Exporter-reported Silver Parquet files were not found")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute(
        f"CREATE TEMP VIEW imports AS SELECT * FROM read_parquet('{IMPORT_GLOB}', union_by_name=true)"
    )
    con.execute(
        f"CREATE TEMP VIEW exports AS SELECT * FROM read_parquet('{EXPORT_GLOB}', union_by_name=true)"
    )

    summary_sql = """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT importer_code) AS importers,
            COUNT(DISTINCT exporter_code) AS exporters,
            COUNT(DISTINCT item_code) AS items,
            MIN(year) AS first_year,
            MAX(year) AS latest_year,
            COUNT(DISTINCT year) AS years,
            COUNT(DISTINCT flag) AS flags,
            COUNT(*) FILTER (WHERE value_type='quantity') AS quantity_rows,
            COUNT(*) FILTER (WHERE value_type='value') AS value_rows,
            COUNT(*) FILTER (WHERE value=0) AS zero_value_rows,
            COUNT(*) FILTER (WHERE value IS NULL) AS missing_value_rows,
            COUNT(*) FILTER (WHERE value<0) AS negative_value_rows,
            COUNT(*) FILTER (WHERE importer_code=exporter_code) AS self_trade_rows,
            COUNT(*) FILTER (WHERE importer_m49 IS NULL OR importer_m49='') AS missing_importer_m49,
            COUNT(*) FILTER (WHERE exporter_m49 IS NULL OR exporter_m49='') AS missing_exporter_m49
        FROM {view}
    """
    import_summary = con.execute(summary_sql.format(view="imports")).fetchdf()
    export_summary = con.execute(summary_sql.format(view="exports")).fetchdf()

    duplicate_summary = con.execute("""
        WITH d AS (
            SELECT importer_code, exporter_code, item_code, year, measure, unit, COUNT(*) AS rows
            FROM imports
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        SELECT COUNT(*) AS duplicate_key_groups,
               COALESCE(SUM(rows-1),0) AS duplicate_excess_rows,
               COALESCE(MAX(rows),0) AS maximum_rows_per_key
        FROM d
    """).fetchdf()

    year_profile = con.execute("""
        SELECT year, value_type, COUNT(*) AS rows,
               COUNT(DISTINCT importer_code) AS importers,
               COUNT(DISTINCT exporter_code) AS exporters,
               COUNT(DISTINCT item_code) AS items,
               SUM(value) AS total_value
        FROM imports GROUP BY ALL ORDER BY year, value_type
    """).fetchdf()

    measure_profile = con.execute("""
        SELECT measure, unit, COUNT(*) AS rows,
               COUNT(DISTINCT importer_code) AS importers,
               COUNT(DISTINCT exporter_code) AS exporters,
               COUNT(DISTINCT item_code) AS items,
               MIN(year) AS first_year, MAX(year) AS latest_year,
               SUM(value) AS total_value
        FROM imports GROUP BY ALL ORDER BY rows DESC
    """).fetchdf()

    flag_profile = con.execute("""
        SELECT COALESCE(flag,'[Missing]') AS flag, COUNT(*) AS rows,
               ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),4) AS percentage,
               COUNT(DISTINCT importer_code) AS importers,
               COUNT(DISTINCT exporter_code) AS exporters,
               COUNT(DISTINCT item_code) AS items
        FROM imports GROUP BY flag ORDER BY rows DESC
    """).fetchdf()

    country_inventory = con.execute("""
        WITH c AS (
            SELECT DISTINCT importer_code AS country_code, importer_m49 AS m49_code, importer AS country FROM imports
            UNION
            SELECT DISTINCT exporter_code, exporter_m49, exporter FROM imports
        )
        SELECT * FROM c ORDER BY country
    """).fetchdf()

    suspicious = con.execute("""
        WITH c AS (
            SELECT DISTINCT importer_code AS country_code, importer_m49 AS m49_code, importer AS country FROM imports
            UNION
            SELECT DISTINCT exporter_code, exporter_m49, exporter FROM imports
        )
        SELECT * FROM c
        WHERE country_code>=5000 OR m49_code IS NULL OR m49_code=''
           OR lower(country) LIKE '%world%' OR lower(country) LIKE '%unspecified%'
           OR lower(country) LIKE '%not elsewhere%' OR lower(country) LIKE '%areas nes%'
           OR lower(country) LIKE '%free zone%'
        ORDER BY country
    """).fetchdf()

    items = con.execute("""
        SELECT item_code, cpc_code, item, COUNT(*) AS rows,
               COUNT(DISTINCT importer_code) AS importers,
               COUNT(DISTINCT exporter_code) AS exporters,
               MIN(year) AS first_year, MAX(year) AS latest_year,
               SUM(value) FILTER (WHERE value_type='quantity') AS total_quantity_tonnes,
               SUM(value) FILTER (WHERE value_type='value') AS total_value_1000_usd
        FROM imports GROUP BY ALL ORDER BY rows DESC
    """).fetchdf()

    duplicate_examples = con.execute("""
        SELECT importer_code, importer, exporter_code, exporter, item_code, item,
               year, measure, unit, COUNT(*) AS rows, SUM(value) AS summed_value,
               STRING_AGG(DISTINCT COALESCE(flag,'[Missing]'), ', ') AS flags
        FROM imports GROUP BY importer_code, importer, exporter_code, exporter,
             item_code, item, year, measure, unit
        HAVING COUNT(*)>1 ORDER BY rows DESC LIMIT 100
    """).fetchdf()

    outputs = {
        "validation_year_profile.csv": year_profile,
        "validation_measure_profile.csv": measure_profile,
        "validation_flag_profile.csv": flag_profile,
        "validation_country_inventory.csv": country_inventory,
        "validation_suspicious_countries.csv": suspicious,
        "validation_item_inventory.csv": items,
        "validation_duplicate_examples.csv": duplicate_examples,
    }
    for filename, frame in outputs.items():
        frame.to_csv(OUTPUT_DIR / filename, index=False)

    report = {
        "dataset": "FAOSTAT Detailed Trade Matrix Silver",
        "importer_reported_summary": one_row(import_summary),
        "exporter_reported_summary": one_row(export_summary),
        "duplicate_summary": one_row(duplicate_summary),
        "country_inventory_rows": len(country_inventory),
        "suspicious_country_rows": len(suspicious),
        "item_inventory_rows": len(items),
        "important_limitation": "The current Silver schema does not retain source Element Code. Duplicate results determine whether Silver must be rebuilt with element_code before aggregation.",
        "validation_outputs": {
            name: str((OUTPUT_DIR / name).relative_to(ROOT)) for name in outputs
        },
    }
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print("=" * 72)
    print("IMPORTER-REPORTED SUMMARY")
    print("=" * 72)
    print(import_summary.to_string(index=False))
    print("\n" + "=" * 72)
    print("EXPORTER-REPORTED SUMMARY")
    print("=" * 72)
    print(export_summary.to_string(index=False))
    print("\n" + "=" * 72)
    print("DUPLICATE SUMMARY")
    print("=" * 72)
    print(duplicate_summary.to_string(index=False))
    print("\n" + "=" * 72)
    print("SUSPICIOUS COUNTRIES OR ENTITIES")
    print("=" * 72)
    print(
        "None detected by preliminary rules."
        if suspicious.empty
        else suspicious.to_string(index=False)
    )
    print(f"\nValidation report: {REPORT_PATH.relative_to(ROOT)}")
    con.close()


if __name__ == "__main__":
    main()

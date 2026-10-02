from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DATA_FILE = (
    ROOT
    / "data"
    / "raw"
    / "faostat"
    / "food_balances"
    / "FoodBalanceSheets_E_All_Data_(Normalized).csv"
)

DATABASE_FILE = ROOT / "data" / "processed" / "food_balances.duckdb"

OUTPUT_DIR = ROOT / "outputs" / "tables" / "dataset_overview"

JSON_OUTPUT = ROOT / "outputs" / "model_results" / "food_balances_complete_profile.json"

MARKDOWN_OUTPUT = ROOT / "docs" / "food_balances_dataset_overview.md"


def save_csv(
    dataframe: pd.DataFrame,
    filename: str,
) -> Path:
    output_path = OUTPUT_DIR / filename
    dataframe.to_csv(output_path, index=False)
    print(f"Saved: {output_path}")
    return output_path


def scalar_value(
    dataframe: pd.DataFrame,
    column: str,
):
    value = dataframe.loc[0, column]

    if hasattr(value, "item"):
        return value.item()

    return value


def main() -> None:
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            "The normalized FAOSTAT Food Balances CSV was not found:\n" f"{DATA_FILE}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(DATABASE_FILE))

    connection.execute("PRAGMA threads=4")
    connection.execute("PRAGMA enable_progress_bar=true")

    csv_path = str(DATA_FILE).replace("'", "''")

    connection.execute(f"""
        CREATE OR REPLACE VIEW food_balances AS
        SELECT *
        FROM read_csv_auto(
            '{csv_path}',
            header = true,
            sample_size = 200000,
            all_varchar = false,
            ignore_errors = false
        )
        """)

    print("\nConnected to FAOSTAT Food Balances.")

    schema = connection.execute("""
        DESCRIBE food_balances
        """).fetchdf()

    save_csv(schema, "01_schema.csv")

    overall_profile = connection.execute("""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(*) FILTER (
                WHERE "Value" IS NOT NULL
            ) AS rows_with_values,
            COUNT(*) FILTER (
                WHERE "Value" IS NULL
            ) AS rows_missing_values,
            COUNT(DISTINCT "Area Code") AS area_codes,
            COUNT(DISTINCT "Area") AS area_names,
            COUNT(DISTINCT "Item Code") AS item_codes,
            COUNT(DISTINCT "Item") AS item_names,
            COUNT(DISTINCT "Element Code") AS element_codes,
            COUNT(DISTINCT "Element") AS element_names,
            COUNT(DISTINCT "Unit") AS units,
            COUNT(DISTINCT "Flag") AS flags,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year,
            COUNT(DISTINCT "Year") AS years_available
        FROM food_balances
        """).fetchdf()

    save_csv(overall_profile, "02_overall_profile.csv")

    year_coverage = connection.execute("""
        SELECT
            "Year" AS year,
            COUNT(*) AS total_rows,
            COUNT("Value") AS rows_with_values,
            COUNT(*) - COUNT("Value") AS missing_values,
            COUNT(DISTINCT "Area Code") AS areas,
            COUNT(DISTINCT "Item Code") AS items,
            COUNT(DISTINCT "Element Code") AS elements,
            ROUND(SUM("Value"), 2) AS sum_of_all_values
        FROM food_balances
        GROUP BY "Year"
        ORDER BY "Year"
        """).fetchdf()

    save_csv(year_coverage, "03_year_coverage.csv")

    areas = connection.execute("""
        SELECT
            "Area Code" AS area_code,
            "Area Code (M49)" AS m49_code,
            "Area" AS area,
            CASE
                WHEN "Area Code" >= 5000
                    THEN 'Aggregate'
                ELSE 'Country or territory'
            END AS area_type,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Item Code") AS items,
            COUNT(DISTINCT "Element Code") AS elements,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year
        FROM food_balances
        GROUP BY
            "Area Code",
            "Area Code (M49)",
            "Area"
        ORDER BY
            area_type,
            area
        """).fetchdf()

    save_csv(areas, "04_areas.csv")

    area_type_summary = areas.groupby("area_type", as_index=False).agg(
        area_count=("area", "nunique"),
        total_rows=("rows", "sum"),
        first_year=("first_year", "min"),
        latest_year=("latest_year", "max"),
    )

    save_csv(
        area_type_summary,
        "05_area_type_summary.csv",
    )

    aggregates = areas.loc[areas["area_type"].eq("Aggregate")].copy()

    save_csv(
        aggregates,
        "06_geographic_aggregates.csv",
    )

    countries = areas.loc[areas["area_type"].eq("Country or territory")].copy()

    save_csv(
        countries,
        "07_countries_and_territories.csv",
    )

    items = connection.execute("""
        SELECT
            "Item Code" AS item_code,
            "Item Code (FBS)" AS fbs_item_code,
            "Item" AS item,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Area Code") AS areas,
            COUNT(DISTINCT "Element Code") AS elements,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year,
            COUNT("Value") AS rows_with_values,
            COUNT(*) - COUNT("Value") AS missing_values
        FROM food_balances
        GROUP BY
            "Item Code",
            "Item Code (FBS)",
            "Item"
        ORDER BY item
        """).fetchdf()

    save_csv(items, "08_food_items.csv")

    elements = connection.execute("""
        SELECT
            "Element Code" AS element_code,
            "Element" AS element,
            "Unit" AS unit,
            COUNT(*) AS rows,
            COUNT("Value") AS rows_with_values,
            COUNT(*) - COUNT("Value") AS missing_values,
            COUNT(DISTINCT "Area Code") AS areas,
            COUNT(DISTINCT "Item Code") AS items,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year,
            MIN("Value") AS minimum_value,
            MAX("Value") AS maximum_value,
            ROUND(AVG("Value"), 4) AS average_value,
            ROUND(MEDIAN("Value"), 4) AS median_value
        FROM food_balances
        GROUP BY
            "Element Code",
            "Element",
            "Unit"
        ORDER BY rows DESC
        """).fetchdf()

    save_csv(elements, "09_elements_and_units.csv")

    units = connection.execute("""
        SELECT
            "Unit" AS unit,
            COUNT(*) AS rows,
            COUNT("Value") AS rows_with_values,
            COUNT(DISTINCT "Element") AS elements,
            COUNT(DISTINCT "Item") AS items,
            COUNT(DISTINCT "Area") AS areas
        FROM food_balances
        GROUP BY "Unit"
        ORDER BY rows DESC
        """).fetchdf()

    save_csv(units, "10_units.csv")

    flags = connection.execute("""
        SELECT
            COALESCE("Flag", '[Missing]') AS flag,
            COUNT(*) AS rows,
            ROUND(
                100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
                4
            ) AS percentage,
            COUNT(DISTINCT "Area") AS areas,
            COUNT(DISTINCT "Item") AS items,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year
        FROM food_balances
        GROUP BY "Flag"
        ORDER BY rows DESC
        """).fetchdf()

    save_csv(flags, "11_flags.csv")

    column_missingness = connection.execute("""
        SELECT
            column_name,
            column_type,
            null_count,
            total_rows,
            ROUND(
                100.0 * null_count / total_rows,
                4
            ) AS missing_percentage
        FROM (
            SELECT
                UNNEST([
                    'Area Code',
                    'Area Code (M49)',
                    'Area',
                    'Item Code',
                    'Item Code (FBS)',
                    'Item',
                    'Element Code',
                    'Element',
                    'Year Code',
                    'Year',
                    'Unit',
                    'Value',
                    'Flag',
                    'Note'
                ]) AS column_name,
                UNNEST([
                    'Identifier',
                    'Identifier',
                    'Text',
                    'Identifier',
                    'Identifier',
                    'Text',
                    'Identifier',
                    'Text',
                    'Identifier',
                    'Year',
                    'Text',
                    'Numeric',
                    'Text',
                    'Text'
                ]) AS column_type,
                UNNEST([
                    COUNT(*) FILTER (WHERE "Area Code" IS NULL),
                    COUNT(*) FILTER (
                        WHERE "Area Code (M49)" IS NULL
                    ),
                    COUNT(*) FILTER (WHERE "Area" IS NULL),
                    COUNT(*) FILTER (WHERE "Item Code" IS NULL),
                    COUNT(*) FILTER (
                        WHERE "Item Code (FBS)" IS NULL
                    ),
                    COUNT(*) FILTER (WHERE "Item" IS NULL),
                    COUNT(*) FILTER (
                        WHERE "Element Code" IS NULL
                    ),
                    COUNT(*) FILTER (WHERE "Element" IS NULL),
                    COUNT(*) FILTER (WHERE "Year Code" IS NULL),
                    COUNT(*) FILTER (WHERE "Year" IS NULL),
                    COUNT(*) FILTER (WHERE "Unit" IS NULL),
                    COUNT(*) FILTER (WHERE "Value" IS NULL),
                    COUNT(*) FILTER (WHERE "Flag" IS NULL),
                    COUNT(*) FILTER (WHERE "Note" IS NULL)
                ]) AS null_count,
                COUNT(*) AS total_rows
            FROM food_balances
        )
        ORDER BY missing_percentage DESC
        """).fetchdf()

    save_csv(
        column_missingness,
        "12_column_missingness.csv",
    )

    duplicate_summary = connection.execute("""
        SELECT
            COUNT(*) AS duplicate_key_groups,
            COALESCE(SUM(row_count - 1), 0) AS excess_rows
        FROM (
            SELECT
                "Area Code",
                "Item Code",
                "Element Code",
                "Year",
                "Unit",
                COUNT(*) AS row_count
            FROM food_balances
            GROUP BY
                "Area Code",
                "Item Code",
                "Element Code",
                "Year",
                "Unit"
            HAVING COUNT(*) > 1
        )
        """).fetchdf()

    save_csv(
        duplicate_summary,
        "13_duplicate_key_summary.csv",
    )

    duplicate_examples = connection.execute("""
        SELECT
            "Area Code" AS area_code,
            "Area" AS area,
            "Item Code" AS item_code,
            "Item" AS item,
            "Element Code" AS element_code,
            "Element" AS element,
            "Year" AS year,
            "Unit" AS unit,
            COUNT(*) AS row_count,
            MIN("Value") AS minimum_value,
            MAX("Value") AS maximum_value
        FROM food_balances
        GROUP BY
            "Area Code",
            "Area",
            "Item Code",
            "Item",
            "Element Code",
            "Element",
            "Year",
            "Unit"
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC
        LIMIT 100
        """).fetchdf()

    save_csv(
        duplicate_examples,
        "14_duplicate_key_examples.csv",
    )

    latest_year = int(scalar_value(overall_profile, "latest_year"))

    latest_year_summary = connection.execute(
        """
        SELECT
            "Element" AS element,
            "Unit" AS unit,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Area") AS areas,
            COUNT(DISTINCT "Item") AS items,
            COUNT("Value") AS rows_with_values
        FROM food_balances
        WHERE "Year" = ?
        GROUP BY "Element", "Unit"
        ORDER BY rows DESC
        """,
        [latest_year],
    ).fetchdf()

    save_csv(
        latest_year_summary,
        "15_latest_year_element_coverage.csv",
    )

    country_latest_year = connection.execute(
        """
        SELECT
            "Area Code" AS area_code,
            "Area Code (M49)" AS m49_code,
            "Area" AS area,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Item") AS items,
            COUNT(DISTINCT "Element") AS elements,
            COUNT("Value") AS rows_with_values
        FROM food_balances
        WHERE "Year" = ?
          AND "Area Code" < 5000
        GROUP BY
            "Area Code",
            "Area Code (M49)",
            "Area"
        ORDER BY rows DESC
        """,
        [latest_year],
    ).fetchdf()

    save_csv(
        country_latest_year,
        "16_latest_year_country_coverage.csv",
    )

    top_items_by_rows = items.sort_values(
        "rows",
        ascending=False,
    ).head(30)

    save_csv(
        top_items_by_rows,
        "17_top_items_by_record_count.csv",
    )

    loss_coverage = connection.execute("""
        SELECT
            "Item Code" AS item_code,
            "Item" AS item,
            COUNT(*) AS loss_rows,
            COUNT(DISTINCT "Area Code") AS areas,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year,
            ROUND(SUM("Value"), 2) AS total_reported_losses,
            ROUND(MEDIAN("Value"), 4) AS median_reported_loss,
            ROUND(AVG("Value"), 4) AS average_reported_loss
        FROM food_balances
        WHERE "Element" = 'Losses'
        GROUP BY
            "Item Code",
            "Item"
        ORDER BY areas DESC, loss_rows DESC
        """).fetchdf()

    save_csv(
        loss_coverage,
        "18_loss_data_coverage_by_item.csv",
    )

    sample_rows = connection.execute("""
        SELECT *
        FROM food_balances
        USING SAMPLE 25 ROWS
        """).fetchdf()

    save_csv(sample_rows, "19_random_sample_rows.csv")

    overall = overall_profile.iloc[0]

    profile_json = {
        "data_file": str(DATA_FILE.relative_to(ROOT)),
        "file_size_bytes": DATA_FILE.stat().st_size,
        "total_rows": int(overall["total_rows"]),
        "rows_with_values": int(overall["rows_with_values"]),
        "rows_missing_values": int(overall["rows_missing_values"]),
        "area_codes": int(overall["area_codes"]),
        "area_names": int(overall["area_names"]),
        "item_codes": int(overall["item_codes"]),
        "item_names": int(overall["item_names"]),
        "element_codes": int(overall["element_codes"]),
        "element_names": int(overall["element_names"]),
        "units": int(overall["units"]),
        "flags": int(overall["flags"]),
        "first_year": int(overall["first_year"]),
        "latest_year": int(overall["latest_year"]),
        "years_available": int(overall["years_available"]),
        "countries_and_territories": int(len(countries)),
        "geographic_aggregates": int(len(aggregates)),
        "duplicate_key_groups": int(
            duplicate_summary.loc[
                0,
                "duplicate_key_groups",
            ]
        ),
        "duplicate_excess_rows": int(duplicate_summary.loc[0, "excess_rows"]),
    }

    with JSON_OUTPUT.open("w", encoding="utf-8") as file:
        json.dump(
            profile_json,
            file,
            indent=2,
            default=str,
        )

    top_elements_markdown = elements[
        [
            "element",
            "unit",
            "rows",
            "areas",
            "items",
        ]
    ].to_markdown(index=False)

    area_types_markdown = area_type_summary.to_markdown(index=False)

    flags_markdown = flags.to_markdown(index=False)

    missingness_markdown = column_missingness.to_markdown(index=False)

    loss_coverage_markdown = (
        loss_coverage[
            [
                "item",
                "loss_rows",
                "areas",
                "first_year",
                "latest_year",
            ]
        ]
        .head(30)
        .to_markdown(index=False)
    )

    markdown = f"""# FAOSTAT Food Balances Dataset Overview

## Dataset Summary

- Total rows: {profile_json['total_rows']:,}
- Time range: {profile_json['first_year']} to {profile_json['latest_year']}
- Years available: {profile_json['years_available']}
- Area names: {profile_json['area_names']}
- Countries or territories: {profile_json['countries_and_territories']}
- Geographic aggregates: {profile_json['geographic_aggregates']}
- Food-item names: {profile_json['item_names']}
- Elements: {profile_json['element_names']}
- Units: {profile_json['units']}
- Flag values: {profile_json['flags']}
- Missing values in Value: {profile_json['rows_missing_values']:,}
- Duplicate key groups: {profile_json['duplicate_key_groups']:,}

## What One Record Represents

A normalized record generally represents one:

**Area x Food Item x Element x Year x Unit**

Examples of elements include production, imports, exports, domestic
supply, losses, food availability, calorie supply, protein supply,
processing, feed, seed, and stock variation.

## Geography Types

{area_types_markdown}

Country-level analysis should generally exclude FAOSTAT regional
aggregates. In this dataset, area codes of 5000 or greater are treated
as aggregates for initial analytical screening.

## Available Elements

{top_elements_markdown}

## FAOSTAT Flags

{flags_markdown}

Flags must be retained because some values may be official, estimated,
or imputed.

## Column Missingness

{missingness_markdown}

The Note field is expected to be sparsely populated. Missing values in
individual elements may reflect that the element is not applicable,
not reported, estimated elsewhere, or unavailable.

## Food Items With Loss Data

{loss_coverage_markdown}

## Analytical Cautions

1. Aggregate regions and countries must not be added together.
2. Broad food groups may overlap with specific food items.
3. FAOSTAT Losses do not indicate the cause of loss.
4. Recorded losses are not automatically preventable through preservation.
5. Import quantity divided by domestic supply is a useful proxy, not a
   complete measure of consumer import dependence.
6. Values with estimated or imputed flags require sensitivity analysis.
7. Extreme ratios should be reviewed across multiple years.
8. Country comparisons should use consistent units and elements.

## Generated Supporting Files

Detailed CSV profiles are available under:

`outputs/tables/dataset_overview/`
"""

    MARKDOWN_OUTPUT.write_text(
        markdown,
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print("COMPLETE DATASET OVERVIEW")
    print("=" * 70)

    print(f"Rows: {profile_json['total_rows']:,}")
    print(f"Years: {profile_json['first_year']} to " f"{profile_json['latest_year']}")
    print("Countries or territories: " f"{profile_json['countries_and_territories']}")
    print("Geographic aggregates: " f"{profile_json['geographic_aggregates']}")
    print(f"Food items: {profile_json['item_names']}")
    print(f"Elements: {profile_json['element_names']}")
    print("Duplicate key groups: " f"{profile_json['duplicate_key_groups']:,}")

    print("\nArea types")
    print(area_type_summary.to_string(index=False))

    print("\nElements and units")
    print(
        elements[
            [
                "element",
                "unit",
                "rows",
                "areas",
                "items",
            ]
        ].to_string(index=False)
    )

    print("\nFlags")
    print(flags.to_string(index=False))

    print("\nColumn missingness")
    print(column_missingness.to_string(index=False))

    print("\nFiles created:")
    print(OUTPUT_DIR)
    print(JSON_OUTPUT)
    print(MARKDOWN_OUTPUT)

    connection.close()

    print("\nDataset profiling completed successfully.")


if __name__ == "__main__":
    main()

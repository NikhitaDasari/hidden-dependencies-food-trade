from __future__ import annotations

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

OUTPUT_DIR = ROOT / "outputs" / "tables"
DATABASE_FILE = ROOT / "data" / "processed" / "food_balances.duckdb"

CANDIDATE_PATTERN = "tomato|fruit|apple|grape|mango|banana|" "vegetable|meat|milk|fish"


def save_table(dataframe: pd.DataFrame, filename: str) -> None:
    output_path = OUTPUT_DIR / filename
    dataframe.to_csv(output_path, index=False)
    print(f"Saved: {output_path}")


def main() -> None:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Food Balances CSV not found: {DATA_FILE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(DATABASE_FILE))
    connection.execute("PRAGMA threads=4")

    csv_path = str(DATA_FILE).replace("'", "''")

    connection.execute(f"""
        CREATE OR REPLACE VIEW food_balances AS
        SELECT *
        FROM read_csv_auto(
            '{csv_path}',
            header = true,
            sample_size = 200000
        )
        """)

    profile = connection.execute("""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT "Area") AS areas,
            COUNT(DISTINCT "Item") AS items,
            COUNT(DISTINCT "Element") AS elements,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year
        FROM food_balances
        """).fetchdf()

    print("\nDataset profile")
    print(profile.to_string(index=False))

    year_coverage = connection.execute("""
        SELECT
            "Year" AS year,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Area") AS areas,
            COUNT(DISTINCT "Item") AS items,
            COUNT(DISTINCT "Element") AS elements
        FROM food_balances
        GROUP BY "Year"
        ORDER BY "Year"
        """).fetchdf()

    save_table(
        year_coverage,
        "food_balance_year_coverage.csv",
    )

    elements = connection.execute("""
        SELECT
            "Element" AS element,
            "Unit" AS unit,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Area") AS areas,
            COUNT(DISTINCT "Item") AS items,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year
        FROM food_balances
        GROUP BY "Element", "Unit"
        ORDER BY rows DESC
        """).fetchdf()

    save_table(
        elements,
        "food_balance_elements.csv",
    )

    flags = connection.execute("""
        SELECT
            COALESCE("Flag", '[Missing]') AS flag,
            COUNT(*) AS rows
        FROM food_balances
        GROUP BY "Flag"
        ORDER BY rows DESC
        """).fetchdf()

    save_table(
        flags,
        "food_balance_flags.csv",
    )

    latest_year = int(profile.loc[0, "latest_year"])

    print(f"\nLatest available year: {latest_year}")

    candidate_long = connection.execute(
        """
        SELECT
            "Area Code" AS area_code,
            "Area Code (M49)" AS m49_code,
            "Area" AS area,
            "Item Code" AS item_code,
            "Item" AS item,
            "Element" AS element,
            "Unit" AS unit,
            "Value" AS value,
            "Flag" AS flag
        FROM food_balances
        WHERE "Year" = ?
          AND regexp_matches(LOWER("Item"), ?)
          AND "Element" IN (
              'Production',
              'Import quantity',
              'Export quantity',
              'Domestic supply quantity',
              'Losses',
              'Food',
              'Food supply quantity (kg/capita/yr)',
              'Food supply (kcal/capita/day)',
              'Protein supply quantity (g/capita/day)'
          )
        """,
        [latest_year, CANDIDATE_PATTERN],
    ).fetchdf()

    save_table(
        candidate_long,
        "candidate_food_latest_year_long.csv",
    )

    metrics = candidate_long.pivot_table(
        index=[
            "area_code",
            "m49_code",
            "area",
            "item_code",
            "item",
        ],
        columns="element",
        values="value",
        aggfunc="sum",
    ).reset_index()

    metrics.columns.name = None

    metrics = metrics.rename(
        columns={
            "Production": "production",
            "Import quantity": "imports",
            "Export quantity": "exports",
            "Domestic supply quantity": "domestic_supply",
            "Losses": "losses",
            "Food": "food_quantity",
            "Food supply quantity (kg/capita/yr)": ("food_supply_kg_per_capita"),
            "Food supply (kcal/capita/day)": ("food_supply_kcal_per_capita_day"),
            "Protein supply quantity (g/capita/day)": (
                "protein_supply_g_per_capita_day"
            ),
        }
    )

    numeric_columns = [
        "production",
        "imports",
        "exports",
        "domestic_supply",
        "losses",
        "food_quantity",
        "food_supply_kg_per_capita",
        "food_supply_kcal_per_capita_day",
        "protein_supply_g_per_capita_day",
    ]

    for column in numeric_columns:
        if column not in metrics.columns:
            metrics[column] = pd.NA

        metrics[column] = pd.to_numeric(
            metrics[column],
            errors="coerce",
        )

    metrics["loss_share_of_supply"] = metrics["losses"] / metrics["domestic_supply"]

    metrics["import_dependency_proxy"] = metrics["imports"] / metrics["domestic_supply"]

    valid = (
        metrics["domestic_supply"].gt(0)
        & metrics["loss_share_of_supply"].between(0, 1)
        & metrics["import_dependency_proxy"].between(0, 2)
    )

    metrics["quality_flag"] = "review"
    metrics.loc[valid, "quality_flag"] = "acceptable"

    metrics = metrics.sort_values(
        ["quality_flag", "loss_share_of_supply"],
        ascending=[True, False],
    )

    save_table(
        metrics,
        "candidate_food_country_metrics.csv",
    )

    coverage = metrics.groupby(
        ["item_code", "item"],
        as_index=False,
    ).agg(
        areas=("area", "nunique"),
        valid_loss_observations=(
            "loss_share_of_supply",
            "count",
        ),
        total_losses=("losses", "sum"),
        total_domestic_supply=("domestic_supply", "sum"),
        median_loss_share=(
            "loss_share_of_supply",
            "median",
        ),
        median_import_dependency=(
            "import_dependency_proxy",
            "median",
        ),
    )

    coverage["coverage_score"] = (
        coverage["areas"].rank(pct=True) * 0.35
        + coverage["valid_loss_observations"].rank(pct=True) * 0.35
        + coverage["total_losses"].rank(pct=True) * 0.30
    )

    coverage = coverage.sort_values(
        "coverage_score",
        ascending=False,
    )

    save_table(
        coverage,
        "candidate_food_coverage.csv",
    )

    print("\nLatest year coverage")
    print(year_coverage.tail(10).to_string(index=False))

    print("\nAvailable elements")
    print(elements.to_string(index=False))

    print("\nCandidate-food ranking")
    print(coverage.head(30).to_string(index=False))

    print("\nHighest preliminary loss shares")

    display_columns = [
        "area",
        "item",
        "domestic_supply",
        "losses",
        "loss_share_of_supply",
        "imports",
        "import_dependency_proxy",
    ]

    print(
        metrics.loc[
            metrics["quality_flag"].eq("acceptable"),
            display_columns,
        ]
        .head(30)
        .to_string(index=False)
    )

    connection.close()

    print("\nExploration completed successfully.")


if __name__ == "__main__":
    main()

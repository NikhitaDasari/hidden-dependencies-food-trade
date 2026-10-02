from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/processed/food_balances.duckdb"
GEO_PATH = (
    ROOT
    / "outputs/tables/core_food_country_foundation/unified_geography_capability.csv"
)
REGISTRY_PATH = ROOT / "outputs/tables/core_food_model/core_food_registry.csv"
CHANNELS_PATH = ROOT / "outputs/tables/core_food_model/core_food_product_channels.csv"
OUT = ROOT / "outputs/tables/core_food_fbs_foundation"
ANNUAL_PATH = OUT / "core_food_fbs_annual_2021_2023.csv"
BASELINE_PATH = OUT / "core_food_fbs_baseline_2021_2023.csv"
NATIONAL_PATH = OUT / "core_food_national_nutrition_denominators.csv"
MATERIALITY_PATH = OUT / "core_food_nutritional_materiality.csv"
DENOM_PATH = OUT / "core_food_fbs_denominator_diagnostics.csv"
MAPPING_PATH = OUT / "core_food_fbs_mapping_diagnostics.csv"
SCOPE_PATH = OUT / "core_food_analytical_scopes.csv"
REPORT_PATH = ROOT / "outputs/model_results/core_food_fbs_foundation_summary.json"

YEARS = [2021, 2022, 2023]
ALIASES = {2949: 2744, 2948: 2848}
ELEMENT_LABELS = {
    "production": "Production",
    "imports": "Import Quantity",
    "exports": "Export Quantity",
    "domestic_supply": "Domestic supply quantity",
    "calories": "Food supply (kcal/capita/day)",
    "protein": "Protein supply quantity (g/capita/day)",
    "fat": "Fat supply quantity (g/capita/day)",
}
PHYSICAL = {"production", "imports", "exports", "domestic_supply"}
NUTRITION = {"calories", "protein", "fat"}


def norm_m49(value: object) -> str | None:
    if pd.isna(value):
        return None
    digits = re.sub(r"\D", "", str(value).replace(".0", ""))
    return digits.zfill(3) if digits else None


def canonical_item(value: object) -> int:
    code = int(float(value))
    return ALIASES.get(code, code)


def discover_schema(con: duckdb.DuckDBPyConnection) -> tuple[str, dict[str, int]]:
    cols = con.execute("DESCRIBE main.food_balances").fetchdf()["column_name"].tolist()
    required = {
        "Area Code (M49)",
        "Area",
        "Item Code",
        "Item",
        "Element Code",
        "Element",
        "Year",
        "Unit",
        "Value",
    }
    missing = required - set(cols)
    if missing:
        raise ValueError(f"Food Balance columns missing: {sorted(missing)}")
    elements = con.execute(
        'SELECT DISTINCT CAST("Element Code" AS INTEGER) AS code, "Element" AS element_label FROM main.food_balances'
    ).fetchdf()
    result: dict[str, int] = {}
    for key, label in ELEMENT_LABELS.items():
        exact = elements.loc[
            elements["element_label"].str.casefold().eq(label.casefold())
        ]
        if exact.empty:
            contains = elements.loc[
                elements["element_label"]
                .str.casefold()
                .str.contains(label.casefold(), regex=False)
            ]
            if len(contains) != 1:
                raise ValueError(
                    f"Could not uniquely resolve element {label!r}: {contains.to_dict('records')}"
                )
            exact = contains
        if len(exact) != 1:
            raise ValueError(f"Element label {label!r} is not unique")
        result[key] = int(exact.iloc[0]["code"])
    return "main.food_balances", result


def build_scopes(registry: pd.DataFrame, channels: pd.DataFrame) -> pd.DataFrame:
    code_col = (
        "proposed_fbs_item_code"
        if "proposed_fbs_item_code" in channels.columns
        else "fbs_item_code"
    )
    name_col = (
        "proposed_fbs_item" if "proposed_fbs_item" in channels.columns else "fbs_item"
    )
    channels = channels.copy()
    channels["canonical_fbs_item_code"] = channels[code_col].map(canonical_item)
    channels["canonical_fbs_item"] = channels[name_col]
    grouped = channels.groupby(
        ["core_food_code", "core_food", "canonical_fbs_item_code"], as_index=False
    ).agg(
        canonical_fbs_item=("canonical_fbs_item", "first"),
        trade_item_codes=(
            "trade_item_code",
            lambda x: ";".join(map(str, sorted(set(map(int, x))))),
        ),
        trade_items=("trade_item", lambda x: "; ".join(sorted(set(map(str, x))))),
        quantity_aggregation_policy=("quantity_aggregation_policy", "first"),
        current_model_usage=("current_model_usage", "first"),
    )
    grouped["scope_count_within_core_food"] = grouped.groupby("core_food_code")[
        "canonical_fbs_item_code"
    ].transform("size")
    grouped["analytical_scope_code"] = grouped.apply(
        lambda r: f"{r['core_food_code']}_FBS{int(r['canonical_fbs_item_code'])}",
        axis=1,
    )
    grouped["family_rollup_allowed"] = grouped["scope_count_within_core_food"].eq(1)
    grouped["scope_interpretation"] = np.where(
        grouped["family_rollup_allowed"],
        "CORE_FOOD_FAMILY_DENOMINATOR",
        "ANALYTICAL_SUBFAMILY_DENOMINATOR",
    )
    if grouped["analytical_scope_code"].duplicated().any():
        raise ValueError("Duplicate analytical scope codes")
    if grouped["core_food_code"].nunique() != 21:
        raise ValueError(
            f"Expected 21 Core Foods, found {grouped['core_food_code'].nunique()}"
        )
    return grouped


def status_row(row: pd.Series) -> str:
    if pd.isna(row["domestic_supply_tonnes"]):
        return "DOMESTIC_SUPPLY_MISSING"
    if row["domestic_supply_tonnes"] == 0:
        return "DOMESTIC_SUPPLY_ZERO"
    if row["domestic_supply_tonnes"] < 0:
        return "DOMESTIC_SUPPLY_NEGATIVE"
    missing = []
    for key in ["imports_tonnes", "exports_tonnes", "production_tonnes"]:
        if pd.isna(row[key]):
            missing.append(key.replace("_tonnes", "").upper() + "_MISSING")
    return "|".join(missing) if missing else "VALID_POSITIVE"


def main() -> None:
    for path in [DB_PATH, GEO_PATH, REGISTRY_PATH, CHANNELS_PATH]:
        if not path.exists():
            raise FileNotFoundError(path)

    geo = pd.read_csv(GEO_PATH, dtype={"entity_m49": "string"})
    registry = pd.read_csv(REGISTRY_PATH)
    channels = pd.read_csv(CHANNELS_PATH)
    scopes = build_scopes(registry, channels)

    eligible_geo = geo.loc[geo["eligible_for_fbs_reliance_candidate"]].copy()
    eligible_geo["entity_m49"] = eligible_geo["entity_m49"].map(norm_m49)
    if eligible_geo["entity_m49"].duplicated().any():
        raise ValueError("Duplicate eligible FBS entity M49 values")
    if (
        eligible_geo["is_composite_geography"].any()
        or eligible_geo["is_aggregate"].any()
    ):
        raise ValueError("Blocked geography entered FBS universe")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    table, elements = discover_schema(con)
    item_codes = sorted(scopes["canonical_fbs_item_code"].astype(int).unique().tolist())
    element_codes = sorted(elements.values())
    raw = con.execute(
        f"""
        SELECT
            CAST("Area Code (M49)" AS VARCHAR) AS area_m49_raw,
            "Area" AS area_name,
            CAST("Item Code" AS INTEGER) AS item_code,
            "Item" AS item_name,
            CAST("Element Code" AS INTEGER) AS element_code,
            "Element" AS element_name,
            CAST("Year" AS INTEGER) AS year,
            "Unit" AS unit,
            CAST("Value" AS DOUBLE) AS value,
            COALESCE(CAST("Flag" AS VARCHAR), '') AS flag
        FROM {table}
        WHERE CAST("Year" AS INTEGER) BETWEEN 2021 AND 2023
          AND CAST("Element Code" AS INTEGER) IN ({",".join(map(str, element_codes))})
          AND CAST("Item Code" AS INTEGER) IN ({",".join(map(str, item_codes + list(ALIASES)))})
        """
    ).fetchdf()
    grand_total_items = con.execute(
        f"""
        SELECT DISTINCT CAST("Item Code" AS INTEGER) AS item_code, "Item" AS item_name
        FROM {table}
        WHERE lower(trim("Item")) = 'grand total'
        """
    ).fetchdf()
    if len(grand_total_items) != 1:
        raise ValueError(
            "Expected exactly one Food Balance Grand Total item for national nutrition "
            f"denominators, found: {grand_total_items.to_dict('records')}"
        )
    grand_total_item_code = int(grand_total_items.iloc[0]["item_code"])
    all_nutrition = con.execute(
        f"""
        SELECT
            CAST("Area Code (M49)" AS VARCHAR) AS area_m49_raw,
            CAST("Year" AS INTEGER) AS year,
            CAST("Element Code" AS INTEGER) AS element_code,
            MAX(CAST("Value" AS DOUBLE)) AS total_value,
            COUNT(*) FILTER (WHERE "Value" IS NOT NULL) AS contributing_rows
        FROM {table}
        WHERE CAST("Year" AS INTEGER) BETWEEN 2021 AND 2023
          AND CAST("Element Code" AS INTEGER) IN ({",".join(map(str, [elements[k] for k in NUTRITION]))})
          AND CAST("Item Code" AS INTEGER) = {grand_total_item_code}
        GROUP BY 1, 2, 3
        """
    ).fetchdf()
    con.close()

    raw["entity_m49"] = raw["area_m49_raw"].map(norm_m49)
    raw["canonical_fbs_item_code"] = raw["item_code"].map(canonical_item)
    all_nutrition["entity_m49"] = all_nutrition["area_m49_raw"].map(norm_m49)
    raw = raw.loc[raw["entity_m49"].isin(set(eligible_geo["entity_m49"]))].copy()
    all_nutrition = all_nutrition.loc[
        all_nutrition["entity_m49"].isin(set(eligible_geo["entity_m49"]))
    ].copy()

    reverse_elements = {value: key for key, value in elements.items()}
    raw["metric"] = raw["element_code"].map(reverse_elements)
    raw["metric_value"] = raw["value"]
    raw.loc[raw["metric"].isin(PHYSICAL), "metric_value"] *= 1000.0

    agg = raw.groupby(
        ["entity_m49", "canonical_fbs_item_code", "year", "metric"], as_index=False
    ).agg(
        metric_value=("metric_value", "sum"),
        source_rows=("value", "size"),
        nonnull_rows=("value", "count"),
        flags=("flag", lambda x: "|".join(sorted({v for v in map(str, x) if v}))),
        source_units=("unit", lambda x: "|".join(sorted(set(map(str, x))))),
    )
    values = agg.pivot(
        index=["entity_m49", "canonical_fbs_item_code", "year"],
        columns="metric",
        values="metric_value",
    ).reset_index()
    flags = agg.pivot(
        index=["entity_m49", "canonical_fbs_item_code", "year"],
        columns="metric",
        values="flags",
    ).reset_index()
    flags = flags.rename(
        columns={
            key: f"{key}_flags"
            for key in reverse_elements.values()
            if key in flags.columns
        }
    )

    grid = eligible_geo[
        ["entity_m49", "entity_name", "entity_type", "capability_status"]
    ].merge(scopes, how="cross")
    grid = grid.merge(pd.DataFrame({"year": YEARS}), how="cross")
    annual = grid.merge(
        values, on=["entity_m49", "canonical_fbs_item_code", "year"], how="left"
    )
    annual = annual.merge(
        flags, on=["entity_m49", "canonical_fbs_item_code", "year"], how="left"
    )

    annual = annual.rename(
        columns={
            "production": "production_tonnes",
            "imports": "imports_tonnes",
            "exports": "exports_tonnes",
            "domestic_supply": "domestic_supply_tonnes",
            "calories": "food_supply_kcal_capita_day",
            "protein": "protein_supply_g_capita_day",
            "fat": "fat_supply_g_capita_day",
        }
    )
    for column in [
        "production_tonnes",
        "imports_tonnes",
        "exports_tonnes",
        "domestic_supply_tonnes",
        "food_supply_kcal_capita_day",
        "protein_supply_g_capita_day",
        "fat_supply_g_capita_day",
    ]:
        if column not in annual:
            annual[column] = np.nan

    annual["denominator_status"] = annual.apply(status_row, axis=1)
    annual["gross_reliance_available"] = (
        annual["domestic_supply_tonnes"].gt(0) & annual["imports_tonnes"].notna()
    )
    annual["net_dependence_available"] = (
        annual["domestic_supply_tonnes"].gt(0)
        & annual["imports_tonnes"].notna()
        & annual["exports_tonnes"].notna()
    )
    annual["production_coverage_available"] = (
        annual["domestic_supply_tonnes"].gt(0) & annual["production_tonnes"].notna()
    )
    positive = annual["domestic_supply_tonnes"].gt(0)
    annual["gross_import_reliance_raw"] = np.where(
        annual["gross_reliance_available"],
        annual["imports_tonnes"] / annual["domestic_supply_tonnes"],
        np.nan,
    )
    annual["gross_import_reliance_capped"] = annual["gross_import_reliance_raw"].clip(
        0, 1
    )
    annual["net_import_dependence_raw"] = np.where(
        annual["net_dependence_available"],
        (annual["imports_tonnes"] - annual["exports_tonnes"])
        / annual["domestic_supply_tonnes"],
        np.nan,
    )
    annual["net_import_dependence_bounded"] = annual["net_import_dependence_raw"].clip(
        -1, 1
    )
    annual["production_coverage_raw"] = np.where(
        annual["production_coverage_available"],
        annual["production_tonnes"] / annual["domestic_supply_tonnes"],
        np.nan,
    )
    annual["reexport_balance_signal"] = np.where(
        annual["imports_tonnes"].gt(0) & annual["exports_tonnes"].notna(),
        np.minimum(annual["imports_tonnes"], annual["exports_tonnes"])
        / annual["imports_tonnes"],
        np.nan,
    )
    annual["is_complete_gross_reliance_row"] = annual["gross_reliance_available"]
    annual["is_complete_net_dependence_row"] = annual["net_dependence_available"]
    annual["is_complete_production_coverage_row"] = annual[
        "production_coverage_available"
    ]
    annual["is_complete_reliance_row"] = (
        annual["gross_reliance_available"] & annual["net_dependence_available"]
    )
    annual["final_vulnerability_ranking_allowed"] = False

    all_nutrition["metric"] = all_nutrition["element_code"].map(reverse_elements)
    national = all_nutrition.pivot(
        index=["entity_m49", "year"], columns="metric", values="total_value"
    ).reset_index()
    national = national.rename(
        columns={
            "calories": "national_food_supply_kcal_capita_day",
            "protein": "national_protein_supply_g_capita_day",
            "fat": "national_fat_supply_g_capita_day",
        }
    )
    annual = annual.merge(national, on=["entity_m49", "year"], how="left")
    annual["national_calorie_materiality"] = (
        annual["food_supply_kcal_capita_day"]
        / annual["national_food_supply_kcal_capita_day"]
    )
    annual["national_protein_materiality"] = (
        annual["protein_supply_g_capita_day"]
        / annual["national_protein_supply_g_capita_day"]
    )
    annual["national_fat_materiality"] = (
        annual["fat_supply_g_capita_day"] / annual["national_fat_supply_g_capita_day"]
    )

    portfolio = annual.groupby(["entity_m49", "year"], as_index=False).agg(
        portfolio_kcal=("food_supply_kcal_capita_day", lambda x: x.sum(min_count=1)),
        portfolio_protein=("protein_supply_g_capita_day", lambda x: x.sum(min_count=1)),
        portfolio_fat=("fat_supply_g_capita_day", lambda x: x.sum(min_count=1)),
    )
    annual = annual.merge(portfolio, on=["entity_m49", "year"], how="left")
    annual["core_food_portfolio_calorie_share"] = (
        annual["food_supply_kcal_capita_day"] / annual["portfolio_kcal"]
    )
    annual["core_food_portfolio_protein_share"] = (
        annual["protein_supply_g_capita_day"] / annual["portfolio_protein"]
    )
    annual["core_food_portfolio_fat_share"] = (
        annual["fat_supply_g_capita_day"] / annual["portfolio_fat"]
    )

    # Guardrails.
    if (
        annual.loc[
            ~positive,
            [
                "gross_import_reliance_raw",
                "net_import_dependence_raw",
                "production_coverage_raw",
            ],
        ]
        .notna()
        .any()
        .any()
    ):
        raise ValueError(
            "A ratio was calculated with a missing or nonpositive denominator"
        )
    if (
        annual.loc[~annual["gross_reliance_available"], "gross_import_reliance_raw"]
        .notna()
        .any()
    ):
        raise ValueError("Gross reliance calculated without required inputs")
    if (
        annual.loc[~annual["net_dependence_available"], "net_import_dependence_raw"]
        .notna()
        .any()
    ):
        raise ValueError("Net dependence calculated without required inputs")
    if (
        annual.loc[~annual["production_coverage_available"], "production_coverage_raw"]
        .notna()
        .any()
    ):
        raise ValueError("Production coverage calculated without required inputs")
    if annual["final_vulnerability_ranking_allowed"].any():
        raise ValueError("A vulnerability ranking was enabled prematurely")
    if "159" in set(annual["entity_m49"].astype(str)):
        raise ValueError("Composite China entered the FBS foundation")

    baseline = annual.groupby(
        [
            "entity_m49",
            "entity_name",
            "entity_type",
            "core_food_code",
            "core_food",
            "analytical_scope_code",
            "canonical_fbs_item_code",
            "canonical_fbs_item",
            "scope_interpretation",
            "family_rollup_allowed",
        ],
        as_index=False,
    ).agg(
        years_present=("year", "nunique"),
        complete_reliance_years=("is_complete_reliance_row", "sum"),
        baseline_imports_tonnes=("imports_tonnes", lambda x: x.sum(min_count=1)),
        baseline_exports_tonnes=("exports_tonnes", lambda x: x.sum(min_count=1)),
        baseline_production_tonnes=("production_tonnes", lambda x: x.sum(min_count=1)),
        baseline_domestic_supply_tonnes=(
            "domestic_supply_tonnes",
            lambda x: x.sum(min_count=1),
        ),
        mean_food_supply_kcal_capita_day=("food_supply_kcal_capita_day", "mean"),
        mean_protein_supply_g_capita_day=("protein_supply_g_capita_day", "mean"),
        mean_fat_supply_g_capita_day=("fat_supply_g_capita_day", "mean"),
        mean_national_calorie_materiality=("national_calorie_materiality", "mean"),
        mean_national_protein_materiality=("national_protein_materiality", "mean"),
        mean_national_fat_materiality=("national_fat_materiality", "mean"),
    )
    bpositive = baseline["baseline_domestic_supply_tonnes"].gt(0)
    baseline["baseline_gross_import_reliance_raw"] = np.where(
        bpositive,
        baseline["baseline_imports_tonnes"]
        / baseline["baseline_domestic_supply_tonnes"],
        np.nan,
    )
    baseline["baseline_gross_import_reliance_capped"] = baseline[
        "baseline_gross_import_reliance_raw"
    ].clip(0, 1)
    baseline["baseline_net_import_dependence_raw"] = np.where(
        bpositive,
        (baseline["baseline_imports_tonnes"] - baseline["baseline_exports_tonnes"])
        / baseline["baseline_domestic_supply_tonnes"],
        np.nan,
    )
    baseline["baseline_net_import_dependence_bounded"] = baseline[
        "baseline_net_import_dependence_raw"
    ].clip(-1, 1)
    baseline["baseline_production_coverage_raw"] = np.where(
        bpositive,
        baseline["baseline_production_tonnes"]
        / baseline["baseline_domestic_supply_tonnes"],
        np.nan,
    )
    baseline["baseline_complete"] = baseline["complete_reliance_years"].eq(3)
    baseline["final_vulnerability_ranking_allowed"] = False

    mapping_diag = scopes.copy()
    mapping_diag["core_food_has_multiple_fbs_denominators"] = mapping_diag[
        "scope_count_within_core_food"
    ].gt(1)
    mapping_diag["unsafe_family_physical_rollup_blocked"] = ~mapping_diag[
        "family_rollup_allowed"
    ]

    denom_diag = (
        annual.groupby(
            [
                "core_food_code",
                "core_food",
                "analytical_scope_code",
                "denominator_status",
            ],
            as_index=False,
        )
        .size()
        .rename(columns={"size": "rows"})
    )
    materiality = annual[
        [
            "entity_m49",
            "entity_name",
            "year",
            "core_food_code",
            "core_food",
            "analytical_scope_code",
            "national_calorie_materiality",
            "national_protein_materiality",
            "national_fat_materiality",
            "core_food_portfolio_calorie_share",
            "core_food_portfolio_protein_share",
            "core_food_portfolio_fat_share",
        ]
    ].copy()

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL_PATH, index=False)
    baseline.to_csv(BASELINE_PATH, index=False)
    national.to_csv(NATIONAL_PATH, index=False)
    materiality.to_csv(MATERIALITY_PATH, index=False)
    denom_diag.to_csv(DENOM_PATH, index=False)
    mapping_diag.to_csv(MAPPING_PATH, index=False)
    scopes.to_csv(SCOPE_PATH, index=False)

    report = {
        "dataset": "Core Food FBS foundation",
        "baseline_period": "2021-2023",
        "core_foods": int(scopes["core_food_code"].nunique()),
        "analytical_scopes": len(scopes),
        "eligible_fbs_entities": len(eligible_geo),
        "annual_rows": len(annual),
        "baseline_rows": len(baseline),
        "complete_annual_reliance_rows": int(annual["is_complete_reliance_row"].sum()),
        "complete_baseline_rows": int(baseline["baseline_complete"].sum()),
        "element_codes_discovered": elements,
        "national_nutrition_grand_total_item_code": grand_total_item_code,
        "controls": {
            "gross_and_net_import_dependence_separate": True,
            "positive_denominator_required": True,
            "missing_values_not_zero_filled": True,
            "national_nutrition_uses_full_fbs_universe": True,
            "multi_denominator_family_rollup_blocked": True,
            "composite_china_excluded": True,
            "final_rankings_enabled": False,
        },
        "outputs": {
            "annual": str(ANNUAL_PATH.relative_to(ROOT)),
            "baseline": str(BASELINE_PATH.relative_to(ROOT)),
            "national_nutrition": str(NATIONAL_PATH.relative_to(ROOT)),
            "materiality": str(MATERIALITY_PATH.relative_to(ROOT)),
            "denominator_diagnostics": str(DENOM_PATH.relative_to(ROOT)),
            "mapping_diagnostics": str(MAPPING_PATH.relative_to(ROOT)),
            "analytical_scopes": str(SCOPE_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("=" * 72)
    print("CORE FOOD FBS FOUNDATION BUILD COMPLETE")
    print("=" * 72)
    print(f"Core Foods: {report['core_foods']}")
    print(f"Analytical scopes: {report['analytical_scopes']}")
    print(f"Eligible FBS entities: {report['eligible_fbs_entities']}")
    print(f"Annual rows: {report['annual_rows']:,}")
    print(f"Baseline rows: {report['baseline_rows']:,}")
    print(f"Complete baseline rows: {report['complete_baseline_rows']:,}")
    print("No final vulnerability rankings were enabled.")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

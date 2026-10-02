from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION_DIR = ROOT / "outputs/tables/core_food_fbs_foundation"
ANNUAL_PATH = FOUNDATION_DIR / "core_food_fbs_annual_2021_2023.csv"
BASELINE_PATH = FOUNDATION_DIR / "core_food_fbs_baseline_2021_2023.csv"
SCOPES_PATH = FOUNDATION_DIR / "core_food_analytical_scopes.csv"

USABILITY_PATH = FOUNDATION_DIR / "core_food_fbs_baseline_usability.csv"
READY_PATH = FOUNDATION_DIR / "core_food_fbs_baseline_ready.csv"
PARTIAL_PATH = FOUNDATION_DIR / "core_food_fbs_partial_baselines.csv"
REVIEW_PATH = FOUNDATION_DIR / "core_food_fbs_data_review.csv"
DIAGNOSTICS_PATH = FOUNDATION_DIR / "core_food_fbs_usability_diagnostics.csv"
REPORT_PATH = (
    ROOT / "outputs/model_results/core_food_fbs_baseline_usability_summary.json"
)

EXPECTED_YEARS = {2021, 2022, 2023}
REMAINING_GATES = (
    "COUNTRY_APPROVAL|TRADE_NETWORK_COVERAGE|MAPPING_ALIGNMENT|"
    "CONFIDENCE_REVIEW|FINAL_QA"
)


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise ValueError(f"Required annual availability column missing: {column}")
    values = frame[column]
    if values.dtype == bool:
        return values
    return (
        values.astype("string")
        .str.casefold()
        .map({"true": True, "false": False})
        .fillna(False)
    )


def count_status(group: pd.DataFrame, status: str) -> int:
    return int(group["denominator_status"].eq(status).sum())


def classify_usability(row: pd.Series) -> str:
    if row["negative_domestic_supply_years"] > 0:
        return "NEGATIVE_DENOMINATOR_PRESENT"
    if row["net_dependence_years_available"] == 3:
        return "COMPLETE_3_YEAR"
    if row["net_dependence_years_available"] == 2:
        return "USABLE_2_YEAR"
    if row["net_dependence_years_available"] == 1:
        return "USABLE_1_YEAR"
    if (
        row["zero_domestic_supply_years"] > 0
        and row["positive_domestic_supply_years"] == 0
        and row["missing_domestic_supply_years"] == 0
    ):
        return "ZERO_DENOMINATOR_ONLY"
    if row["missing_domestic_supply_years"] > 0:
        return "MISSING_DOMESTIC_SUPPLY"
    if (
        row["gross_reliance_years_available"] == 0
        and row["imports_available_years"] < 3
    ):
        return "MISSING_IMPORT_COMPONENT"
    if (
        row["gross_reliance_years_available"] > 0
        and row["net_dependence_years_available"] == 0
        and row["exports_available_years"] < 3
    ):
        return "MISSING_EXPORT_COMPONENT"
    return "NO_USABLE_RELIANCE_YEAR"


def build_issue_flags(row: pd.Series) -> str:
    flags: list[str] = []
    if row["negative_domestic_supply_years"]:
        flags.append("NEGATIVE_DOMESTIC_SUPPLY")
    if row["zero_domestic_supply_years"]:
        flags.append("ZERO_DOMESTIC_SUPPLY")
    if row["missing_domestic_supply_years"]:
        flags.append("MISSING_DOMESTIC_SUPPLY")
    if row["imports_available_years"] < 3:
        flags.append("IMPORTS_INCOMPLETE")
    if row["exports_available_years"] < 3:
        flags.append("EXPORTS_INCOMPLETE")
    if row["production_available_years"] < 3:
        flags.append("PRODUCTION_INCOMPLETE")
    if row["nutrition_available_years"] < 3:
        flags.append("NUTRITION_INCOMPLETE")
    if not row["family_rollup_allowed"]:
        flags.append("ANALYTICAL_SUBFAMILY_ONLY")
    if row["scope_confidence_class"] in {
        "PARTIAL_PRODUCT_CHANNEL",
        "CONVERSION_REQUIRED",
        "SENSITIVITY_ONLY",
    }:
        flags.append(row["scope_confidence_class"])
    return "|".join(flags)


def classify_data_confidence(row: pd.Series) -> str:
    if row["negative_domestic_supply_years"] > 0:
        return "DATA_REVIEW"
    if (
        row["net_dependence_years_available"] == 3
        and row["missing_domestic_supply_years"] == 0
    ):
        return "HIGH"
    if row["net_dependence_years_available"] == 2:
        return "MODERATE"
    if row["gross_reliance_years_available"] >= 1:
        return "PARTIAL"
    return "LOW"


def classify_scope_confidence(row: pd.Series) -> str:
    interpretation = str(row.get("scope_interpretation", ""))
    policy = str(row.get("quantity_aggregation_policy", "")).casefold()
    usage = str(row.get("current_model_usage", "")).casefold()

    if "sensitivity" in usage:
        return "SENSITIVITY_ONLY"
    if "conversion" in policy or "equivalent" in policy:
        return "CONVERSION_REQUIRED"
    if interpretation == "ANALYTICAL_SUBFAMILY_DENOMINATOR":
        return "ANALYTICAL_SUBFAMILY"
    if "partial" in policy or "partial" in usage or "channel" in usage:
        return "PARTIAL_PRODUCT_CHANNEL"
    return "DIRECT_FAMILY"


def overall_confidence(row: pd.Series) -> str:
    data_confidence = row["data_confidence_class"]
    scope_confidence = row["scope_confidence_class"]

    if data_confidence == "DATA_REVIEW":
        return "DATA_REVIEW"
    if scope_confidence in {"CONVERSION_REQUIRED", "SENSITIVITY_ONLY"}:
        return (
            "PARTIAL" if data_confidence in {"HIGH", "MODERATE", "PARTIAL"} else "LOW"
        )
    if scope_confidence == "PARTIAL_PRODUCT_CHANNEL" and data_confidence in {
        "HIGH",
        "MODERATE",
    }:
        return "PARTIAL"
    if scope_confidence == "ANALYTICAL_SUBFAMILY" and data_confidence == "HIGH":
        return "MODERATE"
    return data_confidence


def main() -> None:
    for path in [ANNUAL_PATH, BASELINE_PATH, SCOPES_PATH]:
        if not path.exists():
            raise FileNotFoundError(path)

    annual = pd.read_csv(ANNUAL_PATH, dtype={"entity_m49": "string"})
    baseline = pd.read_csv(BASELINE_PATH, dtype={"entity_m49": "string"})
    scopes = pd.read_csv(SCOPES_PATH)

    if set(annual["year"].dropna().astype(int)) != EXPECTED_YEARS:
        raise ValueError("Annual foundation does not contain exactly 2021-2023")

    key = ["entity_m49", "analytical_scope_code"]
    if annual.duplicated(key + ["year"]).any():
        raise ValueError("Duplicate economy-scope-year rows found")
    if baseline.duplicated(key).any():
        raise ValueError("Duplicate economy-scope baseline rows found")
    if len(baseline) != 4048:
        raise ValueError(f"Expected 4,048 baselines, found {len(baseline):,}")

    annual = annual.copy()
    annual["gross_reliance_available"] = bool_series(annual, "gross_reliance_available")
    annual["net_dependence_available"] = bool_series(annual, "net_dependence_available")
    annual["production_coverage_available"] = bool_series(
        annual, "production_coverage_available"
    )
    annual["nutrition_available"] = (
        annual[
            [
                "food_supply_kcal_capita_day",
                "protein_supply_g_capita_day",
                "fat_supply_g_capita_day",
            ]
        ]
        .notna()
        .all(axis=1)
    )

    annual["positive_domestic_supply"] = annual["domestic_supply_tonnes"].gt(0)
    annual["zero_domestic_supply"] = annual["domestic_supply_tonnes"].eq(0)
    annual["negative_domestic_supply"] = annual["domestic_supply_tonnes"].lt(0)
    annual["missing_domestic_supply"] = annual["domestic_supply_tonnes"].isna()

    coverage = annual.groupby(key, as_index=False).agg(
        gross_reliance_years_available=("gross_reliance_available", "sum"),
        net_dependence_years_available=("net_dependence_available", "sum"),
        production_coverage_years_available=("production_coverage_available", "sum"),
        positive_domestic_supply_years=("positive_domestic_supply", "sum"),
        zero_domestic_supply_years=("zero_domestic_supply", "sum"),
        negative_domestic_supply_years=("negative_domestic_supply", "sum"),
        missing_domestic_supply_years=("missing_domestic_supply", "sum"),
        imports_available_years=("imports_tonnes", lambda x: int(x.notna().sum())),
        exports_available_years=("exports_tonnes", lambda x: int(x.notna().sum())),
        production_available_years=(
            "production_tonnes",
            lambda x: int(x.notna().sum()),
        ),
        nutrition_available_years=("nutrition_available", "sum"),
        annual_statuses=(
            "denominator_status",
            lambda x: "|".join(sorted(set(map(str, x)))),
        ),
    )

    scope_columns = [
        "analytical_scope_code",
        "family_rollup_allowed",
        "scope_interpretation",
        "quantity_aggregation_policy",
        "current_model_usage",
    ]
    missing_scope_columns = [
        column for column in scope_columns if column not in scopes.columns
    ]
    if missing_scope_columns:
        raise ValueError(f"Analytical scope columns missing: {missing_scope_columns}")

    usability = baseline.merge(coverage, on=key, how="left", validate="one_to_one")
    usability = usability.merge(
        scopes[scope_columns],
        on="analytical_scope_code",
        how="left",
        validate="many_to_one",
        suffixes=("", "_scope"),
    )

    for column in ["family_rollup_allowed", "scope_interpretation"]:
        scope_version = f"{column}_scope"
        if scope_version in usability.columns:
            usability[column] = usability[column].combine_first(
                usability[scope_version]
            )
            usability = usability.drop(columns=[scope_version])

    usability["scope_confidence_class"] = usability.apply(
        classify_scope_confidence, axis=1
    )
    usability["baseline_usability_class"] = usability.apply(classify_usability, axis=1)
    usability["data_confidence_class"] = usability.apply(
        classify_data_confidence, axis=1
    )
    usability["overall_confidence_class"] = usability.apply(overall_confidence, axis=1)
    usability["baseline_issue_flags"] = usability.apply(build_issue_flags, axis=1)

    usability["ready_for_network_linkage"] = (
        usability["gross_reliance_years_available"].ge(2)
        & usability["negative_domestic_supply_years"].eq(0)
        & usability["baseline_domestic_supply_tonnes"].gt(0)
        & usability["baseline_imports_tonnes"].notna()
        & ~usability["scope_confidence_class"].isin(
            ["CONVERSION_REQUIRED", "SENSITIVITY_ONLY"]
        )
    )
    usability["ready_for_final_ranking"] = False
    usability["remaining_gates"] = REMAINING_GATES

    # A pooled metric may exist even when linkage is not ready. Keep these concepts separate.
    usability["pooled_gross_metric_available"] = (
        usability["baseline_domestic_supply_tonnes"].gt(0)
        & usability["baseline_imports_tonnes"].notna()
    )
    usability["pooled_net_metric_available"] = (
        usability["baseline_domestic_supply_tonnes"].gt(0)
        & usability["baseline_imports_tonnes"].notna()
        & usability["baseline_exports_tonnes"].notna()
    )

    # Guardrails.
    if len(usability) != len(baseline):
        raise ValueError("Not every baseline was classified exactly once")
    if usability.duplicated(key).any():
        raise ValueError("Duplicate classified baselines found")
    negative = usability["negative_domestic_supply_years"].gt(0)
    if not usability.loc[negative, "overall_confidence_class"].eq("DATA_REVIEW").all():
        raise ValueError("Negative-denominator baselines were not assigned DATA_REVIEW")
    if usability["ready_for_final_ranking"].any():
        raise ValueError("A baseline was prematurely marked ready for final ranking")
    if (
        usability.loc[
            usability["ready_for_network_linkage"], "negative_domestic_supply_years"
        ]
        .gt(0)
        .any()
    ):
        raise ValueError("Negative-denominator baseline entered network linkage")
    if (
        usability.loc[
            usability["ready_for_network_linkage"], "gross_reliance_years_available"
        ]
        .lt(2)
        .any()
    ):
        raise ValueError(
            "Network linkage approved with fewer than two gross-reliance years"
        )

    ready = usability.loc[usability["ready_for_network_linkage"]].copy()
    partial = usability.loc[
        ~usability["ready_for_network_linkage"]
        & usability["gross_reliance_years_available"].ge(1)
        & ~negative
    ].copy()
    review = usability.loc[
        negative
        | usability["baseline_usability_class"].isin(
            [
                "NO_USABLE_RELIANCE_YEAR",
                "ZERO_DENOMINATOR_ONLY",
                "MISSING_DOMESTIC_SUPPLY",
                "MISSING_IMPORT_COMPONENT",
                "MISSING_EXPORT_COMPONENT",
            ]
        )
    ].copy()

    diagnostics = (
        usability.groupby(
            [
                "baseline_usability_class",
                "data_confidence_class",
                "scope_confidence_class",
                "overall_confidence_class",
                "ready_for_network_linkage",
            ],
            dropna=False,
            as_index=False,
        )
        .size()
        .rename(columns={"size": "baseline_rows"})
        .sort_values("baseline_rows", ascending=False)
    )

    FOUNDATION_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    usability.to_csv(USABILITY_PATH, index=False)
    ready.to_csv(READY_PATH, index=False)
    partial.to_csv(PARTIAL_PATH, index=False)
    review.to_csv(REVIEW_PATH, index=False)
    diagnostics.to_csv(DIAGNOSTICS_PATH, index=False)

    report = {
        "dataset": "Core Food FBS baseline usability and confidence",
        "total_baselines": len(usability),
        "ready_for_network_linkage": len(ready),
        "partial_baselines": len(partial),
        "data_review_baselines": int(
            usability["overall_confidence_class"].eq("DATA_REVIEW").sum()
        ),
        "ready_for_final_ranking": 0,
        "usability_counts": {
            str(k): int(v)
            for k, v in usability["baseline_usability_class"].value_counts().items()
        },
        "overall_confidence_counts": {
            str(k): int(v)
            for k, v in usability["overall_confidence_class"].value_counts().items()
        },
        "controls": {
            "all_4048_baselines_classified_once": True,
            "negative_denominator_requires_data_review": True,
            "pooled_metric_separate_from_linkage_readiness": True,
            "multi_denominator_scopes_remain_separate": True,
            "no_final_ranking_enabled": True,
        },
        "outputs": {
            "usability": str(USABILITY_PATH.relative_to(ROOT)),
            "ready": str(READY_PATH.relative_to(ROOT)),
            "partial": str(PARTIAL_PATH.relative_to(ROOT)),
            "data_review": str(REVIEW_PATH.relative_to(ROOT)),
            "diagnostics": str(DIAGNOSTICS_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD FBS BASELINE USABILITY BUILD COMPLETE")
    print("=" * 72)
    print(f"Total baselines classified: {len(usability):,}")
    print(f"Ready for network linkage: {len(ready):,}")
    print(f"Partial baselines: {len(partial):,}")
    print(f"Data-review baselines: {report['data_review_baselines']:,}")
    print("\nUsability classes:")
    print(usability["baseline_usability_class"].value_counts().to_string())
    print("\nOverall confidence:")
    print(usability["overall_confidence_class"].value_counts().to_string())
    print("\nNo baseline was marked ready for final ranking.")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

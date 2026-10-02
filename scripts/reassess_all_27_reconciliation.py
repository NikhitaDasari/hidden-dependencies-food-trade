from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "outputs/tables/reconciliation/tier1_country_year_reconciliation.csv"
SEED = (
    ROOT
    / "outputs/tables/crosswalk_discovery/food_crosswalk_tier1_reconciliation_seed.csv"
)
OUT_DIR = ROOT / "outputs/tables/reconciliation_v2"
COMPONENT_OUT = OUT_DIR / "all_27_component_metrics.csv"
GROUP_OUT = OUT_DIR / "food_group_metrics.csv"
DECISION_OUT = OUT_DIR / "all_27_inclusion_roles.csv"
REPORT = ROOT / "outputs/model_results/tier1_reconciliation_v2_report.json"

MIN_FBS_TONNES_CORE = 1_000.0
RATIO_FLOOR = 1e-9

# Every trade item remains represented. The role controls interpretation rather than deletion.
ROLE_OVERRIDES = {
    30: ("alternative_variant", "rice", "Compare with item 31; do not add by default."),
    31: ("alternative_variant", "rice", "Compare with item 30; do not add by default."),
    16: (
        "supplementary_component",
        "wheat",
        "Evaluate Wheat alone and Wheat plus flour.",
    ),
    118: (
        "supplementary_component",
        "potatoes",
        "Evaluate Potatoes alone and Potatoes plus frozen potatoes.",
    ),
    162: (
        "alternative_or_bundle_test",
        "sugar",
        "Test separately and combined with refined sugar as sensitivity.",
    ),
    164: (
        "alternative_or_bundle_test",
        "sugar",
        "Test separately and combined with raw centrifugal sugar as sensitivity.",
    ),
    882: (
        "partial_proxy",
        "milk",
        "Raw milk is only one component of Milk excluding butter.",
    ),
    1062: (
        "partial_proxy",
        "eggs",
        "Shell eggs are only one component of the Eggs category.",
    ),
    1058: (
        "partial_proxy",
        "poultry_meat",
        "Fresh/chilled chicken is a partial Poultry Meat component.",
    ),
    870: (
        "partial_proxy",
        "bovine_meat",
        "Boneless fresh/chilled cattle meat is a partial Bovine Meat component.",
    ),
    656: (
        "partial_proxy",
        "coffee",
        "Green coffee is a partial Coffee and products component.",
    ),
    388: (
        "partial_proxy",
        "tomatoes",
        "Fresh tomatoes are a partial Tomatoes and products component.",
    ),
    128: (
        "partial_proxy",
        "cassava",
        "Dry cassava is a partial Cassava and products component.",
    ),
}

# Bundle tests are explicit and auditable. Variants remain separate where overlap is unresolved.
BUNDLES = {
    "wheat_primary": [15],
    "wheat_plus_flour_sensitivity": [15, 16],
    "potatoes_primary": [116],
    "potatoes_plus_frozen_sensitivity": [116, 118],
    "rice_paddy_equivalent": [30],
    "rice_milled": [31],
    "rice_combined_sensitivity_only": [30, 31],
    "sugar_raw_equivalent_candidate": [162],
    "sugar_refined_candidate": [164],
    "sugar_combined_sensitivity_only": [162, 164],
}


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return float("nan")
    frame = pd.DataFrame(
        {"value": values[valid], "weight": weights[valid]}
    ).sort_values("value")
    cutoff = frame["weight"].sum() / 2
    return float(frame.loc[frame["weight"].cumsum().ge(cutoff), "value"].iloc[0])


def metrics(frame: pd.DataFrame) -> dict:
    matched = frame.loc[frame["fbs_import_tonnes"].notna()].copy()
    positive = matched.loc[matched["fbs_import_tonnes"].gt(0)].copy()
    core = positive.loc[positive["fbs_import_tonnes"].ge(MIN_FBS_TONNES_CORE)].copy()

    def calc(scope: pd.DataFrame, prefix: str) -> dict:
        if scope.empty:
            return {
                f"{prefix}_rows": 0,
                f"{prefix}_sum_ratio": None,
                f"{prefix}_weighted_median_ratio": None,
                f"{prefix}_geometric_median_ratio": None,
                f"{prefix}_median_ape": None,
                f"{prefix}_weighted_ape": None,
                f"{prefix}_within_0_80_1_25_share": None,
            }
        ratio = scope["bilateral_import_tonnes"] / scope["fbs_import_tonnes"]
        ape = (
            scope["bilateral_import_tonnes"] - scope["fbs_import_tonnes"]
        ).abs() / scope["fbs_import_tonnes"]
        sum_ratio = (
            scope["bilateral_import_tonnes"].sum() / scope["fbs_import_tonnes"].sum()
        )
        geometric_median = float(
            np.exp(np.median(np.log(ratio.clip(lower=RATIO_FLOOR))))
        )
        return {
            f"{prefix}_rows": len(scope),
            f"{prefix}_sum_ratio": float(sum_ratio),
            f"{prefix}_weighted_median_ratio": weighted_median(
                ratio, scope["fbs_import_tonnes"]
            ),
            f"{prefix}_geometric_median_ratio": geometric_median,
            f"{prefix}_median_ape": float(ape.median()),
            f"{prefix}_weighted_ape": float(
                (ape * scope["fbs_import_tonnes"]).sum()
                / scope["fbs_import_tonnes"].sum()
            ),
            f"{prefix}_within_0_80_1_25_share": float(ratio.between(0.80, 1.25).mean()),
        }

    result = {
        "trade_rows": len(frame),
        "matched_fbs_rows": len(matched),
        "positive_fbs_rows": len(positive),
        "core_material_rows": len(core),
        "missing_fbs_rows": int(frame["fbs_import_tonnes"].isna().sum()),
        "zero_fbs_rows": int(frame["fbs_import_tonnes"].eq(0).sum()),
        "match_coverage": float(len(matched) / len(frame)) if len(frame) else None,
        "positive_denominator_coverage": float(len(positive) / len(frame))
        if len(frame)
        else None,
    }
    result.update(calc(positive, "all_positive"))
    result.update(calc(core, "core_material"))
    return result


def classify(row: pd.Series) -> str:
    role = row["inclusion_role"]
    if role in {
        "partial_proxy",
        "supplementary_component",
        "alternative_variant",
        "alternative_or_bundle_test",
    }:
        return "INCLUDE_WITH_DEFINED_ROLE"
    if (
        row["core_material_rows"] >= 100
        and 0.80 <= row["core_material_sum_ratio"] <= 1.25
        and row["core_material_weighted_ape"] <= 0.30
    ):
        return "DENOMINATOR_ALIGNED"
    return "INCLUDE_AS_PARTIAL_OR_EXPANSION_CANDIDATE"


def main() -> None:
    if not PANEL.exists() or not SEED.exists():
        raise FileNotFoundError("Required Tier 1 panel or seed is missing")

    panel = pd.read_csv(PANEL)
    seed = pd.read_csv(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    component_rows = []
    for item_code, group in panel.groupby("trade_item_code", sort=True):
        seed_row = seed.loc[seed["trade_item_code"].eq(item_code)].iloc[0]
        role, family, note = ROLE_OVERRIDES.get(
            int(item_code),
            (
                "standalone_candidate",
                str(seed_row["overlap_group"]),
                "Evaluate as a standalone mapped component.",
            ),
        )
        row = {
            "trade_item_code": int(item_code),
            "trade_item": group["trade_item"].iloc[0],
            "fbs_item_code": int(group["fbs_item_code"].iloc[0]),
            "fbs_item": group["fbs_item"].iloc[0],
            "inclusion_role": role,
            "food_family": family,
            "interpretation_note": note,
        }
        row.update(metrics(group))
        component_rows.append(row)

    components = pd.DataFrame(component_rows)
    components["v2_status"] = components.apply(classify, axis=1)
    components.to_csv(COMPONENT_OUT, index=False)

    bundle_rows = []
    for bundle_name, item_codes in BUNDLES.items():
        selected = panel.loc[panel["trade_item_code"].isin(item_codes)].copy()
        if selected.empty:
            continue
        # FBS denominator appears once per importer-year; bilateral numerators are summed.
        grouped = selected.groupby(
            [
                "fbs_item_code",
                "fbs_item",
                "importer_code",
                "importer_m49",
                "importer",
                "year",
            ],
            dropna=False,
            as_index=False,
        ).agg(
            bilateral_import_tonnes=("bilateral_import_tonnes", "sum"),
            fbs_import_tonnes=("fbs_import_tonnes", "first"),
        )
        row = {
            "bundle_name": bundle_name,
            "trade_item_codes": ";".join(map(str, item_codes)),
            "trade_items": "; ".join(
                seed.loc[seed["trade_item_code"].isin(item_codes), "trade_item"].astype(
                    str
                )
            ),
            "fbs_item_code": int(grouped["fbs_item_code"].iloc[0]),
            "fbs_item": grouped["fbs_item"].iloc[0],
            "bundle_type": "sensitivity_only"
            if "sensitivity" in bundle_name
            else "candidate_variant",
        }
        row.update(metrics(grouped))
        bundle_rows.append(row)

    bundles = pd.DataFrame(bundle_rows)
    bundles.to_csv(GROUP_OUT, index=False)

    decisions = components[
        [
            "trade_item_code",
            "trade_item",
            "fbs_item_code",
            "fbs_item",
            "inclusion_role",
            "food_family",
            "v2_status",
            "interpretation_note",
        ]
    ].copy()
    decisions["included_in_framework"] = True
    decisions["included_as_independent_denominator_aligned_food"] = decisions[
        "v2_status"
    ].eq("DENOMINATOR_ALIGNED")
    decisions.to_csv(DECISION_OUT, index=False)

    report = {
        "framework": "All 27 items retained with explicit analytical roles",
        "core_materiality_threshold_fbs_tonnes": MIN_FBS_TONNES_CORE,
        "component_count": len(components),
        "all_components_included_in_framework": bool(
            decisions["included_in_framework"].all()
        ),
        "role_counts": {
            str(k): int(v)
            for k, v in components["inclusion_role"].value_counts().items()
        },
        "status_counts": {
            str(k): int(v) for k, v in components["v2_status"].value_counts().items()
        },
        "metric_policy": {
            "all_positive": "All country-years with Food Balance imports greater than zero",
            "core_material": f"Country-years with Food Balance imports at least {MIN_FBS_TONNES_CORE:,.0f} tonnes",
            "sum_ratio": "Sum of bilateral imports divided by sum of Food Balance imports",
            "weighted_median_ratio": "Median reconciliation ratio weighted by Food Balance import tonnes",
            "geometric_median_ratio": "Exponentiated median log ratio, symmetric around 1",
            "weighted_ape": "Absolute percentage error weighted by Food Balance import tonnes",
        },
        "zero_and_missing_policy": "Retained as coverage diagnostics; excluded from ratio metrics",
        "outputs": {
            "component_metrics": str(COMPONENT_OUT.relative_to(ROOT)),
            "bundle_metrics": str(GROUP_OUT.relative_to(ROOT)),
            "inclusion_roles": str(DECISION_OUT.relative_to(ROOT)),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("ALL-27 RECONCILIATION REASSESSMENT COMPLETE")
    print("=" * 72)
    print(f"Components retained: {len(components)}")
    print("\nRoles:")
    print(components["inclusion_role"].value_counts().to_string())
    print("\nV2 statuses:")
    print(components["v2_status"].value_counts().to_string())
    print("\nBundle tests:")
    print(
        bundles[
            [
                "bundle_name",
                "core_material_sum_ratio",
                "core_material_weighted_median_ratio",
                "core_material_weighted_ape",
            ]
        ].to_string(index=False)
    )
    print(f"\nReport: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

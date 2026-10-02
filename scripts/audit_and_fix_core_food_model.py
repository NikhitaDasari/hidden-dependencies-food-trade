from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = (
    ROOT
    / "outputs/tables/crosswalk_discovery/food_crosswalk_tier1_reconciliation_seed.csv"
)
PANEL = ROOT / "outputs/tables/reconciliation/tier1_country_year_reconciliation.csv"
V2_METRICS = ROOT / "outputs/tables/reconciliation_v2/all_27_component_metrics.csv"
OUT = ROOT / "outputs/tables/core_food_model"
REPORT = ROOT / "outputs/model_results/core_food_model_audit.json"

FAMILIES = {
    "CF01": ("Wheat", [15, 16], 2511, "equivalent_required", "expanded_family"),
    "CF02": ("Maize", [56], 2514, "native_tonnes", "category_candidate"),
    "CF03": ("Rice", [30, 31], 2807, "overlap_review", "sensitivity_only"),
    "CF04": ("Barley", [44], 2513, "native_tonnes", "category_candidate"),
    "CF05": ("Sorghum", [83], 2518, "native_tonnes", "category_candidate"),
    "CF06": (
        "Sugar",
        [162, 164],
        2542,
        "raw_equivalent_required",
        "combined_candidate",
    ),
    "CF07": ("Potatoes", [116, 118], 2531, "equivalent_required", "expanded_family"),
    "CF08": ("Soybean", [236, 237], 2555, "do_not_sum_native_tonnes", "multi_channel"),
    "CF09": (
        "Rapeseed and mustard",
        [270, 271],
        2558,
        "do_not_sum_native_tonnes",
        "multi_channel",
    ),
    "CF10": ("Palm oil", [257], 2577, "native_tonnes", "category_candidate"),
    "CF11": ("Sunflower oil", [268], 2573, "native_tonnes", "category_candidate"),
    "CF12": ("Bananas", [486], 2615, "native_tonnes", "category_candidate"),
    "CF13": ("Apples", [515], 2617, "partial_family", "expansion_required"),
    "CF14": ("Onions", [403], 2602, "native_tonnes", "category_candidate"),
    "CF15": ("Tomatoes", [388], 2601, "partial_family", "product_channel"),
    "CF16": ("Cassava", [128], 2532, "equivalent_required", "product_channel"),
    "CF17": ("Coffee", [656], 2630, "partial_family", "product_channel"),
    "CF18": ("Poultry meat", [1058], 2734, "partial_family", "product_channel"),
    "CF19": ("Bovine meat", [870], 2731, "partial_family", "product_channel"),
    "CF20": (
        "Milk excluding butter",
        [882],
        2848,
        "milk_equivalent_required",
        "product_channel",
    ),
    "CF21": ("Eggs", [1062], 2744, "egg_equivalent_review", "data_review"),
}

CANONICAL_ALIASES = {2949: 2744, 2948: 2848}


def require(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)


def issue(issue_id: str, severity: str, status: str, title: str, fix: str) -> dict:
    return {
        "issue_id": issue_id,
        "severity": severity,
        "status": status,
        "issue": title,
        "implemented_fix_or_required_action": fix,
    }


def main() -> None:
    for path in [SEED, PANEL, V2_METRICS]:
        require(path)

    seed = pd.read_csv(SEED)
    metrics = pd.read_csv(V2_METRICS)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    if len(seed) != 27 or seed["trade_item_code"].duplicated().any():
        raise ValueError("The 27-item reconciliation seed is not structurally valid")

    registry_rows = []
    mapped_codes: list[int] = []
    for family_code, (
        name,
        item_codes,
        fbs_code,
        quantity_policy,
        usage,
    ) in FAMILIES.items():
        matches = seed.loc[seed["trade_item_code"].isin(item_codes)].copy()
        found = sorted(matches["trade_item_code"].astype(int).tolist())
        if found != sorted(item_codes):
            raise ValueError(f"{family_code} expected {item_codes}, found {found}")
        mapped_codes.extend(found)
        registry_rows.append(
            {
                "core_food_code": family_code,
                "core_food": name,
                "trade_item_codes": ";".join(map(str, item_codes)),
                "trade_items": "; ".join(matches["trade_item"].astype(str)),
                "canonical_fbs_item_code": fbs_code,
                "canonical_fbs_item": matches.loc[
                    matches["proposed_fbs_item_code"].astype(int).eq(fbs_code),
                    "proposed_fbs_item",
                ].iloc[0]
                if matches["proposed_fbs_item_code"].astype(int).eq(fbs_code).any()
                else "",
                "quantity_aggregation_policy": quantity_policy,
                "current_model_usage": usage,
                "included_in_framework": True,
                "technical_family_candidate": (
                    quantity_policy == "native_tonnes" and usage == "category_candidate"
                ),
                "final_gold_ready": False,
                "remaining_gold_gates": (
                    "COUNTRY_ELIGIBILITY|NETWORK_COVERAGE|CONFIDENCE|FINAL_QA"
                ),
            }
        )

    if sorted(mapped_codes) != sorted(seed["trade_item_code"].astype(int).tolist()):
        raise ValueError(
            "The family registry does not cover each of the 27 trade items exactly once"
        )

    registry = pd.DataFrame(registry_rows)
    registry.to_csv(OUT / "core_food_registry.csv", index=False)

    channel = seed.copy()
    family_lookup = {
        item: (code, name, policy, usage)
        for code, (name, items, _, policy, usage) in FAMILIES.items()
        for item in items
    }
    channel[
        [
            "core_food_code",
            "core_food",
            "quantity_aggregation_policy",
            "current_model_usage",
        ]
    ] = channel["trade_item_code"].apply(
        lambda value: pd.Series(family_lookup[int(value)])
    )
    channel["conversion_factor_low"] = pd.NA
    channel["conversion_factor_central"] = pd.NA
    channel["conversion_factor_high"] = pd.NA
    channel["conversion_factor_source"] = ""
    channel["conversion_status"] = channel["quantity_aggregation_policy"].map(
        lambda value: (
            "not_required"
            if value == "native_tonnes"
            else "required_before_equivalent_aggregation"
        )
    )
    channel["may_sum_reported_tonnes_within_family"] = channel[
        "quantity_aggregation_policy"
    ].isin(["native_tonnes"])
    channel.to_csv(OUT / "core_food_product_channels.csv", index=False)

    metric_columns = [
        "trade_item_code",
        "core_material_sum_ratio",
        "core_material_weighted_median_ratio",
        "core_material_geometric_median_ratio",
        "core_material_weighted_ape",
        "core_material_within_0_80_1_25_share",
        "v2_status",
    ]
    readiness = channel.merge(
        metrics[metric_columns], on="trade_item_code", how="left", validate="one_to_one"
    )
    readiness["vulnerability_usage"] = "product_channel_only"
    readiness.loc[
        readiness["quantity_aggregation_policy"].eq("native_tonnes"),
        "vulnerability_usage",
    ] = "core_food_family_candidate"
    readiness.loc[
        readiness["quantity_aggregation_policy"].eq("overlap_review"),
        "vulnerability_usage",
    ] = "sensitivity_only_until_overlap_resolved"
    readiness.loc[
        readiness["quantity_aggregation_policy"].eq("do_not_sum_native_tonnes"),
        "vulnerability_usage",
    ] = "separate_channels_until_equivalent_conversion"
    readiness.to_csv(OUT / "core_food_readiness.csv", index=False)

    problems = [
        issue(
            "CF-001",
            "critical",
            "fixed_in_registry",
            "Raw and processed product tonnes could be summed without equivalence conversion.",
            "Registry blocks native-tonne summation for wheat, potatoes, cassava, milk, soybean, rapeseed, eggs, and other transformed products.",
        ),
        issue(
            "CF-002",
            "critical",
            "fixed_in_design",
            "Bilateral trade totals could be used as national import dependence.",
            "Use FBS Import quantity / FBS Domestic supply quantity for import reliance; use bilateral trade only for supplier allocation.",
        ),
        issue(
            "CF-003",
            "high",
            "open",
            "Country eligibility and aggregate/territory handling are not finalized.",
            "Build a 200-entity eligibility crosswalk; exclude aggregates and document territories before final rankings.",
        ),
        issue(
            "CF-004",
            "high",
            "fixed_in_design",
            "HHI and top-supplier share could be double-weighted in one score.",
            "Use HHI as concentration; report Top1 and Top3 as scenarios and explanatory diagnostics.",
        ),
        issue(
            "CF-005",
            "high",
            "open",
            "Equivalent conversion factors are not sourced.",
            "Populate low, central, and high conversion factors with authoritative sources before equivalent-family aggregation.",
        ),
        issue(
            "CF-006",
            "high",
            "open",
            "Rice paddy-equivalent and milled rice may overlap.",
            "Keep combined rice as sensitivity-only until source definitions establish non-overlap.",
        ),
        issue(
            "CF-007",
            "high",
            "open",
            "Egg trade/FBS relationship is anomalous.",
            "Retain eggs as data-review channel; inspect largest country-year discrepancies before scoring.",
        ),
        issue(
            "CF-008",
            "medium",
            "fixed_in_design",
            "Unweighted medians overemphasized tiny import denominators.",
            "Use aggregate-sum ratio, FBS-volume-weighted median, geometric median, WAPE, and a materiality threshold.",
        ),
        issue(
            "CF-009",
            "medium",
            "open",
            "The current panel contains FBS-zero and missing-FBS observations.",
            "Keep separate statuses; never compute ratios on zero/missing denominators; decide eligibility through country crosswalk.",
        ),
        issue(
            "CF-010",
            "medium",
            "fixed_in_design",
            "Tonnes across foods could be misused as food-security materiality.",
            "Use FBS calorie, protein, and fat contributions; do not compare cross-food importance using tonnes.",
        ),
        issue(
            "CF-011",
            "medium",
            "open",
            "Immediate exporter is not necessarily agricultural origin.",
            "Label network as immediate supplier-channel exposure; do not infer farm origin without origin-tracing data.",
        ),
        issue(
            "CF-012",
            "medium",
            "open",
            "Single-year metrics can be volatile.",
            "Use pooled 2021-2023 baseline for structural rankings and annual series for trend alerts.",
        ),
        issue(
            "CF-013",
            "medium",
            "open",
            "Trade flags and FBS flags are not yet reflected in confidence.",
            "Build a confidence score separately from vulnerability using coverage, flags, conversion certainty, overlap, and reconciliation.",
        ),
        issue(
            "CF-014",
            "medium",
            "open",
            "Supplier shares may be distorted by de minimis flows.",
            "Report all-supplier HHI and a material-supplier view using explicit share/tonnage thresholds with sensitivity tests.",
        ),
        issue(
            "CF-015",
            "medium",
            "open",
            "No resilience or substitutability layer exists yet.",
            "Add alternative exporter capacity and historical supplier-switching as a separate resilience dimension after structural vulnerability is stable.",
        ),
    ]
    issue_df = pd.DataFrame(problems)
    issue_df.to_csv(OUT / "core_food_issue_register.csv", index=False)

    vulnerability_spec = {
        "unit_of_analysis": "country x core_food x baseline_period",
        "structural_baseline": "pooled 2021-2023",
        "annual_monitoring": True,
        "import_reliance": {
            "numerator": "FBS Import quantity (element 5611, converted from 1000 t to t)",
            "denominator": "FBS Domestic supply quantity (element 5301, converted from 1000 t to t)",
            "raw_formula": "fbs_import_tonnes / fbs_domestic_supply_tonnes",
            "scoring_formula": "min(max(raw_formula, 0), 1)",
            "values_above_one": "retain raw; flag for re-export, stock, or classification review",
        },
        "supplier_network": {
            "source": "importer-reported detailed trade matrix",
            "share_formula": "supplier_family_equivalent_tonnes / total_family_equivalent_tonnes",
            "hhi": "sum(supplier_share^2)",
            "effective_suppliers": "1 / hhi",
            "top1_share": "largest supplier share",
            "top3_share": "sum of three largest supplier shares",
            "origin_caution": "reported exporter is immediate supplier, not proven agricultural origin",
        },
        "shock_scenarios": {
            "top1_loss_exposure": "import_reliance_capped * top1_share",
            "top3_loss_exposure": "import_reliance_capped * top3_share",
            "supplier_specific_loss": "import_reliance_capped * sum(supplier_share * shock_severity)",
        },
        "materiality": {
            "primary": "share of national food-supply calories",
            "secondary": ["share of protein supply", "share of fat supply"],
            "prohibited": "cross-food materiality based on tonnes",
        },
        "confidence": {
            "separate_from_vulnerability": True,
            "inputs": [
                "country coverage",
                "FBS/trade reconciliation",
                "conversion-factor certainty",
                "overlap status",
                "trade and FBS flags",
                "time stability",
            ],
        },
        "composite_score_policy": "Do not publish an opaque weighted score until component distributions and sensitivity tests are complete. Publish import reliance, HHI, Top1-loss exposure, materiality, and confidence first.",
    }
    (OUT / "vulnerability_model_spec.json").write_text(
        json.dumps(vulnerability_spec, indent=2) + "\n", encoding="utf-8"
    )

    report = {
        "core_food_count": len(registry),
        "trade_product_count": len(seed),
        "all_27_mapped_exactly_once": True,
        "canonical_aliases": CANONICAL_ALIASES,
        "technical_family_candidates": registry.loc[
            registry["technical_family_candidate"], "core_food"
        ].tolist(),
        "issue_counts": {
            str(k): int(v) for k, v in issue_df["severity"].value_counts().items()
        },
        "open_issue_count": int(issue_df["status"].eq("open").sum()),
        "implemented_or_fixed_issue_count": int(issue_df["status"].ne("open").sum()),
        "outputs": {
            "registry": str((OUT / "core_food_registry.csv").relative_to(ROOT)),
            "channels": str((OUT / "core_food_product_channels.csv").relative_to(ROOT)),
            "readiness": str((OUT / "core_food_readiness.csv").relative_to(ROOT)),
            "issues": str((OUT / "core_food_issue_register.csv").relative_to(ROOT)),
            "vulnerability_spec": str(
                (OUT / "vulnerability_model_spec.json").relative_to(ROOT)
            ),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD MODEL AUDIT AND FIXES COMPLETE")
    print("=" * 72)
    print(f"Core Foods: {len(registry)}")
    print(f"Trade products mapped exactly once: {len(seed)}")
    print(f"Open issues: {report['open_issue_count']}")
    print(f"Implemented/fixed controls: {report['implemented_or_fixed_issue_count']}")
    print("\nTechnical family candidates:")
    for name in report["technical_family_candidates"]:
        print(f"- {name}")
    print(f"\nReport: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

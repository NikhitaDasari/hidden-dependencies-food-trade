from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/model_governance/core_food_chokepoint_policy.json"
MODEL_POLICY_PATH = ROOT / "config/model_governance/core_food_model_specification.json"
NETWORK_ANNUAL = (
    ROOT
    / "outputs/tables/core_food_supplier_network/core_food_supplier_network_annual.csv"
)
PANEL_PATH = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_country_food_year_panel.csv"
)
PRIMARY_FEATURES = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_primary_feature_dataset.csv"
)
LIMITED_FEATURES = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_limited_feature_dataset.csv"
)
STABILITY_PATH = (
    ROOT / "outputs/tables/core_food_model_specification/core_food_band_stability.csv"
)
SCENARIOS_PATH = (
    ROOT / "outputs/tables/core_food_model_specification/core_food_scenario_results.csv"
)
OUT = ROOT / "outputs/tables/core_food_supplier_chokepoints"
REPORT = ROOT / "outputs/model_results/core_food_supplier_chokepoints_summary.json"

RELATIONSHIPS_PATH = OUT / "core_food_importer_supplier_relationships.csv"
FEATURES_PATH = OUT / "core_food_supplier_food_systemic_features.csv"
PRIMARY_PATH = OUT / "core_food_supplier_food_primary_candidates.csv"
EXPANDED_PATH = OUT / "core_food_supplier_food_expanded_candidates.csv"
SCENARIO_PATH = OUT / "core_food_supplier_food_scenario_results.csv"
SYSTEMIC_STABILITY_PATH = OUT / "core_food_supplier_food_stability.csv"
REMOVAL_PATH = OUT / "core_food_supplier_removal_stress_tests.csv"
REMOVAL_SUMMARY_PATH = OUT / "core_food_supplier_removal_summary.csv"
COMPLETENESS_PATH = OUT / "core_food_chokepoint_completeness.csv"
REVIEW_PATH = OUT / "core_food_chokepoint_review.csv"

IMPORTER_KEY = ["importer_m49", "analytical_scope_code"]
RELATIONSHIP_KEY = ["importer_m49", "exporter_m49", "analytical_scope_code"]
ANNUAL_KEY = RELATIONSHIP_KEY + ["year"]
SUPPLIER_FOOD_KEY = ["exporter_m49", "analytical_scope_code"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalize_m49(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(3)
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True)


def validate_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required - set(frame.columns)
    require(not missing, f"{name} columns missing: {sorted(missing)}")


def period_relationships(annual: pd.DataFrame, thresholds: list[float]) -> pd.DataFrame:
    ordered = annual.sort_values(ANNUAL_KEY)
    first_latest = ordered.groupby(RELATIONSHIP_KEY, as_index=False).agg(
        first_supplier_share=("supplier_share", "first"),
        latest_supplier_share=("supplier_share", "last"),
    )
    grouped = ordered.groupby(RELATIONSHIP_KEY, as_index=False).agg(
        importer_name=("importer_name_trade", "first"),
        exporter_name=("exporter_name_trade", "first"),
        core_food_code=("core_food_code", "first"),
        core_food=("core_food", "first"),
        years_relationship_observed=("year", "nunique"),
        first_year_observed=("year", "min"),
        latest_year_observed=("year", "max"),
        total_observed_import_quantity_tonnes=(
            "observed_import_quantity_tonnes",
            "sum",
        ),
        mean_annual_import_quantity_tonnes=("observed_import_quantity_tonnes", "mean"),
        pooled_supplier_share_numerator=("observed_import_quantity_tonnes", "sum"),
        mean_supplier_share=("supplier_share", "mean"),
        maximum_supplier_share=("supplier_share", "max"),
        minimum_supplier_share=("supplier_share", "min"),
    )
    period_denominator = (
        ordered[
            [
                "importer_m49",
                "analytical_scope_code",
                "year",
                "annual_network_total_tonnes",
            ]
        ]
        .drop_duplicates(
            [
                "importer_m49",
                "analytical_scope_code",
                "year",
            ]
        )
        .groupby(
            [
                "importer_m49",
                "analytical_scope_code",
            ],
            as_index=False,
        )
        .agg(
            pooled_supplier_share_denominator=(
                "annual_network_total_tonnes",
                "sum",
            )
        )
    )

    grouped = grouped.merge(
        period_denominator,
        on=[
            "importer_m49",
            "analytical_scope_code",
        ],
        how="left",
        validate="many_to_one",
    )

    require(
        grouped["pooled_supplier_share_denominator"].gt(0).all(),
        "Period importer-food denominator is missing or nonpositive",
    )

    grouped["pooled_supplier_share"] = (
        grouped["pooled_supplier_share_numerator"]
        / grouped["pooled_supplier_share_denominator"]
    )

    grouped["relationship_persistence_rate"] = (
        grouped["years_relationship_observed"] / 3
    )
    grouped = grouped.merge(first_latest, on=RELATIONSHIP_KEY, how="left")
    grouped["supplier_share_first_to_latest_change"] = (
        grouped["latest_supplier_share"] - grouped["first_supplier_share"]
    )
    for threshold in thresholds:
        label = str(int(threshold * 100)).zfill(2)
        counts = (
            ordered.loc[ordered["supplier_share"].ge(threshold)]
            .groupby(RELATIONSHIP_KEY)
            .size()
            .rename(f"relationship_years_share_ge_{label}pct")
            .reset_index()
        )
        grouped = grouped.merge(counts, on=RELATIONSHIP_KEY, how="left")
        grouped[f"relationship_years_share_ge_{label}pct"] = (
            grouped[f"relationship_years_share_ge_{label}pct"].fillna(0).astype(int)
        )
    return grouped


def attach_population(
    relationships: pd.DataFrame,
    population: pd.DataFrame,
    name: str,
    stability: pd.DataFrame,
    policy: dict[str, Any],
) -> pd.DataFrame:
    importer = population.rename(columns={"entity_m49": "importer_m49"}).copy()
    keep = [
        "importer_m49",
        "analytical_scope_code",
        "model_readiness_status",
        "evidence_confidence",
        "effective_supplier_count_period_average",
    ]
    result = relationships.merge(importer[keep], on=IMPORTER_KEY, how="inner")
    stability_importer = stability.rename(columns={"entity_m49": "importer_m49"})
    stability_keep = [
        "importer_m49",
        "analytical_scope_code",
        "stability_band",
        "scenarios_available",
        "high_share",
        "average_development_percentile",
        "minimum_development_percentile",
        "maximum_development_percentile",
    ]
    result = result.merge(
        stability_importer[stability_keep], on=IMPORTER_KEY, how="left"
    )
    result["analysis_population"] = name
    result["vulnerability_band_weight"] = result["stability_band"].map(
        policy["vulnerability_band_weights"]
    )
    result["elevated_signal_importer"] = result["stability_band"].isin(
        ["CONSISTENTLY_HIGH", "OFTEN_HIGH"]
    )
    result["supplier_dependence_exposure"] = (
        result["pooled_supplier_share"] * result["vulnerability_band_weight"]
    )
    result["continuous_dependence_exposure"] = (
        result["pooled_supplier_share"] * result["average_development_percentile"]
    )
    result["vulnerability_weighted_trade_tonnes"] = (
        result["total_observed_import_quantity_tonnes"]
        * result["vulnerability_band_weight"]
    )
    result["low_substitutability_relationship"] = result["pooled_supplier_share"].ge(
        policy["low_substitutability_share_threshold"]
    ) & result["effective_supplier_count_period_average"].le(
        policy["low_substitutability_effective_supplier_threshold"]
    )
    result["supplier_relationship_type"] = "IMMEDIATE_TRADE_PARTNER"
    result["agricultural_origin_known"] = False
    result["origin_inference_prohibited"] = True
    result["official_supplier_ranking_enabled"] = False
    return result


def supplier_features(
    relationships: pd.DataFrame, policy: dict[str, Any]
) -> pd.DataFrame:
    grouped = relationships.groupby(
        SUPPLIER_FOOD_KEY + ["analysis_population"], as_index=False
    ).agg(
        exporter_name=("exporter_name", "first"),
        core_food_code=("core_food_code", "first"),
        core_food=("core_food", "first"),
        importer_count=("importer_m49", "nunique"),
        elevated_signal_importer_count=("elevated_signal_importer", "sum"),
        consistently_high_importer_count=(
            "stability_band",
            lambda x: int((x == "CONSISTENTLY_HIGH").sum()),
        ),
        often_high_importer_count=(
            "stability_band",
            lambda x: int((x == "OFTEN_HIGH").sum()),
        ),
        total_observed_import_quantity_tonnes=(
            "total_observed_import_quantity_tonnes",
            "sum",
        ),
        mean_pooled_supplier_share=("pooled_supplier_share", "mean"),
        maximum_pooled_supplier_share=("pooled_supplier_share", "max"),
        majority_share_importer_count=(
            "pooled_supplier_share",
            lambda x: int((x >= 0.50).sum()),
        ),
        quarter_share_importer_count=(
            "pooled_supplier_share",
            lambda x: int((x >= 0.25).sum()),
        ),
        material_importer_count=(
            "pooled_supplier_share",
            lambda x: int((x >= 0.01).sum()),
        ),
        persistent_relationship_count=(
            "years_relationship_observed",
            lambda x: int(
                (x >= policy["minimum_relationship_years_for_persistence"]).sum()
            ),
        ),
        low_substitutability_importer_count=(
            "low_substitutability_relationship",
            "sum",
        ),
        vulnerability_weighted_importer_count=("vulnerability_band_weight", "sum"),
        supplier_food_weighted_reach=("supplier_dependence_exposure", "sum"),
        continuous_supplier_food_weighted_reach=(
            "continuous_dependence_exposure",
            "sum",
        ),
        vulnerability_weighted_trade_tonnes=(
            "vulnerability_weighted_trade_tonnes",
            "sum",
        ),
        mean_relationship_persistence=("relationship_persistence_rate", "mean"),
        maximum_relationship_persistence=("relationship_persistence_rate", "max"),
    )
    grouped["elevated_importer_share"] = (
        grouped["elevated_signal_importer_count"] / grouped["importer_count"]
    )
    grouped["persistent_relationship_share"] = (
        grouped["persistent_relationship_count"] / grouped["importer_count"]
    )
    grouped["systemic_reach_percentile"] = grouped.groupby(
        ["analysis_population", "analytical_scope_code"]
    )["supplier_food_weighted_reach"].transform(percentile)
    grouped["breadth_percentile"] = grouped.groupby(
        ["analysis_population", "analytical_scope_code"]
    )["importer_count"].transform(percentile)
    grouped["dependence_percentile"] = grouped.groupby(
        ["analysis_population", "analytical_scope_code"]
    )["maximum_pooled_supplier_share"].transform(percentile)
    grouped["developmental_chokepoint_class"] = "LIMITED_OR_LOCALIZED_REACH"
    broad = grouped["systemic_reach_percentile"].ge(0.80) & grouped[
        "breadth_percentile"
    ].ge(0.80)
    concentrated = grouped["systemic_reach_percentile"].ge(0.80) & grouped[
        "dependence_percentile"
    ].ge(0.80)
    persistent = grouped["systemic_reach_percentile"].ge(0.80) & grouped[
        "persistent_relationship_share"
    ].ge(2 / 3)
    grouped.loc[broad, "developmental_chokepoint_class"] = "BROAD_SYSTEMIC_REACH"
    grouped.loc[concentrated & ~broad, "developmental_chokepoint_class"] = (
        "CONCENTRATED_HIGH_DEPENDENCE"
    )
    grouped.loc[
        persistent & ~broad & ~concentrated, "developmental_chokepoint_class"
    ] = "PERSISTENT_ELEVATED_REACH"
    grouped["result_classification"] = policy["result_classification"]
    grouped["official_supplier_ranking_enabled"] = False
    return grouped


def scenario_results(
    annual: pd.DataFrame,
    scenarios: pd.DataFrame,
    primary: pd.DataFrame,
) -> pd.DataFrame:
    allowed = scenarios.loc[
        scenarios["analysis_population"].eq("PRIMARY_ONLY")
        & scenarios["transformation"].eq("WITHIN_SCOPE_PERCENTILE")
        & scenarios["scenario_complete"].astype(bool)
    ].copy()
    allowed = allowed.rename(columns={"entity_m49": "importer_m49"})
    base = annual.merge(
        primary.rename(columns={"entity_m49": "importer_m49"})[IMPORTER_KEY],
        on=IMPORTER_KEY,
        how="inner",
    )
    base = base.merge(
        allowed[IMPORTER_KEY + ["scenario_id", "development_percentile"]],
        on=IMPORTER_KEY,
        how="inner",
    )
    base["relationship_scenario_exposure"] = (
        base["supplier_share"] * base["development_percentile"]
    )
    result = base.groupby(SUPPLIER_FOOD_KEY + ["scenario_id"], as_index=False).agg(
        exporter_name=("exporter_name_trade", "first"),
        core_food_code=("core_food_code", "first"),
        core_food=("core_food", "first"),
        importer_count=("importer_m49", "nunique"),
        scenario_weighted_reach=("relationship_scenario_exposure", "sum"),
        scenario_weighted_trade_tonnes=(
            "observed_import_quantity_tonnes",
            lambda x: float(x.sum()),
        ),
    )
    result["systemic_percentile"] = result.groupby(
        ["analytical_scope_code", "scenario_id"]
    )["scenario_weighted_reach"].transform(percentile)
    result["high_systemic_signal"] = result["systemic_percentile"].ge(0.80)
    result["result_classification"] = "DEVELOPMENTAL_SYSTEMIC_SIGNAL"
    result["official_supplier_ranking_enabled"] = False
    return result


def stability_features(scenarios: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    result = scenarios.groupby(SUPPLIER_FOOD_KEY, as_index=False).agg(
        exporter_name=("exporter_name", "first"),
        core_food_code=("core_food_code", "first"),
        core_food=("core_food", "first"),
        scenarios_available=("scenario_id", "nunique"),
        high_systemic_signal_scenario_count=("high_systemic_signal", "sum"),
        minimum_systemic_percentile=("systemic_percentile", "min"),
        average_systemic_percentile=("systemic_percentile", "mean"),
        maximum_systemic_percentile=("systemic_percentile", "max"),
    )
    result["high_systemic_signal_share"] = (
        result["high_systemic_signal_scenario_count"] / result["scenarios_available"]
    )
    result["systemic_percentile_range"] = (
        result["maximum_systemic_percentile"] - result["minimum_systemic_percentile"]
    )
    result["systemic_stability_band"] = "MIXED_SYSTEMIC_SIGNAL"
    result.loc[
        result["high_systemic_signal_share"].eq(1), "systemic_stability_band"
    ] = "CONSISTENT_SYSTEMIC_SIGNAL"
    result.loc[
        result["high_systemic_signal_share"].ge(0.5)
        & result["high_systemic_signal_share"].lt(1),
        "systemic_stability_band",
    ] = "OFTEN_SYSTEMIC_SIGNAL"
    result.loc[
        result["high_systemic_signal_share"].eq(0)
        & result["average_systemic_percentile"].le(policy["systemic_low_percentile"]),
        "systemic_stability_band",
    ] = "CONSISTENTLY_LOCALIZED"
    result.loc[
        result["high_systemic_signal_share"].eq(0)
        & result["average_systemic_percentile"].gt(policy["systemic_low_percentile"]),
        "systemic_stability_band",
    ] = "OFTEN_LOCALIZED"
    result["result_classification"] = policy["result_classification"]
    result["official_supplier_ranking_enabled"] = False
    return result


def removal_tests(annual: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    importer = panel.rename(columns={"entity_m49": "importer_m49"})
    network_fields = [
        "importer_m49",
        "analytical_scope_code",
        "year",
        "supplier_count",
        "effective_supplier_count",
    ]
    result = annual.merge(
        importer[network_fields], on=IMPORTER_KEY + ["year"], how="left"
    )
    result["removed_supplier_share"] = result["supplier_share"]
    result["remaining_observed_share"] = 1 - result["removed_supplier_share"]
    result["remaining_supplier_count"] = result["supplier_count"] - 1
    result["no_remaining_observed_supplier"] = result["remaining_supplier_count"].eq(0)
    result["high_dependence_removal_flag"] = result["removed_supplier_share"].ge(0.25)
    result["dynamic_substitution_modeled"] = False
    result["stress_test_interpretation"] = "STATIC_REMOVAL_NO_SUBSTITUTION"
    return result


def main() -> None:
    inputs = [
        POLICY_PATH,
        MODEL_POLICY_PATH,
        NETWORK_ANNUAL,
        PANEL_PATH,
        PRIMARY_FEATURES,
        LIMITED_FEATURES,
        STABILITY_PATH,
        SCENARIOS_PATH,
    ]
    for path in inputs:
        require(path.exists(), f"Required input missing: {path}")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    model_policy = json.loads(MODEL_POLICY_PATH.read_text(encoding="utf-8"))
    require(
        model_policy["policy_id"] == policy["input_model_policy_id"],
        "Model policy contract changed",
    )
    require(
        policy["agricultural_origin_inference_allowed"] is False,
        "Origin inference enabled",
    )
    require(
        policy["supplier_causality_claims_allowed"] is False,
        "Supplier causality enabled",
    )
    require(
        policy["dynamic_substitution_modeled"] is False, "Dynamic substitution enabled"
    )
    require(
        policy["evidence_confidence_in_systemic_weighting"] is False,
        "Evidence confidence entered weighting",
    )
    require(
        policy["official_chokepoint_score_enabled"] is False, "Official score enabled"
    )
    require(
        policy["official_supplier_ranking_enabled"] is False, "Official ranking enabled"
    )

    annual = pd.read_csv(
        NETWORK_ANNUAL,
        dtype={"importer_m49": "string", "exporter_m49": "string"},
    )
    panel = pd.read_csv(PANEL_PATH, dtype={"entity_m49": "string"})
    primary = pd.read_csv(PRIMARY_FEATURES, dtype={"entity_m49": "string"})
    limited = pd.read_csv(LIMITED_FEATURES, dtype={"entity_m49": "string"})
    stability = pd.read_csv(STABILITY_PATH, dtype={"entity_m49": "string"})
    scenarios = pd.read_csv(SCENARIOS_PATH, dtype={"entity_m49": "string"})
    annual["importer_m49"] = normalize_m49(annual["importer_m49"])
    annual["exporter_m49"] = normalize_m49(annual["exporter_m49"])
    for frame in [panel, primary, limited, stability, scenarios]:
        frame["entity_m49"] = normalize_m49(frame["entity_m49"])

    validate_columns(
        annual,
        set(ANNUAL_KEY)
        | {
            "importer_name_trade",
            "exporter_name_trade",
            "core_food_code",
            "core_food",
            "observed_import_quantity_tonnes",
            "annual_network_total_tonnes",
            "supplier_share",
            "supplier_relationship_type",
            "agricultural_origin_known",
            "origin_inference_prohibited",
        },
        "Annual supplier network",
    )
    require(
        set(annual["year"].astype(int)) == set(policy["authoritative_years"]),
        "Network years changed",
    )
    require(not annual.duplicated(ANNUAL_KEY).any(), "Duplicate annual relationships")
    share_sums = annual.groupby(["importer_m49", "analytical_scope_code", "year"])[
        "supplier_share"
    ].sum()
    require(
        np.allclose(share_sums.to_numpy(), 1.0, atol=1e-10),
        "Annual supplier shares do not reconcile",
    )
    require(
        annual["supplier_relationship_type"].eq("IMMEDIATE_TRADE_PARTNER").all(),
        "Supplier relationship type changed",
    )
    require(
        not annual["agricultural_origin_known"].astype(bool).any(),
        "Agricultural origin inferred",
    )
    require(
        annual["origin_inference_prohibited"].astype(bool).all(),
        "Origin inference guardrail failed",
    )
    require(len(primary) == 661 and len(limited) == 816, "Governed populations changed")

    relationships = period_relationships(
        annual, [float(value) for value in policy["material_supplier_thresholds"]]
    )
    pooled_share_sums = relationships.groupby(
        [
            "importer_m49",
            "analytical_scope_code",
        ]
    )["pooled_supplier_share"].sum()

    require(
        np.allclose(
            pooled_share_sums.to_numpy(),
            1.0,
            atol=1e-10,
        ),
        "Period pooled supplier shares do not reconcile to one",
    )

    primary_relationships = attach_population(
        relationships, primary, "PRIMARY_ONLY", stability, policy
    )
    expanded_population = pd.concat([primary, limited], ignore_index=True)
    expanded_relationships = attach_population(
        relationships,
        expanded_population,
        "PRIMARY_PLUS_LIMITED",
        stability,
        policy,
    )
    all_relationships = pd.concat(
        [primary_relationships, expanded_relationships], ignore_index=True
    )
    require(
        not all_relationships["official_supplier_ranking_enabled"].any(),
        "Ranking enabled in relationships",
    )

    features = supplier_features(all_relationships, policy)
    primary_candidates = features.loc[
        features["analysis_population"].eq("PRIMARY_ONLY")
    ].copy()
    expanded_candidates = features.loc[
        features["analysis_population"].eq("PRIMARY_PLUS_LIMITED")
    ].copy()
    scenario = scenario_results(annual, scenarios, primary)
    systemic_stability = stability_features(scenario, policy)
    removal = removal_tests(annual, panel)
    removal_summary = removal.groupby(SUPPLIER_FOOD_KEY, as_index=False).agg(
        exporter_name=("exporter_name_trade", "first"),
        core_food_code=("core_food_code", "first"),
        core_food=("core_food", "first"),
        removal_tests=("removed_supplier_share", "size"),
        importers_with_share_loss_above_10pct=(
            "removed_supplier_share",
            lambda x: int((x >= 0.10).sum()),
        ),
        importers_with_share_loss_above_25pct=(
            "removed_supplier_share",
            lambda x: int((x >= 0.25).sum()),
        ),
        importers_with_share_loss_above_50pct=(
            "removed_supplier_share",
            lambda x: int((x >= 0.50).sum()),
        ),
        importer_years_with_no_remaining_supplier=(
            "no_remaining_observed_supplier",
            "sum",
        ),
        maximum_removed_supplier_share=("removed_supplier_share", "max"),
    )
    removal_summary["dynamic_substitution_modeled"] = False

    completeness = all_relationships.groupby("analysis_population", as_index=False).agg(
        relationship_records=("importer_m49", "size"),
        importer_food_records=("importer_m49", lambda x: 0),
        stability_joined_records=("stability_band", lambda x: int(x.notna().sum())),
        vulnerability_weight_available=(
            "vulnerability_band_weight",
            lambda x: int(x.notna().sum()),
        ),
    )
    completeness["stability_completeness_rate"] = (
        completeness["stability_joined_records"] / completeness["relationship_records"]
    )

    review = features.loc[
        features["systemic_reach_percentile"].ge(policy["systemic_high_percentile"])
        | features["low_substitutability_importer_count"].gt(0)
    ].copy()
    review["review_reason"] = np.where(
        review["systemic_reach_percentile"].ge(policy["systemic_high_percentile"]),
        "HIGH_WITHIN_SCOPE_SYSTEMIC_REACH",
        "LOW_SUBSTITUTABILITY_RELATIONSHIP_PRESENT",
    )
    review["review_status"] = "REQUIRES_ANALYST_REVIEW"

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    all_relationships.to_csv(RELATIONSHIPS_PATH, index=False)
    features.to_csv(FEATURES_PATH, index=False)
    primary_candidates.to_csv(PRIMARY_PATH, index=False)
    expanded_candidates.to_csv(EXPANDED_PATH, index=False)
    scenario.to_csv(SCENARIO_PATH, index=False)
    systemic_stability.to_csv(SYSTEMIC_STABILITY_PATH, index=False)
    removal.to_csv(REMOVAL_PATH, index=False)
    removal_summary.to_csv(REMOVAL_SUMMARY_PATH, index=False)
    completeness.to_csv(COMPLETENESS_PATH, index=False)
    review.to_csv(REVIEW_PATH, index=False)

    report = {
        "dataset": "Core Food supplier-food developmental chokepoints",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_commit(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [
                MODEL_POLICY_PATH,
                NETWORK_ANNUAL,
                PANEL_PATH,
                PRIMARY_FEATURES,
                LIMITED_FEATURES,
                STABILITY_PATH,
                SCENARIOS_PATH,
            ]
        },
        "chokepoint_policy_hash": sha256(POLICY_PATH),
        "authoritative_years": policy["authoritative_years"],
        "annual_supplier_edge_rows": len(annual),
        "annual_network_keys": int(
            annual.groupby(["importer_m49", "analytical_scope_code", "year"]).ngroups
        ),
        "period_relationship_rows": len(relationships),
        "primary_relationship_rows": len(primary_relationships),
        "expanded_relationship_rows": len(expanded_relationships),
        "supplier_food_feature_rows": len(features),
        "primary_supplier_food_nodes": len(primary_candidates),
        "expanded_supplier_food_nodes": len(expanded_candidates),
        "scenario_supplier_food_rows": len(scenario),
        "systemic_stability_rows": len(systemic_stability),
        "removal_test_rows": len(removal),
        "review_rows": len(review),
        "controls": {
            "authoritative_period_preserved": True,
            "annual_relationship_keys_unique": not annual.duplicated(ANNUAL_KEY).any(),
            "annual_supplier_shares_reconcile": True,
            "immediate_trade_partner_labeled": True,
            "agricultural_origin_not_inferred": True,
            "primary_and_limited_separate": True,
            "evidence_confidence_excluded_from_weighting": True,
            "supplier_food_grain_preserved": True,
            "scenario_stability_calculated": len(systemic_stability) > 0,
            "static_removal_no_substitution": not removal[
                "dynamic_substitution_modeled"
            ].any(),
            "official_chokepoint_score_disabled": True,
            "official_supplier_ranking_disabled": True,
        },
        "outputs": {
            "relationships": str(RELATIONSHIPS_PATH.relative_to(ROOT)),
            "systemic_features": str(FEATURES_PATH.relative_to(ROOT)),
            "primary_candidates": str(PRIMARY_PATH.relative_to(ROOT)),
            "expanded_candidates": str(EXPANDED_PATH.relative_to(ROOT)),
            "scenario_results": str(SCENARIO_PATH.relative_to(ROOT)),
            "stability": str(SYSTEMIC_STABILITY_PATH.relative_to(ROOT)),
            "removal_tests": str(REMOVAL_PATH.relative_to(ROOT)),
            "removal_summary": str(REMOVAL_SUMMARY_PATH.relative_to(ROOT)),
            "completeness": str(COMPLETENESS_PATH.relative_to(ROOT)),
            "review": str(REVIEW_PATH.relative_to(ROOT)),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD SUPPLIER CHOKEPOINT BUILD COMPLETE")
    print("=" * 72)
    print(f"Authoritative years: {'|'.join(map(str, policy['authoritative_years']))}")
    print(f"Annual supplier edges: {len(annual):,}")
    print(f"Annual network keys: {report['annual_network_keys']:,}")
    print(f"Primary supplier-food nodes: {len(primary_candidates):,}")
    print(f"Expanded supplier-food nodes: {len(expanded_candidates):,}")
    print(f"Scenario supplier-food rows: {len(scenario):,}")
    print(f"Static removal tests: {len(removal):,}")
    print(
        "No agricultural-origin inference, official chokepoint score, or supplier ranking was generated."
    )
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

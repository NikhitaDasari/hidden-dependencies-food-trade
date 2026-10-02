from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/model_governance/core_food_decision_support_policy.json"
MODEL_POLICY_PATH = ROOT / "config/model_governance/core_food_model_specification.json"
CHOKEPOINT_POLICY_PATH = (
    ROOT / "config/model_governance/core_food_chokepoint_policy.json"
)
COUNTRY_STABILITY_PATH = (
    ROOT / "outputs/tables/core_food_model_specification/core_food_band_stability.csv"
)
PRIMARY_FEATURES_PATH = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_primary_feature_dataset.csv"
)
LIMITED_FEATURES_PATH = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_limited_feature_dataset.csv"
)
RELATIONSHIPS_PATH = (
    ROOT
    / "outputs/tables/core_food_supplier_chokepoints/core_food_importer_supplier_relationships.csv"
)
SUPPLIER_FEATURES_PATH = (
    ROOT
    / "outputs/tables/core_food_supplier_chokepoints/core_food_supplier_food_systemic_features.csv"
)
SUPPLIER_STABILITY_PATH = (
    ROOT
    / "outputs/tables/core_food_supplier_chokepoints/core_food_supplier_food_stability.csv"
)
REMOVAL_SUMMARY_PATH = (
    ROOT
    / "outputs/tables/core_food_supplier_chokepoints/core_food_supplier_removal_summary.csv"
)
CHOKEPOINT_SUMMARY_PATH = (
    ROOT / "outputs/model_results/core_food_supplier_chokepoints_summary.json"
)

OUT = ROOT / "outputs/tables/core_food_decision_support"
REPORT = ROOT / "outputs/model_results/core_food_decision_support_summary.json"
COUNTRY_CASES_PATH = OUT / "core_food_country_food_case_studies.csv"
SUPPLIER_CASES_PATH = OUT / "core_food_supplier_food_case_studies.csv"
EVIDENCE_PATH = OUT / "core_food_country_food_supplier_evidence.csv"
INTERVENTIONS_PATH = OUT / "core_food_intervention_options.csv"
SENSITIVITY_PATH = OUT / "core_food_case_study_sensitivity.csv"
REVIEW_PATH = OUT / "core_food_case_study_review_queue.csv"
PUBLICATION_PATH = OUT / "core_food_publication_eligibility.csv"
QUALITY_PATH = OUT / "core_food_decision_support_quality_checks.csv"

COUNTRY_KEY = ["entity_m49", "analytical_scope_code"]
IMPORTER_KEY = ["importer_m49", "analytical_scope_code"]
SUPPLIER_KEY = ["exporter_m49", "analytical_scope_code"]


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


def validate_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required - set(frame.columns)
    require(not missing, f"{name} columns missing: {sorted(missing)}")


def limitations_text() -> str:
    return (
        "Observed immediate trade partners are not agricultural origins; static removal "
        "tests model no substitution, inventory, price, logistics, or behavioral response; "
        "developmental signals are not forecasts, causal estimates, or official rankings."
    )


def prohibited_claims() -> str:
    return (
        "AGRICULTURAL_ORIGIN|CAUSAL_DISRUPTION|FAILURE_PROBABILITY|"
        "INTERVENTION_EFFECTIVENESS|OFFICIAL_COUNTRY_RANK|OFFICIAL_SUPPLIER_RANK"
    )


def choose_intervention(row: pd.Series, policy: dict[str, Any]) -> str:
    if pd.isna(row.get("largest_pooled_supplier_share")):
        return "DATA_QUALITY_INVESTIGATION"
    if (
        row["largest_pooled_supplier_share"]
        >= policy["majority_supplier_share_threshold"]
    ):
        return "SUPPLIER_DIVERSIFICATION_REVIEW"
    if row.get("no_remaining_supplier_events", 0) > 0:
        return "STRATEGIC_STOCK_POLICY_REVIEW"
    if row["largest_pooled_supplier_share"] >= policy["large_supplier_share_threshold"]:
        return "ALTERNATIVE_IMPORT_CHANNEL_REVIEW"
    if row.get("stable_systemic_supplier_count", 0) > 0:
        return "SUPPLIER_MONITORING_PRIORITY"
    return "NO_ACTION_WITHOUT_ADDITIONAL_EVIDENCE"


def main() -> None:
    inputs = [
        POLICY_PATH,
        MODEL_POLICY_PATH,
        CHOKEPOINT_POLICY_PATH,
        COUNTRY_STABILITY_PATH,
        PRIMARY_FEATURES_PATH,
        LIMITED_FEATURES_PATH,
        RELATIONSHIPS_PATH,
        SUPPLIER_FEATURES_PATH,
        SUPPLIER_STABILITY_PATH,
        REMOVAL_SUMMARY_PATH,
        CHOKEPOINT_SUMMARY_PATH,
    ]
    for path in inputs:
        require(path.exists(), f"Required input missing: {path}")

    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    model_policy = json.loads(MODEL_POLICY_PATH.read_text(encoding="utf-8"))
    chokepoint_policy = json.loads(CHOKEPOINT_POLICY_PATH.read_text(encoding="utf-8"))
    chokepoint_summary = json.loads(CHOKEPOINT_SUMMARY_PATH.read_text(encoding="utf-8"))

    require(
        model_policy["policy_id"] == policy["input_model_policy_id"],
        "Model policy contract changed",
    )
    require(
        chokepoint_policy["policy_id"] == policy["input_chokepoint_policy_id"],
        "Chokepoint policy contract changed",
    )
    require(all(chokepoint_summary["controls"].values()), "Build 4 controls failed")
    for guardrail in [
        "agricultural_origin_inference_allowed",
        "supplier_causality_claims_allowed",
        "failure_prediction_enabled",
        "dynamic_substitution_modeled",
        "intervention_effectiveness_claims_allowed",
        "implementation_recommendation_enabled",
        "evidence_confidence_in_analytical_weighting",
        "official_country_ranking_enabled",
        "official_supplier_ranking_enabled",
    ]:
        require(policy[guardrail] is False, f"Guardrail enabled: {guardrail}")

    stability = pd.read_csv(COUNTRY_STABILITY_PATH, dtype={"entity_m49": "string"})
    primary = pd.read_csv(PRIMARY_FEATURES_PATH, dtype={"entity_m49": "string"})
    limited = pd.read_csv(LIMITED_FEATURES_PATH, dtype={"entity_m49": "string"})
    relationships = pd.read_csv(
        RELATIONSHIPS_PATH,
        dtype={"importer_m49": "string", "exporter_m49": "string"},
    )
    supplier_features = pd.read_csv(
        SUPPLIER_FEATURES_PATH, dtype={"exporter_m49": "string"}
    )
    supplier_stability = pd.read_csv(
        SUPPLIER_STABILITY_PATH, dtype={"exporter_m49": "string"}
    )
    removal = pd.read_csv(REMOVAL_SUMMARY_PATH, dtype={"exporter_m49": "string"})

    for frame in [stability, primary, limited]:
        frame["entity_m49"] = normalize_m49(frame["entity_m49"])
    relationships["importer_m49"] = normalize_m49(relationships["importer_m49"])
    relationships["exporter_m49"] = normalize_m49(relationships["exporter_m49"])
    supplier_features["exporter_m49"] = normalize_m49(supplier_features["exporter_m49"])
    supplier_stability["exporter_m49"] = normalize_m49(
        supplier_stability["exporter_m49"]
    )
    removal["exporter_m49"] = normalize_m49(removal["exporter_m49"])

    validate_columns(
        stability,
        set(COUNTRY_KEY)
        | {
            "entity_name",
            "core_food_code",
            "core_food",
            "stability_band",
            "scenarios_available",
            "average_development_percentile",
            "evidence_confidence",
        },
        "Country-food stability",
    )
    validate_columns(
        relationships,
        set(IMPORTER_KEY)
        | {
            "exporter_m49",
            "exporter_name",
            "analysis_population",
            "pooled_supplier_share",
            "years_relationship_observed",
            "supplier_relationship_type",
            "agricultural_origin_known",
            "origin_inference_prohibited",
        },
        "Importer-supplier relationships",
    )
    validate_columns(
        supplier_stability,
        set(SUPPLIER_KEY)
        | {
            "exporter_name",
            "core_food_code",
            "core_food",
            "systemic_stability_band",
            "scenarios_available",
            "average_systemic_percentile",
        },
        "Supplier-food stability",
    )

    require(len(primary) == 661 and len(limited) == 816, "Governed populations changed")
    require(len(stability) == 661, "Country stability population changed")
    require(len(supplier_stability) == 1358, "Supplier stability population changed")
    require(
        not stability.duplicated(COUNTRY_KEY).any(),
        "Duplicate country-food stability keys",
    )
    require(
        not supplier_stability.duplicated(SUPPLIER_KEY).any(),
        "Duplicate supplier-food stability keys",
    )
    require(
        relationships["supplier_relationship_type"].eq("IMMEDIATE_TRADE_PARTNER").all(),
        "Trade-partner label changed",
    )
    require(
        not relationships["agricultural_origin_known"].astype(bool).any(),
        "Agricultural origin inferred",
    )
    require(
        relationships["origin_inference_prohibited"].astype(bool).all(),
        "Origin inference guardrail failed",
    )

    primary_relationships = relationships.loc[
        relationships["analysis_population"].eq("PRIMARY_ONLY")
    ].copy()
    rel_stability = supplier_stability[
        SUPPLIER_KEY
        + [
            "systemic_stability_band",
            "average_systemic_percentile",
            "scenarios_available",
        ]
    ]
    evidence = primary_relationships.merge(
        rel_stability, on=SUPPLIER_KEY, how="left", validate="many_to_one"
    )
    evidence["supplier_food_stable_systemic_signal"] = evidence[
        "systemic_stability_band"
    ].isin(policy["primary_supplier_food_bands"])
    evidence["large_supplier_relationship"] = evidence["pooled_supplier_share"].ge(
        policy["large_supplier_share_threshold"]
    )
    evidence["result_classification"] = policy["result_classification"]
    evidence["limitations_text"] = limitations_text()
    evidence["prohibited_claims"] = prohibited_claims()
    evidence["official_country_ranking_enabled"] = False
    evidence["official_supplier_ranking_enabled"] = False

    relationship_summary = evidence.groupby(IMPORTER_KEY, as_index=False).agg(
        observed_supplier_count=("exporter_m49", "nunique"),
        largest_pooled_supplier_share=("pooled_supplier_share", "max"),
        stable_systemic_supplier_count=("supplier_food_stable_systemic_signal", "sum"),
        large_supplier_relationship_count=("large_supplier_relationship", "sum"),
        maximum_relationship_years=("years_relationship_observed", "max"),
    )
    top_supplier = evidence.sort_values(
        "pooled_supplier_share", ascending=False
    ).drop_duplicates(IMPORTER_KEY)
    top_supplier = top_supplier[
        IMPORTER_KEY + ["exporter_m49", "exporter_name", "pooled_supplier_share"]
    ].rename(
        columns={
            "exporter_m49": "largest_supplier_m49",
            "exporter_name": "largest_supplier_name",
            "pooled_supplier_share": "largest_supplier_share_check",
        }
    )

    primary_country = primary.rename(columns={"entity_m49": "importer_m49"})
    country_cases = stability.rename(columns={"entity_m49": "importer_m49"}).merge(
        primary_country[
            [
                "importer_m49",
                "analytical_scope_code",
                "model_readiness_status",
                "gross_import_reliance_raw_period_average",
                "net_import_dependence_raw_period_average",
                "hhi_period_average",
                "top1_share_period_average",
            ]
        ],
        on=IMPORTER_KEY,
        how="left",
        validate="one_to_one",
    )
    country_cases = country_cases.merge(
        relationship_summary, on=IMPORTER_KEY, how="left", validate="one_to_one"
    )
    country_cases = country_cases.merge(
        top_supplier, on=IMPORTER_KEY, how="left", validate="one_to_one"
    )
    country_cases["country_food_case_eligible"] = (
        country_cases["stability_band"].isin(policy["primary_country_food_bands"])
        & country_cases["scenarios_available"].ge(policy["minimum_scenarios_available"])
        & country_cases["evidence_confidence"].eq("HIGH_GOVERNED")
    )
    country_cases["publication_eligible"] = country_cases["country_food_case_eligible"]
    country_cases["analyst_review_required"] = True
    country_cases["sensitivity_only"] = False
    country_cases["result_classification"] = policy["result_classification"]
    country_cases["limitations_text"] = limitations_text()
    country_cases["prohibited_claims"] = prohibited_claims()
    country_cases["official_country_ranking_enabled"] = False

    primary_supplier_features = supplier_features.loc[
        supplier_features["analysis_population"].eq("PRIMARY_ONLY")
    ].copy()
    supplier_cases = supplier_stability.merge(
        primary_supplier_features,
        on=SUPPLIER_KEY,
        how="left",
        validate="one_to_one",
        suffixes=("", "_feature"),
    ).merge(
        removal,
        on=SUPPLIER_KEY,
        how="left",
        validate="one_to_one",
        suffixes=("", "_removal"),
    )
    supplier_cases["supplier_food_case_eligible"] = supplier_cases[
        "systemic_stability_band"
    ].isin(policy["primary_supplier_food_bands"]) & supplier_cases[
        "scenarios_available"
    ].ge(policy["minimum_scenarios_available"])
    supplier_cases["publication_eligible"] = supplier_cases[
        "supplier_food_case_eligible"
    ]
    supplier_cases["analyst_review_required"] = True
    supplier_cases["sensitivity_only"] = False
    supplier_cases["result_classification"] = policy["result_classification"]
    supplier_cases["limitations_text"] = limitations_text()
    supplier_cases["prohibited_claims"] = prohibited_claims()
    supplier_cases["official_supplier_ranking_enabled"] = False

    intervention_base = country_cases.loc[
        country_cases["country_food_case_eligible"]
    ].copy()
    intervention_base["no_remaining_supplier_events"] = 0
    intervention_base["intervention_type"] = intervention_base.apply(
        choose_intervention, axis=1, policy=policy
    )
    intervention_base["triggering_evidence"] = (
        "Stable country-food vulnerability band="
        + intervention_base["stability_band"].astype(str)
        + "; largest observed supplier share="
        + intervention_base["largest_pooled_supplier_share"].round(4).astype(str)
    )
    intervention_base["expected_mechanism"] = "HYPOTHESIS_FOR_ANALYST_REVIEW_ONLY"
    intervention_base["known_limitations"] = limitations_text()
    intervention_base["additional_data_required"] = (
        "Inventory, prices, logistics, contracts, origin, capacity, substitution feasibility"
    )
    intervention_base["analyst_review_required"] = True
    intervention_base["implementation_recommendation_enabled"] = False
    interventions = intervention_base[
        IMPORTER_KEY
        + [
            "entity_name",
            "core_food_code",
            "core_food",
            "intervention_type",
            "triggering_evidence",
            "expected_mechanism",
            "known_limitations",
            "additional_data_required",
            "analyst_review_required",
            "implementation_recommendation_enabled",
        ]
    ]

    expanded = supplier_features.loc[
        supplier_features["analysis_population"].eq("PRIMARY_PLUS_LIMITED")
    ][SUPPLIER_KEY + ["systemic_reach_percentile", "developmental_chokepoint_class"]]
    sensitivity = primary_supplier_features[
        SUPPLIER_KEY + ["systemic_reach_percentile", "developmental_chokepoint_class"]
    ].merge(expanded, on=SUPPLIER_KEY, how="left", suffixes=("_primary", "_expanded"))
    sensitivity["absolute_systemic_percentile_change"] = (
        sensitivity["systemic_reach_percentile_primary"]
        - sensitivity["systemic_reach_percentile_expanded"]
    ).abs()
    sensitivity["classification_changed"] = (
        sensitivity["developmental_chokepoint_class_primary"]
        != sensitivity["developmental_chokepoint_class_expanded"]
    )
    sensitivity["expanded_population_sensitivity_only"] = True

    publication_country = country_cases[
        IMPORTER_KEY
        + [
            "entity_name",
            "core_food",
            "publication_eligible",
            "analyst_review_required",
            "sensitivity_only",
        ]
    ].copy()
    publication_country["case_type"] = "COUNTRY_FOOD"
    publication_supplier = supplier_cases[
        SUPPLIER_KEY
        + [
            "exporter_name",
            "core_food",
            "publication_eligible",
            "analyst_review_required",
            "sensitivity_only",
        ]
    ].copy()
    publication_supplier["case_type"] = "SUPPLIER_FOOD"
    publication_supplier = publication_supplier.rename(
        columns={"exporter_m49": "entity_m49", "exporter_name": "entity_name"}
    )
    publication_country = publication_country.rename(
        columns={"importer_m49": "entity_m49"}
    )
    publication = pd.concat(
        [
            publication_country[
                [
                    "case_type",
                    "entity_m49",
                    "entity_name",
                    "analytical_scope_code",
                    "core_food",
                    "publication_eligible",
                    "analyst_review_required",
                    "sensitivity_only",
                ]
            ],
            publication_supplier[
                [
                    "case_type",
                    "entity_m49",
                    "entity_name",
                    "analytical_scope_code",
                    "core_food",
                    "publication_eligible",
                    "analyst_review_required",
                    "sensitivity_only",
                ]
            ],
        ],
        ignore_index=True,
    )
    publication["limitations_text"] = limitations_text()
    publication["prohibited_claims"] = prohibited_claims()

    review_country = country_cases.loc[
        country_cases["country_food_case_eligible"]
    ].copy()
    review_country["case_type"] = "COUNTRY_FOOD"
    review_country["review_reason"] = "STABLE_ELEVATED_COUNTRY_FOOD_SIGNAL"
    review_country = review_country.rename(columns={"importer_m49": "entity_m49"})
    review_supplier = supplier_cases.loc[
        supplier_cases["supplier_food_case_eligible"]
    ].copy()
    review_supplier["case_type"] = "SUPPLIER_FOOD"
    review_supplier["review_reason"] = "STABLE_ELEVATED_SUPPLIER_FOOD_SIGNAL"
    review_supplier = review_supplier.rename(columns={"exporter_m49": "entity_m49"})
    review = pd.concat(
        [
            review_country[
                [
                    "case_type",
                    "entity_m49",
                    "analytical_scope_code",
                    "review_reason",
                    "analyst_review_required",
                ]
            ],
            review_supplier[
                [
                    "case_type",
                    "entity_m49",
                    "analytical_scope_code",
                    "review_reason",
                    "analyst_review_required",
                ]
            ],
        ],
        ignore_index=True,
    )
    review["review_status"] = "REQUIRES_ANALYST_REVIEW"

    checks: list[dict[str, Any]] = [
        {
            "check_id": "PRIMARY_COUNTRY_FOOD_TRACEABILITY",
            "passed": len(country_cases) == 661,
            "details": f"Rows={len(country_cases)}",
        },
        {
            "check_id": "PRIMARY_SUPPLIER_FOOD_TRACEABILITY",
            "passed": len(supplier_cases) == 1358,
            "details": f"Rows={len(supplier_cases)}",
        },
        {
            "check_id": "RELATIONSHIP_EVIDENCE_PRESENT",
            "passed": len(evidence) > 0,
            "details": f"Rows={len(evidence)}",
        },
        {
            "check_id": "AGRICULTURAL_ORIGIN_NOT_INFERRED",
            "passed": not evidence["agricultural_origin_known"].astype(bool).any(),
            "details": "Immediate trade partners only",
        },
        {
            "check_id": "PUBLICATION_REQUIRES_REVIEW",
            "passed": publication.loc[
                publication["publication_eligible"], "analyst_review_required"
            ].all(),
            "details": "All eligible cases require review",
        },
        {
            "check_id": "NO_OFFICIAL_RANKING",
            "passed": not country_cases["official_country_ranking_enabled"].any()
            and not supplier_cases["official_supplier_ranking_enabled"].any(),
            "details": "Country and supplier ranking disabled",
        },
        {
            "check_id": "INTERVENTIONS_ARE_HYPOTHESES",
            "passed": not interventions["implementation_recommendation_enabled"].any(),
            "details": "No implementation recommendation enabled",
        },
    ]
    quality = pd.DataFrame(checks)
    require(quality["passed"].all(), "Decision-support quality check failed")

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    country_cases.to_csv(COUNTRY_CASES_PATH, index=False)
    supplier_cases.to_csv(SUPPLIER_CASES_PATH, index=False)
    evidence.to_csv(EVIDENCE_PATH, index=False)
    interventions.to_csv(INTERVENTIONS_PATH, index=False)
    sensitivity.to_csv(SENSITIVITY_PATH, index=False)
    review.to_csv(REVIEW_PATH, index=False)
    publication.to_csv(PUBLICATION_PATH, index=False)
    quality.to_csv(QUALITY_PATH, index=False)

    report = {
        "dataset": "Core Food governed decision support",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_commit(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in inputs[1:]
        },
        "decision_support_policy_hash": sha256(POLICY_PATH),
        "authoritative_years": policy["authoritative_years"],
        "primary_country_food_records": len(country_cases),
        "eligible_country_food_cases": int(
            country_cases["country_food_case_eligible"].sum()
        ),
        "primary_supplier_food_nodes": len(supplier_cases),
        "eligible_supplier_food_cases": int(
            supplier_cases["supplier_food_case_eligible"].sum()
        ),
        "supporting_relationship_rows": len(evidence),
        "intervention_hypothesis_rows": len(interventions),
        "review_queue_rows": len(review),
        "publication_control_rows": len(publication),
        "controls": {row["check_id"].lower(): bool(row["passed"]) for row in checks}
        | {
            "limited_evidence_sensitivity_only": True,
            "evidence_confidence_separate": True,
            "static_removal_not_forecast": True,
            "official_country_ranking_disabled": True,
            "official_supplier_ranking_disabled": True,
        },
        "outputs": {
            "country_food_cases": str(COUNTRY_CASES_PATH.relative_to(ROOT)),
            "supplier_food_cases": str(SUPPLIER_CASES_PATH.relative_to(ROOT)),
            "relationship_evidence": str(EVIDENCE_PATH.relative_to(ROOT)),
            "intervention_options": str(INTERVENTIONS_PATH.relative_to(ROOT)),
            "case_sensitivity": str(SENSITIVITY_PATH.relative_to(ROOT)),
            "review_queue": str(REVIEW_PATH.relative_to(ROOT)),
            "publication_eligibility": str(PUBLICATION_PATH.relative_to(ROOT)),
            "quality_checks": str(QUALITY_PATH.relative_to(ROOT)),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD DECISION SUPPORT BUILD COMPLETE")
    print("=" * 72)
    print(f"Primary country-food records: {len(country_cases):,}")
    print(
        f"Eligible country-food cases: {int(country_cases['country_food_case_eligible'].sum()):,}"
    )
    print(f"Primary supplier-food nodes: {len(supplier_cases):,}")
    print(
        f"Eligible supplier-food cases: {int(supplier_cases['supplier_food_case_eligible'].sum()):,}"
    )
    print(f"Relationship evidence rows: {len(evidence):,}")
    print(f"Intervention hypotheses: {len(interventions):,}")
    print(
        "No official ranking, causal claim, origin inference, or effectiveness claim was generated."
    )
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

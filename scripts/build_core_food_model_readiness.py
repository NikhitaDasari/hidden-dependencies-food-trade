from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/model_governance/core_food_readiness_policy.json"
DECISION_DIR = ROOT / "config/review_decisions"
OUT = ROOT / "outputs/tables/core_food_model_readiness"
REPORT = ROOT / "outputs/model_results/core_food_model_readiness_summary.json"

USABILITY = (
    ROOT
    / "outputs/tables/core_food_fbs_foundation/core_food_fbs_baseline_usability.csv"
)
READY = (
    ROOT / "outputs/tables/core_food_fbs_foundation/core_food_fbs_baseline_ready.csv"
)
SCOPES = (
    ROOT / "outputs/tables/core_food_fbs_foundation/core_food_analytical_scopes.csv"
)
NETWORK = (
    ROOT
    / "outputs/tables/core_food_supplier_network/core_food_supplier_network_summary.csv"
)
ANNUAL = (
    ROOT
    / "outputs/tables/core_food_supplier_network/core_food_supplier_network_annual.csv"
)
UNMATCHED = (
    ROOT
    / "outputs/tables/core_food_supplier_network/core_food_supplier_network_unmatched_importers.csv"
)
GEO = (
    ROOT
    / "outputs/tables/core_food_country_foundation/unified_geography_capability.csv"
)

COUNTRY_DECISIONS = DECISION_DIR / "country_eligibility_decisions.csv"
MAPPING_DECISIONS = DECISION_DIR / "scope_mapping_decisions.csv"
COVERAGE_DECISIONS = DECISION_DIR / "coverage_exception_decisions.csv"

KEY = ["entity_m49", "analytical_scope_code"]
EXPECTED_TOTAL = 4048
EXPECTED_LINKAGE_READY = 2257
EXPECTED_IMPORTER_EXCLUDED = 219
EXPECTED_NO_NETWORK = 55
EXPECTED_OBSERVED_NETWORK = 1983

SCOPE_RECOMMENDATIONS = {
    "DIRECT_FAMILY": "PRIMARY_ALIGNED",
    "ANALYTICAL_SUBFAMILY": "PRIMARY_SEPARATE_SUBFAMILY",
    "PARTIAL_PRODUCT_CHANNEL": "PARTIAL_CHANNEL_APPROVED",
    "CONVERSION_REQUIRED": "CONVERSION_METHOD_REQUIRED",
    "SENSITIVITY_ONLY": "SENSITIVITY_ONLY",
}
ALLOWED_COUNTRY = {
    "APPROVED",
    "APPROVED_WITH_LIMITATION",
    "REJECTED_NO_BASELINE_IMPORT_OBSERVATION",
    "REJECTED_AGGREGATE",
    "REJECTED_COMPOSITE",
    "REVIEW_CODE_ALIGNMENT",
    "REVIEW_TERRITORY_STATUS",
}
ALLOWED_MAPPING = {
    "PRIMARY_ALIGNED",
    "PRIMARY_SEPARATE_SUBFAMILY",
    "PARTIAL_CHANNEL_APPROVED",
    "CONVERSION_METHOD_REQUIRED",
    "SENSITIVITY_ONLY",
    "REJECTED_OVERLAP",
    "REJECTED_DOUBLE_COUNTING",
    "REVIEW_ITEM_COVERAGE",
}
ALLOWED_COVERAGE = {
    "NO_OVERRIDE",
    "APPROVE_WITH_LIMITATION",
    "KEEP_REVIEW_HOLD",
    "NOT_ELIGIBLE",
}


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


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return (
        series.astype("string")
        .str.casefold()
        .map({"true": True, "false": False, "1": True, "0": False})
        .fillna(False)
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def validate_policy(policy: dict[str, Any]) -> None:
    required = {
        "policy_id",
        "policy_version",
        "baseline_years",
        "coverage_thresholds",
        "minimum_years",
        "primary_mapping_decisions",
        "limited_mapping_decisions",
        "primary_fbs_confidence",
        "limited_fbs_confidence",
        "require_human_country_approval_for_release",
        "require_human_mapping_approval_for_release",
        "allow_coverage_override_to_primary",
        "final_ranking_enabled",
    }
    require(
        required <= set(policy),
        f"Policy keys missing: {sorted(required - set(policy))}",
    )
    require(policy["baseline_years"] == [2021, 2022, 2023], "Unexpected baseline years")
    limits = policy["coverage_thresholds"]
    ordered = [
        limits["low_upper_exclusive"],
        limits["partial_upper_exclusive"],
        limits["aligned_upper_inclusive"],
        limits["above_fbs_upper_inclusive"],
    ]
    require(ordered == sorted(ordered), "Coverage thresholds are not monotonic")
    require(
        policy["allow_coverage_override_to_primary"] is False,
        "Coverage override cannot promote to primary",
    )
    require(
        policy["final_ranking_enabled"] is False,
        "Readiness policy cannot enable ranking",
    )


def load_decisions(
    path: Path, keys: list[str], decision: str, allowed: set[str]
) -> pd.DataFrame:
    columns = keys + [
        decision,
        "reviewer",
        "review_date",
        "decision_rationale",
        "evidence_reference",
    ]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, dtype={key: "string" for key in keys})
    missing = set(keys + [decision]) - set(frame)
    require(not missing, f"{path.name} columns missing: {sorted(missing)}")
    if "entity_m49" in frame:
        frame["entity_m49"] = normalize_m49(frame["entity_m49"])
    require(not frame.duplicated(keys).any(), f"Duplicate keys in {path}")
    invalid = sorted(set(frame[decision].dropna()) - allowed)
    require(not invalid, f"Invalid decisions in {path}: {invalid}")
    for column in columns:
        if column not in frame:
            frame[column] = ""
    final = frame[decision].notna() & ~frame[decision].isin(
        {
            "NO_OVERRIDE",
            "REVIEW_CODE_ALIGNMENT",
            "REVIEW_TERRITORY_STATUS",
            "REVIEW_ITEM_COVERAGE",
        }
    )
    if final.any():
        for column in ["reviewer", "review_date", "decision_rationale"]:
            require(
                frame.loc[final, column].fillna("").str.strip().ne("").all(),
                f"Final decisions require {column} in {path}",
            )
    return frame[columns]


def fbs_gate(row: pd.Series, policy: dict[str, Any]) -> str:
    if (
        row["negative_domestic_supply_years"] > 0
        or row["overall_confidence_class"] == "DATA_REVIEW"
    ):
        return "FAIL_DATA_REVIEW"
    years = policy["minimum_years"]
    if (
        row["gross_reliance_years_available"] >= years["primary_fbs_gross"]
        and row["net_dependence_years_available"] >= years["primary_fbs_net"]
        and row["overall_confidence_class"] in policy["primary_fbs_confidence"]
    ):
        return "PASS_PRIMARY"
    if (
        row["gross_reliance_years_available"] >= years["limited_fbs_gross"]
        and row["overall_confidence_class"] in policy["limited_fbs_confidence"]
    ):
        return "PASS_WITH_LIMITATION"
    return "FAIL_INSUFFICIENT_FBS_SUPPORT"


def network_year_gate(row: pd.Series, policy: dict[str, Any]) -> str:
    if not row["ready_for_network_linkage"]:
        return "NOT_APPLICABLE_PRE_LINKAGE"
    if not row["importer_eligible"]:
        return "FAIL_IMPORTER_INELIGIBLE"
    if not row["has_observed_network"]:
        return "FAIL_NO_OBSERVED_NETWORK"
    years = row["network_years_observed"]
    minimum = policy["minimum_years"]
    if years >= minimum["primary_network"]:
        return "PASS_PRIMARY"
    if years >= minimum["limited_network"]:
        return "PASS_WITH_LIMITATION"
    return "FAIL_INSUFFICIENT_NETWORK_YEARS"


def coverage_gate(row: pd.Series) -> str:
    if not row["ready_for_network_linkage"]:
        return "NOT_APPLICABLE_PRE_LINKAGE"
    if not row["importer_eligible"]:
        return "FAIL_IMPORTER_INELIGIBLE"
    if not row["has_observed_network"]:
        return "FAIL_NO_OBSERVED_NETWORK"
    return {
        "ALIGNED_COVERAGE": "PASS_ALIGNED",
        "PARTIAL_COVERAGE": "PASS_WITH_LIMITATION_PARTIAL",
        "LOW_COVERAGE": "FAIL_LOW_COVERAGE",
        "ABOVE_FBS_IMPORTS": "REVIEW_ABOVE_FBS",
        "EXTREME_COVERAGE_REVIEW": "REVIEW_EXTREME",
        "FBS_IMPORT_DENOMINATOR_UNAVAILABLE": "FAIL_DENOMINATOR_UNAVAILABLE",
        "NO_OBSERVED_NETWORK": "FAIL_NO_OBSERVED_NETWORK",
    }.get(str(row.get("network_coverage_class")), "REVIEW_UNKNOWN_COVERAGE")


def governance_state(value: object, pending_values: set[str]) -> str:
    if pd.isna(value) or not str(value).strip() or str(value) in pending_values:
        return "PENDING"
    return "FINAL"


def classify(row: pd.Series, policy: dict[str, Any]) -> tuple[str, str]:
    recommendation = row["mapping_policy_recommendation"]
    mapping = row["mapping_effective_decision"]

    # Scope and FBS gates precede network gates. This preserves the complete universe.
    if row["fbs_gate"] == "FAIL_DATA_REVIEW":
        return "DATA_REVIEW_REQUIRED", "TECHNICAL"
    if (
        recommendation == "CONVERSION_METHOD_REQUIRED"
        and row["mapping_decision_state"] != "FINAL"
    ):
        return "CONVERSION_METHOD_REQUIRED", "GOVERNANCE"
    if mapping == "CONVERSION_METHOD_REQUIRED":
        return "CONVERSION_METHOD_REQUIRED", "GOVERNANCE"
    if (
        recommendation == "SENSITIVITY_ONLY"
        and row["mapping_decision_state"] != "FINAL"
    ):
        return "SENSITIVITY_ONLY", "GOVERNANCE"
    if mapping == "SENSITIVITY_ONLY":
        return "SENSITIVITY_ONLY", "GOVERNANCE"
    if mapping in {"REJECTED_OVERLAP", "REJECTED_DOUBLE_COUNTING"}:
        return "NOT_ELIGIBLE", "GOVERNANCE"
    if mapping == "REVIEW_ITEM_COVERAGE":
        return "MAPPING_REVIEW_REQUIRED", "GOVERNANCE"
    if row["fbs_gate"] == "FAIL_INSUFFICIENT_FBS_SUPPORT":
        return "FBS_SUPPORT_INSUFFICIENT", "TECHNICAL"
    if not row["ready_for_network_linkage"]:
        return "NOT_READY_FOR_NETWORK_LINKAGE", "TECHNICAL"
    if not row["importer_eligible"]:
        return "NOT_ELIGIBLE", "TECHNICAL"
    if row["network_year_gate"] == "FAIL_NO_OBSERVED_NETWORK":
        return "NO_OBSERVED_NETWORK", "TECHNICAL"
    if row["coverage_gate"] == "FAIL_DENOMINATOR_UNAVAILABLE":
        return "FBS_DENOMINATOR_UNAVAILABLE", "TECHNICAL"
    if row["coverage_gate"] == "FAIL_LOW_COVERAGE":
        return "LOW_NETWORK_COVERAGE", "TECHNICAL"
    if row["coverage_gate"] == "REVIEW_EXTREME":
        return "EXTREME_COVERAGE_REVIEW", "GOVERNANCE"
    if row["coverage_gate"] == "REVIEW_ABOVE_FBS":
        return "ABOVE_FBS_COVERAGE_REVIEW", "GOVERNANCE"
    if row["coverage_override_decision"] == "NOT_ELIGIBLE":
        return "NOT_ELIGIBLE", "GOVERNANCE"
    if row["coverage_override_decision"] == "KEEP_REVIEW_HOLD":
        return "COVERAGE_REVIEW_REQUIRED", "GOVERNANCE"

    technically_primary = (
        row["fbs_gate"] == "PASS_PRIMARY"
        and row["network_year_gate"] == "PASS_PRIMARY"
        and row["coverage_gate"] == "PASS_ALIGNED"
        and mapping in policy["primary_mapping_decisions"]
    )
    technically_limited = (
        row["fbs_gate"] in {"PASS_PRIMARY", "PASS_WITH_LIMITATION"}
        and row["network_year_gate"] in {"PASS_PRIMARY", "PASS_WITH_LIMITATION"}
        and row["coverage_gate"] in {"PASS_ALIGNED", "PASS_WITH_LIMITATION_PARTIAL"}
        and mapping in policy["limited_mapping_decisions"]
    )
    pending = (
        row["country_decision_state"] != "FINAL"
        or row["mapping_decision_state"] != "FINAL"
    )
    if technically_primary:
        return (
            "TECHNICALLY_READY_GOVERNANCE_PENDING"
            if pending
            else "READY_FOR_PRIMARY_MODEL",
            "GOVERNANCE" if pending else "APPROVED",
        )
    if (
        technically_limited
        or row["coverage_override_decision"] == "APPROVE_WITH_LIMITATION"
    ):
        return (
            "READY_WITH_LIMITATIONS_GOVERNANCE_PENDING"
            if pending
            else "READY_WITH_LIMITATIONS",
            "GOVERNANCE" if pending else "APPROVED",
        )
    return "DATA_REVIEW_REQUIRED", "TECHNICAL"


def issue_flags(row: pd.Series) -> str:
    values: list[str] = []
    checks = [
        ("fbs_gate", {"PASS_PRIMARY"}),
        ("mapping_policy_recommendation", {"PRIMARY_ALIGNED"}),
        ("network_year_gate", {"PASS_PRIMARY", "NOT_APPLICABLE_PRE_LINKAGE"}),
        ("coverage_gate", {"PASS_ALIGNED", "NOT_APPLICABLE_PRE_LINKAGE"}),
    ]
    for column, normal in checks:
        value = str(row[column])
        if value not in normal:
            values.append(value)
    if not row["ready_for_network_linkage"]:
        values.append("NOT_READY_FOR_NETWORK_LINKAGE")
    if row["country_decision_state"] == "PENDING":
        values.append("COUNTRY_GOVERNANCE_PENDING")
    if row["mapping_decision_state"] == "PENDING":
        values.append("MAPPING_GOVERNANCE_PENDING")
    if row["coverage_override_decision"] != "NO_OVERRIDE":
        values.append(f"COVERAGE_OVERRIDE_{row['coverage_override_decision']}")
    return "|".join(dict.fromkeys(values)) or "NONE"


def main() -> None:
    sources = [USABILITY, READY, SCOPES, NETWORK, ANNUAL, UNMATCHED, GEO]
    for path in sources + [POLICY_PATH]:
        require(path.exists(), f"Required input missing: {path}")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    validate_policy(policy)

    universe = pd.read_csv(USABILITY, dtype={"entity_m49": "string"})
    ready = pd.read_csv(READY, dtype={"entity_m49": "string"})
    scopes = pd.read_csv(SCOPES)
    network = pd.read_csv(
        NETWORK, dtype={"entity_m49": "string", "importer_m49": "string"}
    )
    annual = pd.read_csv(ANNUAL, dtype={"importer_m49": "string"})
    unmatched = pd.read_csv(UNMATCHED, dtype={"entity_m49": "string"})
    geo = pd.read_csv(GEO, dtype={"entity_m49": "string"})
    for frame in [universe, ready, network, unmatched, geo]:
        frame["entity_m49"] = normalize_m49(frame["entity_m49"])
    annual["importer_m49"] = normalize_m49(annual["importer_m49"])

    require(
        len(universe) == EXPECTED_TOTAL, f"Expected {EXPECTED_TOTAL:,} universe rows"
    )
    require(
        len(ready) == EXPECTED_LINKAGE_READY,
        f"Expected {EXPECTED_LINKAGE_READY:,} linkage-ready rows",
    )
    require(not universe.duplicated(KEY).any(), "Duplicate universe keys")
    require(not network.duplicated(KEY).any(), "Duplicate network keys")
    require(
        len(unmatched) == EXPECTED_IMPORTER_EXCLUDED,
        "Unexpected importer-exclusion count",
    )

    ready_keys = ready[KEY].drop_duplicates().assign(ready_from_file=True)
    model = universe.merge(ready_keys, on=KEY, how="left", validate="one_to_one")
    model["ready_from_file"] = model["ready_from_file"].fillna(False)
    model["ready_for_network_linkage"] = as_bool(model["ready_for_network_linkage"])
    require(
        model["ready_for_network_linkage"].eq(model["ready_from_file"]).all(),
        "Ready flags do not reconcile to ready file",
    )

    annual_years = (
        annual.groupby(["importer_m49", "analytical_scope_code"], as_index=False)
        .agg(network_years_observed=("year", "nunique"))
        .rename(columns={"importer_m49": "entity_m49"})
    )
    network_fields = [
        column for column in network if column not in model or column in KEY
    ]
    model = model.merge(
        network[network_fields],
        on=KEY,
        how="left",
        validate="one_to_one",
        indicator="network_join",
    )
    model = model.merge(annual_years, on=KEY, how="left", validate="one_to_one")
    model["network_years_observed"] = (
        model["network_years_observed"].fillna(0).astype(int)
    )
    model["importer_eligible"] = model["network_join"].eq("both")
    model["has_observed_network"] = as_bool(model["has_observed_network"])
    model["country_technical_gate"] = model.apply(
        lambda row: (
            "NOT_APPLICABLE_PRE_LINKAGE"
            if not row["ready_for_network_linkage"]
            else "PASS_OBSERVED_IMPORTER"
            if row["importer_eligible"]
            else "FAIL_NO_BASELINE_IMPORT_OBSERVATION"
        ),
        axis=1,
    )

    country = load_decisions(
        COUNTRY_DECISIONS,
        ["entity_m49"],
        "country_governance_decision",
        ALLOWED_COUNTRY,
    )
    mapping = load_decisions(
        MAPPING_DECISIONS,
        ["analytical_scope_code"],
        "mapping_governance_decision",
        ALLOWED_MAPPING,
    )
    coverage = load_decisions(
        COVERAGE_DECISIONS, KEY, "coverage_override_decision", ALLOWED_COVERAGE
    )
    model = model.merge(
        country,
        on="entity_m49",
        how="left",
        validate="many_to_one",
        suffixes=("", "_country"),
    )
    model = model.merge(
        mapping,
        on="analytical_scope_code",
        how="left",
        validate="many_to_one",
        suffixes=("", "_mapping"),
    )
    model = model.merge(
        coverage, on=KEY, how="left", validate="one_to_one", suffixes=("", "_coverage")
    )
    model["mapping_policy_recommendation"] = model["scope_confidence_class"].map(
        SCOPE_RECOMMENDATIONS
    )
    require(
        model["mapping_policy_recommendation"].notna().all(),
        "Unknown scope confidence class",
    )
    model["mapping_effective_decision"] = model["mapping_governance_decision"].fillna(
        model["mapping_policy_recommendation"]
    )
    model["coverage_override_decision"] = model["coverage_override_decision"].fillna(
        "NO_OVERRIDE"
    )
    model["country_policy_recommendation"] = model["country_technical_gate"].map(
        {
            "PASS_OBSERVED_IMPORTER": "APPROVED",
            "FAIL_NO_BASELINE_IMPORT_OBSERVATION": "REJECTED_NO_BASELINE_IMPORT_OBSERVATION",
            "NOT_APPLICABLE_PRE_LINKAGE": "NOT_APPLICABLE_PRE_LINKAGE",
        }
    )
    model["country_decision_state"] = model["country_governance_decision"].apply(
        lambda value: governance_state(
            value, {"REVIEW_CODE_ALIGNMENT", "REVIEW_TERRITORY_STATUS"}
        )
    )
    model["mapping_decision_state"] = model["mapping_governance_decision"].apply(
        lambda value: governance_state(value, {"REVIEW_ITEM_COVERAGE"})
    )

    model["fbs_gate"] = model.apply(fbs_gate, axis=1, policy=policy)
    model["network_year_gate"] = model.apply(network_year_gate, axis=1, policy=policy)
    model["coverage_gate"] = model.apply(coverage_gate, axis=1)
    classified = model.apply(
        lambda row: classify(row, policy), axis=1, result_type="expand"
    )
    model[["model_readiness_status", "readiness_authority"]] = classified
    model["model_readiness_issue_flags"] = model.apply(issue_flags, axis=1)
    model["technical_model_candidate"] = model["model_readiness_status"].isin(
        {
            "TECHNICALLY_READY_GOVERNANCE_PENDING",
            "READY_WITH_LIMITATIONS_GOVERNANCE_PENDING",
            "READY_FOR_PRIMARY_MODEL",
            "READY_WITH_LIMITATIONS",
        }
    )
    model["governance_approved_for_model"] = model["model_readiness_status"].isin(
        {"READY_FOR_PRIMARY_MODEL", "READY_WITH_LIMITATIONS"}
    )
    model["ready_for_final_ranking"] = False
    model["policy_id"] = policy["policy_id"]
    model["policy_version"] = policy["policy_version"]

    # Enterprise population and fail-closed controls.
    require(
        len(model) == EXPECTED_TOTAL and not model.duplicated(KEY).any(),
        "Universe classification failed",
    )
    require(model["model_readiness_status"].notna().all(), "Missing readiness status")
    require(not model["ready_for_final_ranking"].any(), "Final ranking enabled")
    require(
        model["ready_for_network_linkage"].sum() == EXPECTED_LINKAGE_READY,
        "Linkage-ready population changed",
    )
    importer_excluded = model["ready_for_network_linkage"] & ~model["importer_eligible"]

    source_network_observed = as_bool(network["has_observed_network"])

    observed_network_keys = pd.MultiIndex.from_frame(
        network.loc[source_network_observed, KEY]
    )
    absent_network_keys = pd.MultiIndex.from_frame(
        network.loc[~source_network_observed, KEY]
    )
    model_keys = pd.MultiIndex.from_frame(model[KEY])

    observed = pd.Series(
        model_keys.isin(observed_network_keys),
        index=model.index,
        dtype=bool,
    )
    no_network = pd.Series(
        model_keys.isin(absent_network_keys),
        index=model.index,
        dtype=bool,
    )

    # Authoritative network-summary keys control the exported network flag.
    model["has_observed_network"] = observed

    expected_importer_eligible = len(network)
    expected_no_network = int((~source_network_observed).sum())
    expected_observed_network = int(source_network_observed.sum())

    print(
        "Network reconciliation: "
        f"source={expected_importer_eligible:,}, "
        f"source_observed={expected_observed_network:,}, "
        f"source_absent={expected_no_network:,}, "
        f"model_observed={int(observed.sum()):,}, "
        f"model_absent={int(no_network.sum()):,}"
    )

    require(
        not (observed & no_network).any(),
        "A record appears in both observed and absent network populations",
    )
    require(
        not observed.loc[~model["ready_for_network_linkage"]].any(),
        "A pre-linkage record was assigned an observed network",
    )
    require(
        not no_network.loc[~model["ready_for_network_linkage"]].any(),
        "A pre-linkage record was assigned an absent-network state",
    )
    require(
        expected_importer_eligible == expected_no_network + expected_observed_network,
        "Supplier-network source population does not reconcile",
    )
    require(
        int(model["ready_for_network_linkage"].sum()) == len(ready),
        "Linkage-ready population does not reconcile to the ready file",
    )
    require(
        int(importer_excluded.sum()) == len(unmatched),
        "Importer exclusions do not reconcile to the exclusion file",
    )
    require(
        int(
            model.loc[
                model["ready_for_network_linkage"],
                "importer_eligible",
            ].sum()
        )
        == expected_importer_eligible,
        "Importer eligibility does not reconcile to the network summary",
    )
    require(
        int(no_network.sum()) == expected_no_network,
        "Absent-network keys do not reconcile to the network summary",
    )
    require(
        int(observed.sum()) == expected_observed_network,
        "Observed-network keys do not reconcile to the network summary",
    )
    require(
        int(importer_excluded.sum()) == EXPECTED_IMPORTER_EXCLUDED,
        "Importer-exclusion baseline contract changed",
    )
    require(
        int(no_network.sum()) == EXPECTED_NO_NETWORK,
        "Absent-network baseline contract changed",
    )
    require(
        int(observed.sum()) == EXPECTED_OBSERVED_NETWORK,
        "Observed-network baseline contract changed",
    )
    require(
        (model["scope_confidence_class"] == "CONVERSION_REQUIRED").sum() == 1056,
        "Conversion-required population changed",
    )
    require(
        (model["scope_confidence_class"] == "SENSITIVITY_ONLY").sum() == 176,
        "Sensitivity-only population changed",
    )
    require(
        (model["negative_domestic_supply_years"] > 0).sum() == 57,
        "Negative-denominator population changed",
    )
    require(
        not model.loc[
            model["scope_confidence_class"] == "CONVERSION_REQUIRED",
            "governance_approved_for_model",
        ].any(),
        "Conversion-required scope approved",
    )
    require(
        not model.loc[
            model["scope_confidence_class"] == "SENSITIVITY_ONLY",
            "governance_approved_for_model",
        ].any(),
        "Sensitivity-only scope approved",
    )
    require(
        model.loc[
            model["core_food_code"].isin(["CF08", "CF09"]), "analytical_scope_code"
        ].nunique()
        == 4,
        "Subfamilies collapsed",
    )

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    model.to_csv(OUT / "core_food_model_readiness.csv", index=False)
    ledger_columns = KEY + [
        "entity_name",
        "core_food",
        "ready_for_network_linkage",
        "country_technical_gate",
        "country_policy_recommendation",
        "country_governance_decision",
        "country_decision_state",
        "mapping_policy_recommendation",
        "mapping_governance_decision",
        "mapping_decision_state",
        "mapping_effective_decision",
        "fbs_gate",
        "network_year_gate",
        "coverage_gate",
        "coverage_override_decision",
        "model_readiness_status",
        "readiness_authority",
        "model_readiness_issue_flags",
    ]
    model[ledger_columns].to_csv(
        OUT / "core_food_readiness_gate_ledger.csv", index=False
    )
    model.loc[model["model_readiness_status"] == "READY_FOR_PRIMARY_MODEL"].to_csv(
        OUT / "core_food_primary_model_candidates.csv", index=False
    )
    model.loc[
        model["model_readiness_status"].isin(
            {"READY_WITH_LIMITATIONS", "READY_WITH_LIMITATIONS_GOVERNANCE_PENDING"}
        )
    ].to_csv(OUT / "core_food_limited_model_candidates.csv", index=False)
    model.loc[model["model_readiness_status"] == "SENSITIVITY_ONLY"].to_csv(
        OUT / "core_food_sensitivity_candidates.csv", index=False
    )
    model.loc[model["readiness_authority"] == "GOVERNANCE"].to_csv(
        OUT / "core_food_governance_review_queue.csv", index=False
    )
    model.loc[
        (model["readiness_authority"] == "TECHNICAL")
        & ~model["technical_model_candidate"]
    ].to_csv(OUT / "core_food_technical_exclusions.csv", index=False)

    country_base = model[
        [
            "entity_m49",
            "entity_name",
            "country_technical_gate",
            "country_policy_recommendation",
        ]
    ].drop_duplicates()
    country_standard = country_base.loc[
        country_base["country_technical_gate"] == "PASS_OBSERVED_IMPORTER"
    ].copy()
    country_exception = country_base.loc[
        country_base["country_technical_gate"] == "FAIL_NO_BASELINE_IMPORT_OBSERVATION"
    ].copy()
    for queue in [country_standard, country_exception]:
        queue["country_governance_decision"] = ""
        queue["reviewer"] = ""
        queue["review_date"] = ""
        queue["decision_rationale"] = ""
        queue["evidence_reference"] = ""
    country_standard.to_csv(OUT / "country_standard_approval_queue.csv", index=False)
    country_exception.to_csv(OUT / "country_exception_review_queue.csv", index=False)

    scope_lookup = universe[
        ["analytical_scope_code", "scope_confidence_class"]
    ].drop_duplicates()
    mapping_queue = scopes.merge(
        scope_lookup, on="analytical_scope_code", how="left", validate="one_to_one"
    )
    mapping_queue["mapping_policy_recommendation"] = mapping_queue[
        "scope_confidence_class"
    ].map(SCOPE_RECOMMENDATIONS)
    mapping_queue["mapping_governance_decision"] = ""
    mapping_queue["reviewer"] = ""
    mapping_queue["review_date"] = ""
    mapping_queue["decision_rationale"] = ""
    mapping_queue["evidence_reference"] = ""
    mapping_queue.to_csv(OUT / "mapping_review_queue.csv", index=False)
    model.loc[
        model["coverage_gate"].isin(
            {
                "PASS_WITH_LIMITATION_PARTIAL",
                "FAIL_LOW_COVERAGE",
                "FAIL_DENOMINATOR_UNAVAILABLE",
                "REVIEW_ABOVE_FBS",
                "REVIEW_EXTREME",
            }
        )
    ].to_csv(OUT / "coverage_review_queue.csv", index=False)
    model.loc[model["coverage_gate"] == "FAIL_NO_OBSERVED_NETWORK"].to_csv(
        OUT / "no_network_review_queue.csv", index=False
    )

    summary = {
        "dataset": "Core Food enterprise governed model-readiness layer",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": current_commit(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in sources
        },
        "policy_hash": sha256(POLICY_PATH),
        "decision_hashes": {
            str(path.relative_to(ROOT)): sha256(path) if path.exists() else None
            for path in [COUNTRY_DECISIONS, MAPPING_DECISIONS, COVERAGE_DECISIONS]
        },
        "records": len(model),
        "population_funnel": {
            "all_fbs_baselines": len(model),
            "conversion_required": int(
                (model["scope_confidence_class"] == "CONVERSION_REQUIRED").sum()
            ),
            "sensitivity_only": int(
                (model["scope_confidence_class"] == "SENSITIVITY_ONLY").sum()
            ),
            "negative_denominator_data_review": int(
                (model["negative_domestic_supply_years"] > 0).sum()
            ),
            "ready_for_network_linkage": int(model["ready_for_network_linkage"].sum()),
            "importer_exclusions": int(importer_excluded.sum()),
            "importer_eligible": int(model["importer_eligible"].sum()),
            "no_observed_network": int(no_network.sum()),
            "observed_network": int(observed.sum()),
        },
        "status_counts": {
            str(k): int(v)
            for k, v in model["model_readiness_status"].value_counts().items()
        },
        "controls": {
            "all_4048_records_classified_once": True,
            "all_1056_conversion_records_retained_and_blocked": True,
            "all_176_sensitivity_records_retained_outside_primary": True,
            "all_57_negative_denominator_records_retained": True,
            "all_2257_linkage_ready_records_preserved": True,
            "all_219_importer_exclusions_retained": True,
            "all_55_no_network_records_retained": True,
            "all_1983_observed_networks_represented": True,
            "recommendations_separate_from_governance_decisions": True,
            "technical_and_governance_gates_separated": True,
            "coverage_override_cannot_promote_to_primary": True,
            "analytical_subfamilies_separate": True,
            "no_final_score_or_ranking": True,
        },
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD ENTERPRISE MODEL READINESS BUILD COMPLETE")
    print("=" * 72)
    print(f"Complete FBS universe classified: {len(model):,}")
    print(f"Ready for network linkage: {model['ready_for_network_linkage'].sum():,}")
    print(f"Importer exclusions retained: {importer_excluded.sum():,}")
    print(f"Observed networks represented: {observed.sum():,}")
    print(f"No observed network retained: {no_network.sum():,}")
    print("\nReadiness statuses:")
    print(model["model_readiness_status"].value_counts().to_string())
    print("\nNo vulnerability score or final ranking was generated.")
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

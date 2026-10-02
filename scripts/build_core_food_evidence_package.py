#!/usr/bin/env python3
"""Build the governed Core Food presentation evidence package.

This build is deliberately fail closed. A case is included only when its
publication decision, review metadata, and verification flags satisfy the
tracked evidence-package policy.
"""

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
POLICY_PATH = ROOT / "config/model_governance/core_food_evidence_package_policy.json"
DECISIONS_PATH = (
    ROOT / "config/review_decisions/core_food_case_publication_decisions.csv"
)
DECISION_POLICY_PATH = (
    ROOT / "config/model_governance/core_food_decision_support_policy.json"
)

INPUT_DIR = ROOT / "outputs/tables/core_food_decision_support"
COUNTRY_CASES_PATH = INPUT_DIR / "core_food_country_food_case_studies.csv"
SUPPLIER_CASES_PATH = INPUT_DIR / "core_food_supplier_food_case_studies.csv"
RELATIONSHIPS_PATH = INPUT_DIR / "core_food_country_food_supplier_evidence.csv"
INTERVENTIONS_PATH = INPUT_DIR / "core_food_intervention_options.csv"
PUBLICATION_PATH = INPUT_DIR / "core_food_publication_eligibility.csv"
BUILD5_SUMMARY_PATH = (
    ROOT / "outputs/model_results/core_food_decision_support_summary.json"
)

OUTPUT_DIR = ROOT / "outputs/tables/core_food_evidence_package"
MODEL_DIR = ROOT / "outputs/model_results"
PRESENTATION_DIR = ROOT / "outputs/presentation"
SUMMARY_PATH = MODEL_DIR / "core_food_evidence_package_summary.json"

CASE_KEY = ["case_type", "entity_m49", "analytical_scope_code"]
COUNTRY_KEY = ["importer_m49", "analytical_scope_code"]
SUPPLIER_KEY = ["exporter_m49", "analytical_scope_code"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False, **kwargs)


def bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def nonblank(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().ne("")


def empty_like(data: pd.DataFrame, extra: dict[str, str] | None = None) -> pd.DataFrame:
    result = data.iloc[0:0].copy()
    for column, dtype in (extra or {}).items():
        result[column] = pd.Series(dtype=dtype)
    return result


def write_csv(data: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    data.to_csv(path, index=False)
    return path


def make_gate_results(decisions: pd.DataFrame, approved: pd.Series) -> pd.DataFrame:
    result = decisions[CASE_KEY + ["review_status", "publication_decision"]].copy()
    result["reviewer_identity_present"] = nonblank(decisions["reviewer_name"])
    result["review_date_present"] = nonblank(decisions["review_date"])
    result["review_rationale_present"] = nonblank(decisions["review_rationale"])
    result["display_name_present"] = nonblank(decisions["approved_display_name"])
    result["narrative_scope_present"] = nonblank(decisions["approved_narrative_scope"])
    result["evidence_verified"] = bool_series(decisions["evidence_verified"])
    result["prohibited_claims_verified"] = bool_series(
        decisions["prohibited_claims_verified"]
    )
    result["publication_gate_passed"] = approved

    reasons: list[str] = []
    for index in decisions.index:
        failures: list[str] = []
        row = decisions.loc[index]
        if row["review_status"] != "REVIEW_COMPLETE":
            failures.append("REVIEW_NOT_COMPLETE")
        if row["publication_decision"] not in {
            "APPROVED_FOR_INTERNAL_PRESENTATION",
            "APPROVED_FOR_EXTERNAL_PRESENTATION",
        }:
            failures.append("DECISION_NOT_PUBLISHABLE")
        for column, code in [
            ("reviewer_name", "REVIEWER_MISSING"),
            ("review_date", "REVIEW_DATE_MISSING"),
            ("review_rationale", "RATIONALE_MISSING"),
            ("approved_display_name", "DISPLAY_NAME_MISSING"),
            ("approved_narrative_scope", "NARRATIVE_SCOPE_MISSING"),
        ]:
            if not str(row[column]).strip():
                failures.append(code)
        if not bool_series(pd.Series([row["evidence_verified"]])).iloc[0]:
            failures.append("EVIDENCE_NOT_VERIFIED")
        if not bool_series(pd.Series([row["prohibited_claims_verified"]])).iloc[0]:
            failures.append("PROHIBITED_CLAIMS_NOT_VERIFIED")
        reasons.append("PASS" if not failures else "|".join(failures))
    result["publication_gate_reason"] = reasons
    return result


def build_markdown(
    approved_country: pd.DataFrame,
    approved_supplier: pd.DataFrame,
    approved_interventions: pd.DataFrame,
) -> None:
    methodology = """# Core Food Methodology Summary\n\nThis evidence package is derived from the governed 2021–2023 Core Food analytical pipeline. It uses stable developmental country-food signals, observed immediate trade-partner relationships, supplier-food systemic-reach signals, and documented analyst publication decisions. It does not create a new model or official ranking.\n"""
    limitations = """# Core Food Limitations Summary\n\n- Supplier relationships represent observed immediate trade partners, not agricultural origin.\n- Static removal tests assume no substitution, inventory, price, logistics, policy, production, consumer, or rerouting response.\n- Developmental signals are not failure probabilities or causal disruption estimates.\n- Intervention categories are hypotheses for analyst review, not implementation recommendations.\n- No official country or supplier ranking is generated.\n"""

    lines = ["# Approved Core Food Case Briefs", ""]
    if approved_country.empty and approved_supplier.empty:
        lines.extend(
            [
                "No cases are currently approved for presentation.",
                "",
                "The publication gate is operating in fail-closed mode.",
            ]
        )
    else:
        if not approved_country.empty:
            lines.extend(["## Country-Food Cases", ""])
            for _, row in approved_country.iterrows():
                name = row.get(
                    "approved_display_name", row.get("entity_name", "Approved case")
                )
                food = row.get("core_food", row.get("analytical_scope_code", ""))
                scope = row.get("approved_narrative_scope", "")
                lines.extend([f"### {name}: {food}", "", str(scope), ""])
        if not approved_supplier.empty:
            lines.extend(["## Supplier-Food Cases", ""])
            for _, row in approved_supplier.iterrows():
                name = row.get(
                    "approved_display_name", row.get("exporter_name", "Approved case")
                )
                food = row.get("core_food", row.get("analytical_scope_code", ""))
                scope = row.get("approved_narrative_scope", "")
                lines.extend([f"### {name}: {food}", "", str(scope), ""])

    outline = f"""# Core Food Presentation Outline\n\n1. Purpose and governance\n2. Data period and analytical population\n3. Methodology and stability testing\n4. Approved country-food cases: {len(approved_country):,}\n5. Approved supplier-food cases: {len(approved_supplier):,}\n6. Approved intervention hypotheses: {len(approved_interventions):,}\n7. Limitations and prohibited claims\n8. Next review decisions\n"""

    (PRESENTATION_DIR / "core_food_methodology_summary.md").write_text(
        methodology, encoding="utf-8"
    )
    (PRESENTATION_DIR / "core_food_limitations_summary.md").write_text(
        limitations, encoding="utf-8"
    )
    (PRESENTATION_DIR / "core_food_case_briefs.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    (PRESENTATION_DIR / "core_food_presentation_outline.md").write_text(
        outline, encoding="utf-8"
    )


def main() -> None:
    for directory in [OUTPUT_DIR, MODEL_DIR, PRESENTATION_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    required_paths = [
        POLICY_PATH,
        DECISIONS_PATH,
        DECISION_POLICY_PATH,
        COUNTRY_CASES_PATH,
        SUPPLIER_CASES_PATH,
        RELATIONSHIPS_PATH,
        INTERVENTIONS_PATH,
        PUBLICATION_PATH,
        BUILD5_SUMMARY_PATH,
    ]
    for path in required_paths:
        require(path.exists(), f"Required input missing: {path}")

    policy = read_json(POLICY_PATH)
    decision_policy = read_json(DECISION_POLICY_PATH)
    build5_summary = read_json(BUILD5_SUMMARY_PATH)

    require(policy["policy_id"] == "core-food-evidence-package", "Unexpected policy")
    require(
        policy["input_decision_support_policy_id"] == decision_policy["policy_id"],
        "Decision-support policy contract mismatch",
    )
    require(all(build5_summary["controls"].values()), "Build 5 controls are not valid")

    decisions = read_csv(DECISIONS_PATH, dtype={"entity_m49": "string"})
    country = read_csv(COUNTRY_CASES_PATH, dtype={"importer_m49": "string"})
    supplier = read_csv(SUPPLIER_CASES_PATH, dtype={"exporter_m49": "string"})
    relationships = read_csv(
        RELATIONSHIPS_PATH,
        dtype={"importer_m49": "string", "exporter_m49": "string"},
    )
    interventions = read_csv(INTERVENTIONS_PATH, dtype={"importer_m49": "string"})
    publication = read_csv(PUBLICATION_PATH, dtype={"entity_m49": "string"})

    require(len(decisions) == 426, "Expected 426 publication decisions")
    require(not decisions.duplicated(CASE_KEY).any(), "Decision keys are not unique")
    require(
        set(decisions["review_status"]) <= set(policy["allowed_review_statuses"]),
        "Invalid review status",
    )
    require(
        set(decisions["publication_decision"])
        <= set(policy["allowed_publication_decisions"]),
        "Invalid publication decision",
    )

    eligible_keys = publication.loc[
        bool_series(publication["publication_eligible"]),
        CASE_KEY + ["sensitivity_only"],
    ].copy()
    require(len(eligible_keys) == 426, "Build 5 eligible population does not reconcile")
    merged = decisions.merge(
        eligible_keys, on=CASE_KEY, how="left", validate="one_to_one"
    )
    require(
        merged["sensitivity_only"].ne("").all(),
        "Decision key is absent from Build 5 eligibility",
    )

    publishable = merged["publication_decision"].isin(policy["publishable_decisions"])
    approved = (
        merged["review_status"].eq("REVIEW_COMPLETE")
        & publishable
        & nonblank(merged["reviewer_name"])
        & nonblank(merged["review_date"])
        & nonblank(merged["review_rationale"])
        & nonblank(merged["approved_display_name"])
        & nonblank(merged["approved_narrative_scope"])
        & bool_series(merged["evidence_verified"])
        & bool_series(merged["prohibited_claims_verified"])
        & ~bool_series(merged["sensitivity_only"])
    )

    gate_results = make_gate_results(merged, approved)
    approved_decisions = merged.loc[approved].copy()

    country_decisions = approved_decisions.loc[
        approved_decisions["case_type"].eq("COUNTRY_FOOD")
    ].rename(columns={"entity_m49": "importer_m49"})
    supplier_decisions = approved_decisions.loc[
        approved_decisions["case_type"].eq("SUPPLIER_FOOD")
    ].rename(columns={"entity_m49": "exporter_m49"})

    approved_country = country.merge(
        country_decisions.drop(columns=["case_type", "sensitivity_only"]),
        on=COUNTRY_KEY,
        how="inner",
        validate="one_to_one",
    )
    approved_supplier = supplier.merge(
        supplier_decisions.drop(columns=["case_type", "sensitivity_only"]),
        on=SUPPLIER_KEY,
        how="inner",
        validate="one_to_one",
    )

    approved_relationships = relationships.merge(
        approved_country[COUNTRY_KEY],
        on=COUNTRY_KEY,
        how="inner",
        validate="many_to_one",
    )
    approved_interventions = interventions.merge(
        approved_country[COUNTRY_KEY],
        on=COUNTRY_KEY,
        how="inner",
        validate="one_to_one",
    )

    if not approved_relationships.empty:
        sums = approved_relationships.groupby(COUNTRY_KEY)[
            "pooled_supplier_share"
        ].sum()
        require(
            np.allclose(sums.to_numpy(), 1.0, atol=1e-10),
            "Approved relationship shares do not reconcile",
        )

    country_chart = approved_country.copy()
    supplier_chart = approved_supplier.copy()

    country_nodes = approved_country.assign(
        node_id=lambda x: (
            "IMPORTER:"
            + x["importer_m49"].astype(str)
            + ":"
            + x["analytical_scope_code"]
        ),
        node_type="COUNTRY_FOOD",
    )
    supplier_nodes = approved_supplier.assign(
        node_id=lambda x: (
            "SUPPLIER:"
            + x["exporter_m49"].astype(str)
            + ":"
            + x["analytical_scope_code"]
        ),
        node_type="SUPPLIER_FOOD",
    )
    node_columns = ["node_id", "node_type", "analytical_scope_code"]
    network_nodes = pd.concat(
        [country_nodes[node_columns], supplier_nodes[node_columns]], ignore_index=True
    ).drop_duplicates("node_id")

    network_edges = approved_relationships.copy()
    if not network_edges.empty:
        network_edges["source_node_id"] = (
            "SUPPLIER:"
            + network_edges["exporter_m49"].astype(str)
            + ":"
            + network_edges["analytical_scope_code"]
        )
        network_edges["target_node_id"] = (
            "IMPORTER:"
            + network_edges["importer_m49"].astype(str)
            + ":"
            + network_edges["analytical_scope_code"]
        )
        network_edges["edge_interpretation"] = "IMMEDIATE_TRADE_PARTNER"
        network_edges["agricultural_origin_inferred"] = False

    brief_registry = approved_decisions[
        CASE_KEY
        + [
            "publication_decision",
            "reviewer_name",
            "review_date",
            "approved_display_name",
            "approved_narrative_scope",
            "additional_limitations",
        ]
    ].copy()
    brief_registry["result_classification"] = policy["result_classification"]

    source_paths = [
        POLICY_PATH,
        DECISIONS_PATH,
        DECISION_POLICY_PATH,
        COUNTRY_CASES_PATH,
        SUPPLIER_CASES_PATH,
        RELATIONSHIPS_PATH,
        INTERVENTIONS_PATH,
        PUBLICATION_PATH,
        BUILD5_SUMMARY_PATH,
    ]
    source_registry = pd.DataFrame(
        {
            "source_path": [str(path.relative_to(ROOT)) for path in source_paths],
            "sha256": [sha256(path) for path in source_paths],
        }
    )

    metrics = pd.DataFrame(
        [
            ("governed_candidates", len(decisions)),
            ("approved_country_food_cases", len(approved_country)),
            ("approved_supplier_food_cases", len(approved_supplier)),
            ("approved_relationship_evidence_rows", len(approved_relationships)),
            ("approved_intervention_hypotheses", len(approved_interventions)),
            ("held_or_unapproved_cases", int((~approved).sum())),
        ],
        columns=["metric", "value"],
    )

    checks = pd.DataFrame(
        [
            (
                "DECISION_KEYS_UNIQUE",
                not decisions.duplicated(CASE_KEY).any(),
                f"Rows={len(decisions)}",
            ),
            ("ALL_BUILD5_CASES_RECONCILED", len(merged) == 426, f"Rows={len(merged)}"),
            (
                "UNREVIEWED_EXCLUDED",
                not approved[merged["review_status"].ne("REVIEW_COMPLETE")].any(),
                "Fail closed",
            ),
            (
                "HOLD_EXCLUDED",
                not approved[merged["publication_decision"].eq("HOLD")].any(),
                "Fail closed",
            ),
            (
                "REJECTED_EXCLUDED",
                not approved[merged["publication_decision"].eq("REJECTED")].any(),
                "Fail closed",
            ),
            (
                "EVIDENCE_VERIFICATION_REQUIRED",
                not approved[~bool_series(merged["evidence_verified"])].any(),
                "Required",
            ),
            (
                "CLAIMS_VERIFICATION_REQUIRED",
                not approved[~bool_series(merged["prohibited_claims_verified"])].any(),
                "Required",
            ),
            (
                "SENSITIVITY_ONLY_EXCLUDED",
                not approved[bool_series(merged["sensitivity_only"])].any(),
                "Required",
            ),
            (
                "NO_OFFICIAL_COUNTRY_RANKING",
                not policy["official_country_ranking_enabled"],
                "Disabled",
            ),
            (
                "NO_OFFICIAL_SUPPLIER_RANKING",
                not policy["official_supplier_ranking_enabled"],
                "Disabled",
            ),
            (
                "NO_AGRICULTURAL_ORIGIN_INFERENCE",
                not policy["agricultural_origin_inference_allowed"],
                "Disabled",
            ),
            (
                "NO_INTERVENTION_EFFECTIVENESS_CLAIM",
                not policy["intervention_effectiveness_claims_allowed"],
                "Disabled",
            ),
        ],
        columns=["check_id", "passed", "details"],
    )
    require(checks["passed"].all(), "Evidence-package quality checks failed")

    outputs: dict[str, Path] = {}
    outputs["metrics"] = write_csv(metrics, "core_food_executive_summary_metrics.csv")
    outputs["country_cases"] = write_csv(
        approved_country, "core_food_approved_country_food_cases.csv"
    )
    outputs["supplier_cases"] = write_csv(
        approved_supplier, "core_food_approved_supplier_food_cases.csv"
    )
    outputs["relationships"] = write_csv(
        approved_relationships, "core_food_approved_relationship_evidence.csv"
    )
    outputs["interventions"] = write_csv(
        approved_interventions, "core_food_approved_intervention_hypotheses.csv"
    )
    outputs["country_chart"] = write_csv(
        country_chart, "core_food_country_food_chart_data.csv"
    )
    outputs["supplier_chart"] = write_csv(
        supplier_chart, "core_food_supplier_food_chart_data.csv"
    )
    outputs["network_nodes"] = write_csv(network_nodes, "core_food_network_nodes.csv")
    outputs["network_edges"] = write_csv(network_edges, "core_food_network_edges.csv")
    outputs["brief_registry"] = write_csv(
        brief_registry, "core_food_case_brief_registry.csv"
    )
    outputs["source_registry"] = write_csv(
        source_registry, "core_food_source_registry.csv"
    )
    outputs["gate_results"] = write_csv(
        gate_results, "core_food_publication_gate_results.csv"
    )
    outputs["quality_checks"] = write_csv(
        checks, "core_food_evidence_package_quality_checks.csv"
    )

    build_markdown(approved_country, approved_supplier, approved_interventions)

    summary = {
        "dataset": "Core Food governed presentation evidence package",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_head(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in source_paths
        },
        "evidence_package_policy_hash": sha256(POLICY_PATH),
        "authoritative_years": policy["authoritative_years"],
        "governed_candidate_rows": len(decisions),
        "approved_country_food_cases": len(approved_country),
        "approved_supplier_food_cases": len(approved_supplier),
        "approved_relationship_rows": len(approved_relationships),
        "approved_intervention_rows": len(approved_interventions),
        "held_or_unapproved_cases": int((~approved).sum()),
        "publication_gate_fail_closed": len(approved_decisions) == 0
        if decisions["publication_decision"].eq("HOLD").all()
        else True,
        "controls": dict(zip(checks["check_id"], checks["passed"], strict=True)),
        "outputs": {key: str(path.relative_to(ROOT)) for key, path in outputs.items()},
    }
    with SUMMARY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print("=" * 72)
    print("CORE FOOD EVIDENCE PACKAGE BUILD COMPLETE")
    print("=" * 72)
    print(f"Governed candidates: {len(decisions):,}")
    print(f"Approved country-food cases: {len(approved_country):,}")
    print(f"Approved supplier-food cases: {len(approved_supplier):,}")
    print(f"Approved relationship rows: {len(approved_relationships):,}")
    print(f"Approved intervention hypotheses: {len(approved_interventions):,}")
    print(f"Cases held or unapproved: {(~approved).sum():,}")
    print(
        "No official ranking, origin inference, forecast, or effectiveness claim was generated."
    )
    print(f"Report: {SUMMARY_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

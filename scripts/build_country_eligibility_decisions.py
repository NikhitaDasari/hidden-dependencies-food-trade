from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = (
    ROOT / "outputs/tables/core_food_country_foundation/"
    "country_eligibility_candidates.csv"
)
OUTPUT_DIR = ROOT / "outputs/tables/core_food_country_foundation"
DECISIONS_PATH = OUTPUT_DIR / "country_eligibility_decisions.csv"
RANKING_PATH = OUTPUT_DIR / "country_ranking_universe.csv"
SUPPLIER_PATH = OUTPUT_DIR / "supplier_role_universe.csv"
EXCLUSIONS_PATH = OUTPUT_DIR / "country_eligibility_exclusions.csv"
SOURCE_ONLY_PATH = OUTPUT_DIR / "source_only_entity_review.csv"
REVIEW_PATH = OUTPUT_DIR / "country_territory_manual_review.csv"
REPORT_PATH = ROOT / "outputs/model_results/country_eligibility_decisions_summary.json"


def apply_decision(row: pd.Series) -> pd.Series:
    match_method = row["match_method"]
    candidate_status = row["eligibility_status_candidate"]
    candidate_type = row["entity_type_candidate"]

    result = {
        "final_entity_type": "",
        "final_eligibility_status": "PENDING_MANUAL_REVIEW",
        "eligible_for_country_ranking": False,
        "eligible_for_supplier_role": False,
        "has_usable_fbs_entity": pd.notna(row["fbs_area_code"]),
        "has_observed_trade_entity": pd.notna(row["trade_area_code"]),
        "decision_is_final": False,
        "review_priority": "STANDARD",
        "blocking_reason": "COUNTRY_VERSUS_TERRITORY_REVIEW",
        "review_method": "AUTOMATED_CANDIDATE_TRIAGE",
        "decision_notes": "",
    }

    if candidate_status == "EXCLUDE_AGGREGATE" or candidate_type == "aggregate":
        result.update(
            {
                "final_entity_type": "aggregate",
                "final_eligibility_status": "EXCLUDE_AGGREGATE",
                "eligible_for_country_ranking": False,
                "eligible_for_supplier_role": False,
                "decision_is_final": True,
                "review_priority": "COMPLETE",
                "blocking_reason": "",
                "review_method": "FAOSTAT_AGGREGATE_CODE_AND_NAME_RULE",
                "decision_notes": "Aggregate excluded from importer rankings and supplier roles.",
            }
        )
        return pd.Series(result)

    if (
        candidate_status == "EXCLUDE_HISTORICAL"
        or candidate_type == "historical_entity"
    ):
        result.update(
            {
                "final_entity_type": "historical_entity",
                "final_eligibility_status": "EXCLUDE_HISTORICAL",
                "eligible_for_country_ranking": False,
                "eligible_for_supplier_role": False,
                "decision_is_final": True,
                "review_priority": "COMPLETE",
                "blocking_reason": "",
                "review_method": "HISTORICAL_ENTITY_RULE",
                "decision_notes": "Historical entity excluded from the 2021-2023 baseline.",
            }
        )
        return pd.Series(result)

    if match_method == "M49_EXACT":
        result.update(
            {
                "final_entity_type": "country_or_territory_pending",
                "final_eligibility_status": "PROVISIONAL_MATCHED_ENTITY",
                "eligible_for_supplier_role": True,
                "review_priority": "HIGH",
                "blocking_reason": "COUNTRY_VERSUS_TERRITORY_REVIEW",
                "decision_notes": (
                    "Exact M49 match across trade and Food Balances. Supplier role is "
                    "provisionally usable; importer ranking remains blocked pending entity review."
                ),
            }
        )
        return pd.Series(result)

    if match_method == "TRADE_ONLY":
        result.update(
            {
                "final_entity_type": "trade_entity_pending",
                "final_eligibility_status": "TRADE_ONLY_REVIEW",
                "eligible_for_supplier_role": True,
                "review_priority": "CRITICAL",
                "blocking_reason": "NO_MATCHED_FBS_ENTITY",
                "decision_notes": (
                    "Trade entity may remain an immediate supplier. Country ranking is blocked "
                    "until a compatible Food Balance entity or documented crosswalk is found."
                ),
            }
        )
        return pd.Series(result)

    if match_method == "FBS_ONLY":
        result.update(
            {
                "final_entity_type": "fbs_entity_pending",
                "final_eligibility_status": "FBS_ONLY_REVIEW",
                "eligible_for_supplier_role": False,
                "review_priority": "CRITICAL",
                "blocking_reason": "NO_OBSERVED_TRADE_ENTITY",
                "decision_notes": (
                    "Food Balance entity may support reliance calculations, but observed supplier "
                    "network metrics are unavailable until trade coverage is resolved."
                ),
            }
        )
        return pd.Series(result)

    result.update(
        {
            "final_entity_type": "unmatched",
            "final_eligibility_status": "UNMATCHED_REVIEW",
            "review_priority": "CRITICAL",
            "blocking_reason": "UNRESOLVED_ENTITY_MATCH",
        }
    )
    return pd.Series(result)


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(INPUT_PATH)

    candidates = pd.read_csv(INPUT_PATH, dtype={"entity_m49": "string"})
    if candidates.empty:
        raise ValueError("Country eligibility candidate file is empty")
    if candidates["entity_m49"].duplicated().any():
        duplicates = candidates.loc[
            candidates["entity_m49"].duplicated(False),
            ["entity_m49", "entity_name", "match_method"],
        ]
        raise ValueError(
            "Duplicate entity M49 values found:\n" + duplicates.to_string(index=False)
        )

    decision_columns = candidates.apply(apply_decision, axis=1)
    drop_existing = [
        column for column in decision_columns.columns if column in candidates.columns
    ]
    decisions = pd.concat(
        [candidates.drop(columns=drop_existing), decision_columns], axis=1
    )

    # Guardrails: no importer ranking is approved in this triage stage.
    if decisions["eligible_for_country_ranking"].any():
        raise ValueError("An importer-ranking entity was approved before manual review")
    if decisions.loc[
        decisions["final_entity_type"].eq("aggregate"),
        "eligible_for_supplier_role",
    ].any():
        raise ValueError("An aggregate was approved for a supplier role")
    if not decisions.loc[
        decisions["final_entity_type"].eq("aggregate"), "decision_is_final"
    ].all():
        raise ValueError("Aggregate decisions were not finalized")

    decisions = decisions.sort_values(
        ["decision_is_final", "review_priority", "entity_name"],
        ascending=[True, True, True],
        na_position="last",
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(DECISIONS_PATH, index=False)

    ranking = decisions.loc[decisions["eligible_for_country_ranking"],].copy()
    ranking.to_csv(RANKING_PATH, index=False)

    suppliers = decisions.loc[decisions["eligible_for_supplier_role"],].copy()
    suppliers.to_csv(SUPPLIER_PATH, index=False)

    exclusions = decisions.loc[
        decisions["final_eligibility_status"].str.startswith("EXCLUDE_"),
    ].copy()
    exclusions.to_csv(EXCLUSIONS_PATH, index=False)

    source_only = decisions.loc[
        decisions["match_method"].isin(["TRADE_ONLY", "FBS_ONLY"]),
    ].copy()
    source_only.to_csv(SOURCE_ONLY_PATH, index=False)

    review = decisions.loc[~decisions["decision_is_final"]].copy()
    review.to_csv(REVIEW_PATH, index=False)

    report = {
        "dataset": "Country eligibility decision triage",
        "total_entities": len(decisions),
        "finalized_exclusions": int(decisions["decision_is_final"].sum()),
        "pending_manual_review": int((~decisions["decision_is_final"]).sum()),
        "country_ranking_universe_rows": len(ranking),
        "provisional_supplier_role_rows": len(suppliers),
        "source_only_review_rows": len(source_only),
        "status_counts": {
            str(key): int(value)
            for key, value in decisions["final_eligibility_status"]
            .value_counts()
            .items()
        },
        "guardrails": {
            "country_rankings_auto_approved": 0,
            "aggregates_allowed_as_suppliers": 0,
            "supplier_role_is_independent_of_country_ranking": True,
        },
        "outputs": {
            "decisions": str(DECISIONS_PATH.relative_to(ROOT)),
            "country_ranking_universe": str(RANKING_PATH.relative_to(ROOT)),
            "supplier_role_universe": str(SUPPLIER_PATH.relative_to(ROOT)),
            "exclusions": str(EXCLUSIONS_PATH.relative_to(ROOT)),
            "source_only_review": str(SOURCE_ONLY_PATH.relative_to(ROOT)),
            "manual_review": str(REVIEW_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("COUNTRY ELIGIBILITY DECISION TRIAGE COMPLETE")
    print("=" * 72)
    print(f"Total entities: {len(decisions):,}")
    print(f"Finalized exclusions: {report['finalized_exclusions']:,}")
    print(f"Pending manual review: {report['pending_manual_review']:,}")
    print(f"Country ranking universe: {len(ranking):,}")
    print(f"Provisional supplier-role universe: {len(suppliers):,}")
    print(f"Source-only review: {len(source_only):,}")
    print("\nDecision statuses:")
    print(decisions["final_eligibility_status"].value_counts().to_string())
    print("\nNo country was approved for ranking in this triage stage.")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

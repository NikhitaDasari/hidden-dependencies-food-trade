from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRADE_ROOT = ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported"
DB_PATH = ROOT / "data/processed/food_balances.duckdb"
CANDIDATES_PATH = (
    ROOT / "outputs/tables/core_food_country_foundation/"
    "country_eligibility_candidates.csv"
)
DECISIONS_PATH = (
    ROOT / "outputs/tables/core_food_country_foundation/"
    "country_eligibility_decisions.csv"
)
OUTPUT_DIR = ROOT / "outputs/tables/core_food_country_foundation"
UNIFIED_PATH = OUTPUT_DIR / "unified_geography_capability.csv"
IMPORTER_PATH = OUTPUT_DIR / "provisional_importer_network_universe.csv"
SUPPLIER_PATH = OUTPUT_DIR / "provisional_exporter_supplier_universe.csv"
FBS_PATH = OUTPUT_DIR / "provisional_fbs_reliance_universe.csv"
HIERARCHY_PATH = OUTPUT_DIR / "geographic_hierarchy_review.csv"
SOURCE_GAPS_PATH = OUTPUT_DIR / "unified_source_coverage_gaps.csv"
MANUAL_REVIEW_PATH = OUTPUT_DIR / "unified_geography_manual_review.csv"
REPORT_PATH = ROOT / "outputs/model_results/unified_geography_capability_summary.json"

BASELINE_START = 2021
BASELINE_END = 2023

# Explicit conservative overrides. All other nonaggregate entities remain pending.
KNOWN_TERRITORIES = {
    "344": ("Hong Kong SAR", "159"),
    "446": ("Macao SAR", "159"),
    "258": ("French Polynesia", "250"),
    "540": ("New Caledonia", "250"),
}
COMPOSITE_GEOGRAPHIES = {
    "159": {
        "name": "China",
        "components": ["156", "158", "344", "446"],
        "reason": "Composite China geography potentially overlaps component economies.",
    }
}


def normalize_m49(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace("'", "")
    text = text.removesuffix(".0")
    digits = re.sub(r"\D", "", text)
    return digits.zfill(3) if digits else None


def coalesce_text(*values: object) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return ""


def load_trade_roles() -> pd.DataFrame:
    parquet_files = list(TRADE_ROOT.rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files under {TRADE_ROOT}")

    connection = duckdb.connect()
    glob_path = str(TRADE_ROOT / "**/*.parquet")
    importer = connection.execute(
        f"""
        SELECT
            importer_code AS role_area_code,
            importer_m49 AS role_m49,
            importer AS role_area,
            COUNT(*) AS importer_rows,
            COUNT(*) FILTER (
                WHERE year BETWEEN {BASELINE_START} AND {BASELINE_END}
            ) AS importer_baseline_rows,
            COUNT(DISTINCT item_code) AS importer_items,
            MIN(year) AS importer_first_year,
            MAX(year) AS importer_latest_year
        FROM read_parquet('{glob_path}', union_by_name = true)
        GROUP BY importer_code, importer_m49, importer
        """
    ).fetchdf()
    exporter = connection.execute(
        f"""
        SELECT
            exporter_code AS role_area_code,
            exporter_m49 AS role_m49,
            exporter AS role_area,
            COUNT(*) AS exporter_rows,
            COUNT(*) FILTER (
                WHERE year BETWEEN {BASELINE_START} AND {BASELINE_END}
            ) AS exporter_baseline_rows,
            COUNT(DISTINCT item_code) AS exporter_items,
            MIN(year) AS exporter_first_year,
            MAX(year) AS exporter_latest_year
        FROM read_parquet('{glob_path}', union_by_name = true)
        GROUP BY exporter_code, exporter_m49, exporter
        """
    ).fetchdf()
    connection.close()

    importer["entity_m49"] = importer["role_m49"].map(normalize_m49)
    exporter["entity_m49"] = exporter["role_m49"].map(normalize_m49)

    imp_dupes = importer["entity_m49"].dropna().duplicated().any()
    exp_dupes = exporter["entity_m49"].dropna().duplicated().any()
    if imp_dupes or exp_dupes:
        raise ValueError("Duplicate normalized M49 identifiers within a trade role")

    importer = importer.rename(
        columns={
            "role_area_code": "importer_area_code",
            "role_m49": "importer_m49_raw",
            "role_area": "importer_area",
        }
    )
    exporter = exporter.rename(
        columns={
            "role_area_code": "exporter_area_code",
            "role_m49": "exporter_m49_raw",
            "role_area": "exporter_area",
        }
    )
    return importer.merge(exporter, on="entity_m49", how="outer", validate="one_to_one")


def load_fbs_entities() -> pd.DataFrame:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    frame = connection.execute(
        f"""
        SELECT
            "Area Code" AS fbs_area_code,
            "Area Code (M49)" AS fbs_m49_raw,
            "Area" AS fbs_area,
            COUNT(*) AS fbs_rows,
            COUNT(*) FILTER (
                WHERE "Year" BETWEEN {BASELINE_START} AND {BASELINE_END}
            ) AS fbs_baseline_rows,
            COUNT(*) FILTER (WHERE "Element Code" = 5611) AS fbs_import_rows,
            COUNT(*) FILTER (WHERE "Element Code" = 5301) AS fbs_domestic_supply_rows,
            MIN("Year") AS fbs_first_year,
            MAX("Year") AS fbs_latest_year
        FROM main.food_balances
        GROUP BY "Area Code", "Area Code (M49)", "Area"
        """
    ).fetchdf()
    connection.close()
    frame["entity_m49"] = frame["fbs_m49_raw"].map(normalize_m49)
    if frame["entity_m49"].dropna().duplicated().any():
        raise ValueError("Duplicate normalized M49 identifiers in Food Balances")
    return frame


def main() -> None:
    for path in [CANDIDATES_PATH, DECISIONS_PATH]:
        if not path.exists():
            raise FileNotFoundError(path)

    candidates = pd.read_csv(CANDIDATES_PATH, dtype={"entity_m49": "string"})
    decisions = pd.read_csv(DECISIONS_PATH, dtype={"entity_m49": "string"})
    trade = load_trade_roles()
    fbs = load_fbs_entities()

    base = trade.merge(fbs, on="entity_m49", how="outer", validate="one_to_one")
    candidate_columns = [
        "entity_m49",
        "entity_name",
        "entity_type_candidate",
        "eligibility_status_candidate",
        "match_method",
    ]
    base = base.merge(
        candidates[candidate_columns],
        on="entity_m49",
        how="outer",
        validate="one_to_one",
    )
    decision_columns = [
        "entity_m49",
        "final_entity_type",
        "final_eligibility_status",
        "decision_is_final",
    ]
    base = base.merge(
        decisions[decision_columns], on="entity_m49", how="outer", validate="one_to_one"
    )

    base["entity_name"] = base.apply(
        lambda row: coalesce_text(
            row.get("entity_name"),
            row.get("fbs_area"),
            row.get("importer_area"),
            row.get("exporter_area"),
        ),
        axis=1,
    )
    base["observed_as_importer"] = base["importer_area_code"].notna()
    base["observed_as_exporter"] = base["exporter_area_code"].notna()
    base["has_fbs_entity"] = base["fbs_area_code"].notna()
    base["has_baseline_importer_rows"] = base["importer_baseline_rows"].fillna(0).gt(0)
    base["has_baseline_exporter_rows"] = base["exporter_baseline_rows"].fillna(0).gt(0)
    base["has_baseline_fbs_rows"] = base["fbs_baseline_rows"].fillna(0).gt(0)

    fbs_code = base["fbs_area_code"].fillna(0).astype(int)
    base["is_aggregate"] = base["eligibility_status_candidate"].eq(
        "EXCLUDE_AGGREGATE"
    ) | fbs_code.between(5000, 5999)
    base["is_historical"] = base["eligibility_status_candidate"].eq(
        "EXCLUDE_HISTORICAL"
    )
    base["is_composite_geography"] = base["entity_m49"].isin(COMPOSITE_GEOGRAPHIES)
    base["entity_type"] = "country_or_territory_pending"
    base.loc[base["is_aggregate"], "entity_type"] = "aggregate"
    base.loc[base["is_historical"], "entity_type"] = "historical_entity"
    base.loc[base["is_composite_geography"], "entity_type"] = "composite_geography"

    base["geographic_parent_m49"] = ""
    base["geographic_parent_name"] = ""
    base["hierarchy_status"] = "NO_KNOWN_HIERARCHY_CONFLICT"
    for m49, (label, parent_m49) in KNOWN_TERRITORIES.items():
        mask = base["entity_m49"].eq(m49)
        base.loc[mask, "entity_type"] = "territory"
        base.loc[mask, "geographic_parent_m49"] = parent_m49
        base.loc[mask, "geographic_parent_name"] = (
            "China" if parent_m49 == "159" else "France"
        )
        base.loc[mask, "hierarchy_status"] = "TERRITORY_RETAIN_SEPARATELY"
        base.loc[mask, "entity_name"] = base.loc[mask, "entity_name"].replace("", label)

    base["overlap_group"] = ""
    for m49, details in COMPOSITE_GEOGRAPHIES.items():
        mask = base["entity_m49"].eq(m49)
        base.loc[mask, "hierarchy_status"] = "POTENTIAL_OVERLAP"
        base.loc[mask, "overlap_group"] = "|".join(details["components"])

    base["ranking_scope_candidate"] = "COUNTRIES_AND_TERRITORIES"
    base["eligible_for_economy_ranking"] = False
    base["eligible_for_supplier_role"] = (
        base["observed_as_exporter"]
        & base["has_baseline_exporter_rows"]
        & ~base["is_aggregate"]
        & ~base["is_historical"]
        & ~base["is_composite_geography"]
    )
    base["eligible_for_importer_network"] = (
        base["observed_as_importer"]
        & base["has_baseline_importer_rows"]
        & ~base["is_aggregate"]
        & ~base["is_historical"]
        & ~base["is_composite_geography"]
    )
    base["eligible_for_fbs_reliance_candidate"] = (
        base["has_fbs_entity"]
        & base["has_baseline_fbs_rows"]
        & ~base["is_aggregate"]
        & ~base["is_historical"]
        & ~base["is_composite_geography"]
    )
    base["eligible_for_complete_vulnerability_profile"] = False

    base["supplier_relationship_type"] = "IMMEDIATE_TRADE_PARTNER"
    base["agricultural_origin_known"] = False
    base["origin_inference_prohibited"] = True

    base["capability_status"] = "MANUAL_ENTITY_REVIEW_REQUIRED"
    base.loc[base["is_aggregate"], "capability_status"] = "EXCLUDED_AGGREGATE"
    base.loc[base["is_historical"], "capability_status"] = "EXCLUDED_HISTORICAL"
    base.loc[base["is_composite_geography"], "capability_status"] = (
        "GEOGRAPHIC_HIERARCHY_REVIEW"
    )
    base.loc[
        ~base["is_aggregate"]
        & ~base["is_historical"]
        & ~base["is_composite_geography"]
        & base["observed_as_importer"]
        & base["observed_as_exporter"]
        & base["has_fbs_entity"],
        "capability_status",
    ] = "THREE_SOURCE_ENTITY_PENDING_APPROVAL"

    base["blocking_reason"] = "COUNTRY_OR_TERRITORY_APPROVAL_REQUIRED"
    base.loc[base["is_aggregate"], "blocking_reason"] = ""
    base.loc[base["is_historical"], "blocking_reason"] = ""
    base.loc[base["is_composite_geography"], "blocking_reason"] = (
        "COMPOSITE_GEOGRAPHY_POTENTIAL_OVERLAP"
    )
    base.loc[~base["has_fbs_entity"] & ~base["is_aggregate"], "blocking_reason"] = (
        "NO_MATCHED_FBS_ENTITY"
    )
    base.loc[
        base["has_fbs_entity"]
        & ~base["observed_as_importer"]
        & ~base["is_aggregate"]
        & ~base["is_composite_geography"],
        "blocking_reason",
    ] = "NO_OBSERVED_IMPORTER_NETWORK"

    # Guardrails.
    if base.loc[base["is_aggregate"], "eligible_for_supplier_role"].any():
        raise ValueError("An aggregate was approved as a supplier")
    if base.loc[base["is_composite_geography"], "eligible_for_supplier_role"].any():
        raise ValueError("A composite geography was approved as a supplier")
    if base["eligible_for_economy_ranking"].any():
        raise ValueError("An economy was ranked before manual approval")
    if not base.loc[base["eligible_for_supplier_role"], "observed_as_exporter"].all():
        raise ValueError("Supplier role assigned without exporter observation")

    component_m49 = set(COMPOSITE_GEOGRAPHIES["159"]["components"])
    china_composite = base.loc[base["entity_m49"].eq("159")]
    if len(china_composite) != 1:
        raise ValueError("Expected exactly one composite China entity")
    if not china_composite["is_composite_geography"].all():
        raise ValueError("Composite China entity was not blocked")
    if not component_m49.issubset(set(base["entity_m49"].dropna())):
        raise ValueError("One or more China component geographies are missing")

    columns = [
        "entity_m49",
        "entity_name",
        "entity_type",
        "ranking_scope_candidate",
        "geographic_parent_m49",
        "geographic_parent_name",
        "hierarchy_status",
        "overlap_group",
        "is_aggregate",
        "is_historical",
        "is_composite_geography",
        "observed_as_importer",
        "observed_as_exporter",
        "has_fbs_entity",
        "has_baseline_importer_rows",
        "has_baseline_exporter_rows",
        "has_baseline_fbs_rows",
        "importer_area_code",
        "importer_area",
        "importer_rows",
        "importer_baseline_rows",
        "exporter_area_code",
        "exporter_area",
        "exporter_rows",
        "exporter_baseline_rows",
        "fbs_area_code",
        "fbs_area",
        "fbs_rows",
        "fbs_baseline_rows",
        "eligible_for_economy_ranking",
        "eligible_for_supplier_role",
        "eligible_for_importer_network",
        "eligible_for_fbs_reliance_candidate",
        "eligible_for_complete_vulnerability_profile",
        "supplier_relationship_type",
        "agricultural_origin_known",
        "origin_inference_prohibited",
        "capability_status",
        "blocking_reason",
    ]
    unified = base[columns].sort_values(
        ["capability_status", "entity_name"], na_position="last"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    unified.to_csv(UNIFIED_PATH, index=False)
    unified.loc[unified["eligible_for_importer_network"]].to_csv(
        IMPORTER_PATH, index=False
    )
    unified.loc[unified["eligible_for_supplier_role"]].to_csv(
        SUPPLIER_PATH, index=False
    )
    unified.loc[unified["eligible_for_fbs_reliance_candidate"]].to_csv(
        FBS_PATH, index=False
    )
    unified.loc[unified["hierarchy_status"].ne("NO_KNOWN_HIERARCHY_CONFLICT")].to_csv(
        HIERARCHY_PATH, index=False
    )
    unified.loc[
        ~(
            unified["observed_as_importer"]
            & unified["observed_as_exporter"]
            & unified["has_fbs_entity"]
        )
        & ~unified["is_aggregate"]
    ].to_csv(SOURCE_GAPS_PATH, index=False)
    unified.loc[~unified["is_aggregate"] & ~unified["is_historical"]].to_csv(
        MANUAL_REVIEW_PATH, index=False
    )

    report = {
        "dataset": "Unified importer-exporter-FBS geography capability",
        "baseline_period": {"start_year": BASELINE_START, "end_year": BASELINE_END},
        "total_entities": len(unified),
        "observed_importers": int(unified["observed_as_importer"].sum()),
        "observed_exporters": int(unified["observed_as_exporter"].sum()),
        "fbs_entities": int(unified["has_fbs_entity"].sum()),
        "three_source_entities": int(
            (
                unified["observed_as_importer"]
                & unified["observed_as_exporter"]
                & unified["has_fbs_entity"]
            ).sum()
        ),
        "excluded_aggregates": int(unified["is_aggregate"].sum()),
        "composite_geographies_blocked": int(unified["is_composite_geography"].sum()),
        "provisional_supplier_entities": int(
            unified["eligible_for_supplier_role"].sum()
        ),
        "provisional_importer_network_entities": int(
            unified["eligible_for_importer_network"].sum()
        ),
        "provisional_fbs_reliance_entities": int(
            unified["eligible_for_fbs_reliance_candidate"].sum()
        ),
        "economy_rankings_auto_approved": 0,
        "method_controls": {
            "supplier_requires_exporter_observation": True,
            "supplier_requires_baseline_exporter_observation": True,
            "importer_network_requires_baseline_importer_observation": True,
            "importer_network_requires_importer_observation": True,
            "agricultural_origin_inferred": False,
            "ranking_scope_candidate": "COUNTRIES_AND_TERRITORIES",
            "composite_china_blocked": True,
            "missing_capabilities_remain_null": True,
        },
        "outputs": {
            "unified": str(UNIFIED_PATH.relative_to(ROOT)),
            "importer_network_universe": str(IMPORTER_PATH.relative_to(ROOT)),
            "exporter_supplier_universe": str(SUPPLIER_PATH.relative_to(ROOT)),
            "fbs_reliance_universe": str(FBS_PATH.relative_to(ROOT)),
            "hierarchy_review": str(HIERARCHY_PATH.relative_to(ROOT)),
            "source_coverage_gaps": str(SOURCE_GAPS_PATH.relative_to(ROOT)),
            "manual_review": str(MANUAL_REVIEW_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("UNIFIED GEOGRAPHY AND CAPABILITY BUILD COMPLETE")
    print("=" * 72)
    print(f"Total entities: {len(unified):,}")
    print(f"Observed importers: {report['observed_importers']:,}")
    print(f"Observed exporters: {report['observed_exporters']:,}")
    print(f"FBS entities: {report['fbs_entities']:,}")
    print(f"Three-source entities: {report['three_source_entities']:,}")
    print(f"Excluded aggregates: {report['excluded_aggregates']:,}")
    print(f"Composite geographies blocked: {report['composite_geographies_blocked']:,}")
    print(f"Provisional supplier entities: {report['provisional_supplier_entities']:,}")
    print(
        "Provisional importer-network entities: "
        f"{report['provisional_importer_network_entities']:,}"
    )
    print(
        "Provisional FBS-reliance entities: "
        f"{report['provisional_fbs_reliance_entities']:,}"
    )
    print("\nNo economy was automatically approved for ranking.")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

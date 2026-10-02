from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/processed/food_balances.duckdb"
TRADE_ROOT = ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported"
OUTPUT_DIR = ROOT / "outputs/tables/core_food_country_foundation"
OUTPUT_PATH = OUTPUT_DIR / "country_eligibility_candidates.csv"
REVIEW_PATH = OUTPUT_DIR / "country_eligibility_manual_review.csv"
DIAGNOSTIC_PATH = OUTPUT_DIR / "country_eligibility_diagnostics.csv"
REPORT_PATH = ROOT / "outputs/model_results/country_eligibility_candidates_summary.json"

AGGREGATE_PATTERNS = [
    r"^world$",
    r"^africa$",
    r"^americas$",
    r"^asia$",
    r"^europe$",
    r"^oceania$",
    r"\bleast developed countries\b",
    r"\blow income food deficit countries\b",
    r"\bland locked developing countries\b",
    r"\bnet food importing developing countries\b",
    r"\bsmall island developing states\b",
    r"\bannex\b",
    r"\btotal\b",
    r"\baggregate\b",
    r"\bgroup\b",
    r"\bregion\b",
    r"\bdeveloped countries\b",
    r"\bdeveloping countries\b",
    r"\beuropean union\b",
    r"^australia and new zealand$",
    r"^caribbean$",
    r"^central america$",
    r"^melanesia$",
    r"^micronesia$",
    r"^northern america$",
    r"^polynesia$",
    r"^south america$",
]
HISTORICAL_PATTERNS = [
    r"\bussr\b",
    r"\byugoslav",
    r"\bczechoslovak",
    r"\bserbia and montenegro\b",
    r"\bethiopia pdr\b",
    r"\bsudan former\b",
    r"\bdemocratic yemen\b",
]
SPECIAL_REPORTING_PATTERNS = [
    r"\bfree zone\b",
    r"\bbunkers\b",
    r"\bunspecified\b",
    r"\bnot elsewhere specified\b",
    r"\bother areas\b",
]


def normalize_m49(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace("'", "")
    text = text.removesuffix(".0")
    digits = re.sub(r"\D", "", text)
    return digits.zfill(3) if digits else None


def normalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def matches_any(name: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in patterns)


def classify_entity(
    name: str,
    has_m49: bool,
    fbs_area_code: object,
) -> tuple[str, str, bool, bool, str]:
    normalized = normalize_name(name)
    fbs_code = None if pd.isna(fbs_area_code) else int(fbs_area_code)
    if fbs_code is not None and 5000 <= fbs_code < 6000:
        return (
            "aggregate",
            "EXCLUDE_AGGREGATE",
            False,
            False,
            "FAOSTAT Food Balance area code is in the aggregate-series range.",
        )
    if matches_any(normalized, AGGREGATE_PATTERNS):
        return (
            "aggregate",
            "EXCLUDE_AGGREGATE",
            False,
            False,
            "Aggregate or region name pattern.",
        )
    if matches_any(normalized, HISTORICAL_PATTERNS):
        return (
            "historical_entity",
            "EXCLUDE_HISTORICAL",
            False,
            False,
            "Historical entity name pattern.",
        )
    if matches_any(normalized, SPECIAL_REPORTING_PATTERNS):
        return (
            "special_reporting_entity",
            "REVIEW",
            False,
            True,
            "Potential supplier role, but not an importer-ranking unit without review.",
        )
    if not has_m49:
        return "unmatched", "UNMATCHED", False, True, "No usable M49 identifier."
    return (
        "country_or_territory_candidate",
        "REVIEW",
        False,
        True,
        "M49-backed entity requires country-versus-territory review.",
    )


def load_trade_entities() -> pd.DataFrame:
    if not list(TRADE_ROOT.rglob("*.parquet")):
        raise FileNotFoundError(f"No Parquet files under {TRADE_ROOT}")
    connection = duckdb.connect()
    parquet_glob = str(TRADE_ROOT / "**/*.parquet")
    frame = connection.execute(
        f"""
        SELECT
            importer_code AS trade_area_code,
            importer_m49 AS trade_m49,
            importer AS trade_area,
            COUNT(*) AS trade_rows,
            MIN(year) AS trade_first_year,
            MAX(year) AS trade_latest_year,
            COUNT(DISTINCT item_code) AS trade_items,
            SUM(CASE WHEN value_type = 'quantity' AND unit = 't' AND value > 0
                     THEN 1 ELSE 0 END) AS positive_tonne_rows
        FROM read_parquet('{parquet_glob}', union_by_name = true)
        GROUP BY importer_code, importer_m49, importer
        ORDER BY importer
        """
    ).fetchdf()
    connection.close()
    frame["trade_m49_normalized"] = frame["trade_m49"].map(normalize_m49)
    frame["trade_name_normalized"] = frame["trade_area"].map(normalize_name)
    return frame


def load_fbs_entities() -> pd.DataFrame:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    frame = connection.execute(
        """
        SELECT
            "Area Code" AS fbs_area_code,
            "Area Code (M49)" AS fbs_m49,
            "Area" AS fbs_area,
            COUNT(*) AS fbs_rows,
            MIN("Year") AS fbs_first_year,
            MAX("Year") AS fbs_latest_year,
            COUNT(DISTINCT "Item Code") AS fbs_items,
            COUNT(*) FILTER (WHERE "Element Code" = 5611) AS fbs_import_rows,
            COUNT(*) FILTER (WHERE "Element Code" = 5301) AS fbs_domestic_supply_rows
        FROM main.food_balances
        GROUP BY "Area Code", "Area Code (M49)", "Area"
        ORDER BY "Area"
        """
    ).fetchdf()
    connection.close()
    frame["fbs_m49_normalized"] = frame["fbs_m49"].map(normalize_m49)
    frame["fbs_name_normalized"] = frame["fbs_area"].map(normalize_name)
    return frame


def main() -> None:
    trade = load_trade_entities()
    fbs = load_fbs_entities()

    valid_trade_m49 = trade["trade_m49_normalized"].dropna()
    if valid_trade_m49.duplicated().any():
        duplicate_values = set(valid_trade_m49[valid_trade_m49.duplicated(False)])
        duplicates = trade.loc[
            trade["trade_m49_normalized"].isin(duplicate_values),
            ["trade_m49_normalized", "trade_area_code", "trade_area"],
        ]
        raise ValueError(
            "Duplicate trade M49 identifiers:\n" + duplicates.to_string(index=False)
        )

    valid_fbs_m49 = fbs["fbs_m49_normalized"].dropna()
    if valid_fbs_m49.duplicated().any():
        duplicate_values = set(valid_fbs_m49[valid_fbs_m49.duplicated(False)])
        duplicates = fbs.loc[
            fbs["fbs_m49_normalized"].isin(duplicate_values),
            ["fbs_m49_normalized", "fbs_area_code", "fbs_area"],
        ]
        raise ValueError(
            "Duplicate FBS M49 identifiers:\n" + duplicates.to_string(index=False)
        )

    merged = trade.merge(
        fbs,
        left_on="trade_m49_normalized",
        right_on="fbs_m49_normalized",
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    merged["match_method"] = merged["_merge"].map(
        {"both": "M49_EXACT", "left_only": "TRADE_ONLY", "right_only": "FBS_ONLY"}
    )
    merged["entity_name"] = merged["trade_area"].combine_first(merged["fbs_area"])
    merged["entity_m49"] = merged["trade_m49_normalized"].combine_first(
        merged["fbs_m49_normalized"]
    )

    classifications = merged.apply(
        lambda row: classify_entity(
            row["entity_name"],
            pd.notna(row["entity_m49"]),
            row["fbs_area_code"],
        ),
        axis=1,
        result_type="expand",
    )
    classifications.columns = [
        "entity_type_candidate",
        "eligibility_status_candidate",
        "eligible_for_country_ranking_candidate",
        "eligible_for_supplier_role_candidate",
        "classification_rationale",
    ]
    merged = pd.concat([merged, classifications], axis=1)
    merged["name_agreement"] = (
        merged["trade_name_normalized"].ne("")
        & merged["fbs_name_normalized"].ne("")
        & merged["trade_name_normalized"].eq(merged["fbs_name_normalized"])
    )

    merged["manual_review_required"] = True
    merged["review_status"] = "PENDING_MANUAL_REVIEW"
    merged["final_entity_type"] = ""
    merged["final_eligibility_status"] = ""
    merged["eligible_for_country_ranking"] = pd.NA
    merged["eligible_for_supplier_role"] = pd.NA
    merged["review_notes"] = ""

    columns = [
        "entity_m49",
        "entity_name",
        "trade_area_code",
        "trade_m49",
        "trade_area",
        "fbs_area_code",
        "fbs_m49",
        "fbs_area",
        "match_method",
        "name_agreement",
        "entity_type_candidate",
        "eligibility_status_candidate",
        "eligible_for_country_ranking_candidate",
        "eligible_for_supplier_role_candidate",
        "classification_rationale",
        "trade_rows",
        "trade_first_year",
        "trade_latest_year",
        "trade_items",
        "positive_tonne_rows",
        "fbs_rows",
        "fbs_first_year",
        "fbs_latest_year",
        "fbs_items",
        "fbs_import_rows",
        "fbs_domestic_supply_rows",
        "manual_review_required",
        "review_status",
        "final_entity_type",
        "final_eligibility_status",
        "eligible_for_country_ranking",
        "eligible_for_supplier_role",
        "review_notes",
    ]
    result = merged[columns].sort_values(
        ["eligibility_status_candidate", "entity_name"], na_position="last"
    )
    if result["eligible_for_country_ranking"].notna().any():
        raise ValueError(
            "Country-ranking eligibility was populated before manual review"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    result.to_csv(REVIEW_PATH, index=False)

    diagnostics = (
        result.groupby(
            ["match_method", "entity_type_candidate", "eligibility_status_candidate"],
            dropna=False,
        )
        .agg(
            entities=("entity_name", "size"),
            trade_rows=("trade_rows", "sum"),
            fbs_rows=("fbs_rows", "sum"),
        )
        .reset_index()
        .sort_values("entities", ascending=False)
    )
    diagnostics.to_csv(DIAGNOSTIC_PATH, index=False)

    report = {
        "dataset": "Country eligibility candidates",
        "candidate_only": True,
        "auto_approved_country_rankings": 0,
        "total_entities": len(result),
        "trade_entities": int(result["trade_area_code"].notna().sum()),
        "fbs_entities": int(result["fbs_area_code"].notna().sum()),
        "m49_exact_matches": int(result["match_method"].eq("M49_EXACT").sum()),
        "trade_only": int(result["match_method"].eq("TRADE_ONLY").sum()),
        "fbs_only": int(result["match_method"].eq("FBS_ONLY").sum()),
        "candidate_status_counts": {
            str(key): int(value)
            for key, value in result["eligibility_status_candidate"]
            .value_counts()
            .items()
        },
        "required_manual_decisions": [
            "Confirm sovereign country versus territory",
            "Confirm aggregate exclusions",
            "Review trade-only and FBS-only entities",
            "Confirm country-ranking eligibility",
            "Confirm supplier-role eligibility independently",
        ],
        "outputs": {
            "candidates": str(OUTPUT_PATH.relative_to(ROOT)),
            "manual_review": str(REVIEW_PATH.relative_to(ROOT)),
            "diagnostics": str(DIAGNOSTIC_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("COUNTRY ELIGIBILITY CANDIDATES COMPLETE")
    print("=" * 72)
    print(f"Total entities: {len(result):,}")
    print(f"Trade entities: {report['trade_entities']:,}")
    print(f"FBS entities: {report['fbs_entities']:,}")
    print(f"M49 exact matches: {report['m49_exact_matches']:,}")
    print(f"Trade only: {report['trade_only']:,}")
    print(f"FBS only: {report['fbs_only']:,}")
    print("\nCandidate eligibility statuses:")
    print(result["eligibility_status_candidate"].value_counts().to_string())
    print("\nNo entity was auto-approved for country ranking.")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

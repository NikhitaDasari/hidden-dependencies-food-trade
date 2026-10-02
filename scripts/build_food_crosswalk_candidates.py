from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FBS_ITEMS = ROOT / "outputs/tables/dataset_overview/08_food_items.csv"
TRADE_GLOB = str(
    ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported/**/*.parquet"
)
OUTPUT_DIR = ROOT / "outputs/tables/crosswalk_discovery"
CANDIDATES = OUTPUT_DIR / "food_crosswalk_candidates.csv"
EXACT_MATCHES = OUTPUT_DIR / "food_crosswalk_exact_matches.csv"
REVIEW_QUEUE = OUTPUT_DIR / "food_crosswalk_manual_review.csv"
EXCLUDED_UNITS = OUTPUT_DIR / "trade_items_non_tonne_units.csv"
SUMMARY = ROOT / "outputs/model_results/food_crosswalk_discovery_summary.json"

AGGREGATE_TERMS = {
    "grand total",
    "animal products",
    "vegetal products",
    "cereals excluding beer",
    "starchy roots",
    "sugar crops",
    "sugar and sweeteners",
    "pulses",
    "treenuts",
    "oilcrops",
    "vegetable oils",
    "vegetables",
    "fruits excluding wine",
    "stimulants",
    "spices",
    "alcoholic beverages",
    "meat",
    "offals",
    "animal fats",
    "eggs",
    "milk excluding butter",
    "fish seafood",
    "aquatic products other",
    "miscellaneous",
}

NON_FOOD_TERMS = (
    "hides",
    "skins",
    "wool",
    "tobacco",
    "cigarette",
    "rubber",
    "fibre",
    "fiber",
    "cotton",
    "flax",
    "hemp",
    "jute",
    "inedible",
    "industrial",
    "waste",
    "crude organic material",
    "essential oil",
    "beeswax",
)


def normalize_name(value: str) -> str:
    text = str(value).lower().strip()
    text = text.replace("n.e.c.", "nes").replace("n.e.c", "nes")
    text = text.replace("excluding", "excl")
    text = text.replace("products", "product")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def top_matches(name: str, choices: list[tuple[int, str, str]], limit: int = 3):
    scored = [
        (similarity(name, normalized), code, label)
        for code, label, normalized in choices
    ]
    scored.sort(reverse=True)
    return scored[:limit]


def main() -> None:
    if not FBS_ITEMS.exists():
        raise FileNotFoundError(FBS_ITEMS)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)

    fbs = pd.read_csv(FBS_ITEMS)
    required = {"item_code", "item"}
    if not required.issubset(fbs.columns):
        raise ValueError(f"Missing FBS columns: {required - set(fbs.columns)}")

    fbs = fbs[
        [
            column
            for column in ["item_code", "fbs_item_code", "item"]
            if column in fbs.columns
        ]
    ].drop_duplicates()
    fbs["fbs_normalized_name"] = fbs["item"].map(normalize_name)
    fbs["fbs_is_aggregate"] = fbs["fbs_normalized_name"].isin(AGGREGATE_TERMS)

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    trade = con.execute(
        f"""
        SELECT
            item_code,
            ANY_VALUE(cpc_code) AS cpc_code,
            ANY_VALUE(item) AS item,
            COUNT(*) AS rows,
            COUNT(*) FILTER (WHERE value_type='quantity' AND unit='t') AS tonne_rows,
            COUNT(*) FILTER (WHERE value_type='quantity' AND unit<>'t') AS non_tonne_quantity_rows,
            COUNT(DISTINCT importer_code) AS importers,
            COUNT(DISTINCT exporter_code) AS exporters,
            MIN(year) AS first_year,
            MAX(year) AS latest_year,
            SUM(value) FILTER (WHERE value_type='quantity' AND unit='t' AND value>0) AS positive_tonnes
        FROM read_parquet('{TRADE_GLOB}', union_by_name=true)
        GROUP BY item_code
        ORDER BY item_code
        """
    ).fetchdf()
    con.close()

    trade["trade_normalized_name"] = trade["item"].map(normalize_name)
    trade["preliminary_non_food"] = trade["trade_normalized_name"].map(
        lambda value: any(term in value for term in NON_FOOD_TERMS)
    )
    trade["tonne_compatible"] = trade["tonne_rows"].gt(0)

    exact_lookup = {}
    for row in fbs.itertuples(index=False):
        exact_lookup.setdefault(row.fbs_normalized_name, []).append(row)

    choices = [
        (int(row.item_code), str(row.item), str(row.fbs_normalized_name))
        for row in fbs.itertuples(index=False)
    ]

    records = []
    for row in trade.itertuples(index=False):
        exact = exact_lookup.get(row.trade_normalized_name, [])
        top = top_matches(row.trade_normalized_name, choices)
        best_score, best_code, best_name = top[0]
        second_score = top[1][0] if len(top) > 1 else None
        exact_codes = ";".join(str(item.item_code) for item in exact)
        exact_names = ";".join(str(item.item) for item in exact)
        exact_nonaggregate = [item for item in exact if not item.fbs_is_aggregate]

        if row.preliminary_non_food:
            status = "exclude_preliminary_non_food"
        elif not row.tonne_compatible:
            status = "exclude_non_tonne_only"
        elif len(exact_nonaggregate) == 1:
            status = "exact_name_match"
        elif len(exact_nonaggregate) > 1:
            status = "review_multiple_exact_matches"
        elif best_score >= 0.90:
            status = "review_high_similarity"
        else:
            status = "manual_review"

        records.append(
            {
                "trade_item_code": int(row.item_code),
                "trade_cpc_code": row.cpc_code,
                "trade_item": row.item,
                "trade_normalized_name": row.trade_normalized_name,
                "rows": int(row.rows),
                "tonne_rows": int(row.tonne_rows),
                "non_tonne_quantity_rows": int(row.non_tonne_quantity_rows),
                "tonne_compatible": bool(row.tonne_compatible),
                "positive_tonnes": row.positive_tonnes,
                "importers": int(row.importers),
                "exporters": int(row.exporters),
                "first_year": int(row.first_year),
                "latest_year": int(row.latest_year),
                "preliminary_non_food": bool(row.preliminary_non_food),
                "exact_fbs_item_codes": exact_codes,
                "exact_fbs_items": exact_names,
                "best_fbs_item_code": best_code,
                "best_fbs_item": best_name,
                "best_similarity": round(best_score, 6),
                "second_best_similarity": None
                if second_score is None
                else round(second_score, 6),
                "mapping_status": status,
                "manual_decision": "",
                "approved_fbs_item_code": "",
                "mapping_rationale": "",
            }
        )

    candidates = pd.DataFrame(records).sort_values(
        ["mapping_status", "positive_tonnes", "trade_item"],
        ascending=[True, False, True],
        na_position="last",
    )
    candidates.to_csv(CANDIDATES, index=False)
    candidates[candidates["mapping_status"].eq("exact_name_match")].to_csv(
        EXACT_MATCHES, index=False
    )
    candidates[
        ~candidates["mapping_status"].isin(
            [
                "exact_name_match",
                "exclude_preliminary_non_food",
                "exclude_non_tonne_only",
            ]
        )
    ].to_csv(REVIEW_QUEUE, index=False)
    candidates[candidates["non_tonne_quantity_rows"].gt(0)].to_csv(
        EXCLUDED_UNITS, index=False
    )

    summary = {
        "trade_items": len(candidates),
        "fbs_items": len(fbs),
        "tonne_compatible_trade_items": int(candidates["tonne_compatible"].sum()),
        "preliminary_non_food_items": int(candidates["preliminary_non_food"].sum()),
        "mapping_status_counts": {
            str(key): int(value)
            for key, value in candidates["mapping_status"].value_counts().items()
        },
        "important_method_note": (
            "This is a discovery crosswalk only. Exact and fuzzy name matches do not establish "
            "physical equivalence. Every approved mapping must pass overlap, processing, unit, "
            "and bilateral-to-national import reconciliation checks."
        ),
        "outputs": {
            "all_candidates": str(CANDIDATES.relative_to(ROOT)),
            "exact_matches": str(EXACT_MATCHES.relative_to(ROOT)),
            "manual_review": str(REVIEW_QUEUE.relative_to(ROOT)),
            "non_tonne_units": str(EXCLUDED_UNITS.relative_to(ROOT)),
        },
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("FOOD CROSSWALK DISCOVERY COMPLETE")
    print("=" * 72)
    print(f"Trade items: {summary['trade_items']}")
    print(f"Food Balance items: {summary['fbs_items']}")
    print(f"Tonne-compatible trade items: {summary['tonne_compatible_trade_items']}")
    for status, count in summary["mapping_status_counts"].items():
        print(f"{status}: {count}")
    print(f"Summary: {SUMMARY.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

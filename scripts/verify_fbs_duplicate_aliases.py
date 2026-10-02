from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/processed/food_balances.duckdb"
OUTPUT_PATH = ROOT / "outputs/model_results/fbs_duplicate_alias_verification.json"
PAIRS = [(2744, 2949, "Eggs"), (2848, 2948, "Milk - Excluding Butter")]


def compare_pair(
    connection: duckdb.DuckDBPyConnection, left: int, right: int, label: str
) -> dict:
    query = """
        WITH left_rows AS (
            SELECT
                "Area Code" AS area_code,
                "Area Code (M49)" AS area_m49,
                "Area" AS area,
                "Element Code" AS element_code,
                "Element" AS element,
                "Year" AS year,
                "Unit" AS unit,
                "Value" AS value,
                "Flag" AS flag,
                "Note" AS note
            FROM main.food_balances
            WHERE "Item Code" = ?
        ),
        right_rows AS (
            SELECT
                "Area Code" AS area_code,
                "Area Code (M49)" AS area_m49,
                "Area" AS area,
                "Element Code" AS element_code,
                "Element" AS element,
                "Year" AS year,
                "Unit" AS unit,
                "Value" AS value,
                "Flag" AS flag,
                "Note" AS note
            FROM main.food_balances
            WHERE "Item Code" = ?
        ),
        comparison AS (
            SELECT
                COUNT(*) FILTER (WHERE l.area_code IS NULL) AS only_in_right,
                COUNT(*) FILTER (WHERE r.area_code IS NULL) AS only_in_left,
                COUNT(*) FILTER (
                    WHERE l.area_code IS NOT NULL
                      AND r.area_code IS NOT NULL
                      AND (
                          l.value IS DISTINCT FROM r.value
                          OR l.flag IS DISTINCT FROM r.flag
                          OR l.note IS DISTINCT FROM r.note
                          OR l.area_m49 IS DISTINCT FROM r.area_m49
                          OR l.area IS DISTINCT FROM r.area
                      )
                ) AS differing_matched_rows,
                COUNT(*) FILTER (
                    WHERE l.area_code IS NOT NULL
                      AND r.area_code IS NOT NULL
                ) AS matched_key_rows
            FROM left_rows l
            FULL OUTER JOIN right_rows r
              USING (area_code, element_code, element, year, unit)
        )
        SELECT
            (SELECT COUNT(*) FROM left_rows) AS left_rows,
            (SELECT COUNT(*) FROM right_rows) AS right_rows,
            only_in_left,
            only_in_right,
            differing_matched_rows,
            matched_key_rows
        FROM comparison
    """
    row = connection.execute(query, [left, right]).fetchone()
    result = {
        "label": label,
        "canonical_code": left,
        "alias_code": right,
        "canonical_rows": row[0],
        "alias_rows": row[1],
        "only_in_canonical": row[2],
        "only_in_alias": row[3],
        "differing_matched_rows": row[4],
        "matched_key_rows": row[5],
    }
    result["exact_alias"] = (
        result["canonical_rows"] == result["alias_rows"]
        and result["only_in_canonical"] == 0
        and result["only_in_alias"] == 0
        and result["differing_matched_rows"] == 0
    )
    return result


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)

    connection = duckdb.connect(str(DB_PATH), read_only=True)
    results = [compare_pair(connection, *pair) for pair in PAIRS]
    connection.close()

    report = {
        "dataset": "FAOSTAT Food Balances",
        "comparison_key": ["area_code", "element_code", "element", "year", "unit"],
        "value_fields_checked": ["value", "flag", "note", "area_m49", "area"],
        "pairs": results,
        "all_pairs_are_exact_aliases": all(item["exact_alias"] for item in results),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("FBS DUPLICATE ITEM-CODE ALIAS VERIFICATION")
    print("=" * 72)
    for item in results:
        print(
            f"{item['label']}: {item['canonical_code']} vs {item['alias_code']} | "
            f"exact_alias={item['exact_alias']} | "
            f"canonical_rows={item['canonical_rows']:,} | alias_rows={item['alias_rows']:,} | "
            f"only_in_canonical={item['only_in_canonical']:,} | "
            f"only_in_alias={item['only_in_alias']:,} | "
            f"differing_matched_rows={item['differing_matched_rows']:,}"
        )
    print(f"Report: {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

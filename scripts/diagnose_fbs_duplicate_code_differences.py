from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/processed/food_balances.duckdb"
OUTPUT_PATH = ROOT / "outputs/model_results/fbs_duplicate_code_differences.json"
PAIRS = [(2744, 2949, "Eggs"), (2848, 2948, "Milk - Excluding Butter")]


def diagnose(
    connection: duckdb.DuckDBPyConnection, left: int, right: int, label: str
) -> dict:
    sql = """
    WITH l AS (
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
    r AS (
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
    joined AS (
        SELECT
            COALESCE(l.element_code, r.element_code) AS element_code,
            COALESCE(l.element, r.element) AS element,
            COALESCE(l.unit, r.unit) AS unit,
            l.value AS left_value,
            r.value AS right_value,
            l.flag AS left_flag,
            r.flag AS right_flag,
            l.note AS left_note,
            r.note AS right_note,
            l.area_m49 AS left_area_m49,
            r.area_m49 AS right_area_m49,
            l.area AS left_area,
            r.area AS right_area
        FROM l
        FULL OUTER JOIN r
          USING (area_code, element_code, element, year, unit)
    )
    SELECT
        element_code,
        element,
        unit,
        COUNT(*) AS matched_rows,
        COUNT(*) FILTER (WHERE left_value IS DISTINCT FROM right_value) AS value_differences,
        COUNT(*) FILTER (WHERE left_flag IS DISTINCT FROM right_flag) AS flag_differences,
        COUNT(*) FILTER (WHERE left_note IS DISTINCT FROM right_note) AS note_differences,
        COUNT(*) FILTER (WHERE left_area_m49 IS DISTINCT FROM right_area_m49) AS m49_differences,
        COUNT(*) FILTER (WHERE left_area IS DISTINCT FROM right_area) AS area_name_differences,
        MAX(ABS(left_value - right_value)) FILTER (
            WHERE left_value IS NOT NULL AND right_value IS NOT NULL
        ) AS maximum_absolute_value_difference
    FROM joined
    GROUP BY element_code, element, unit
    ORDER BY element_code
    """
    profile = connection.execute(sql, [left, right]).fetchdf()

    import_sql = """
    WITH l AS (
        SELECT "Area Code" area_code, "Year" AS year_key, "Value" AS value, "Flag" AS flag, "Note" AS note
        FROM main.food_balances
        WHERE "Item Code" = ? AND "Element Code" = 5611
    ),
    r AS (
        SELECT "Area Code" area_code, "Year" AS year_key, "Value" AS value, "Flag" AS flag, "Note" AS note
        FROM main.food_balances
        WHERE "Item Code" = ? AND "Element Code" = 5611
    )
    SELECT
        COUNT(*) AS rows,
        COUNT(*) FILTER (WHERE l.value IS DISTINCT FROM r.value) AS value_differences,
        COUNT(*) FILTER (WHERE l.flag IS DISTINCT FROM r.flag) AS flag_differences,
        COUNT(*) FILTER (WHERE l.note IS DISTINCT FROM r.note) AS note_differences,
        MAX(ABS(l.value-r.value)) FILTER (
            WHERE l.value IS NOT NULL AND r.value IS NOT NULL
        ) AS maximum_absolute_value_difference
    FROM l FULL OUTER JOIN r USING (area_code, year_key)
    """
    import_row = connection.execute(import_sql, [left, right]).fetchone()

    value_difference_total = int(profile["value_differences"].sum())
    result = {
        "label": label,
        "left_code": left,
        "right_code": right,
        "all_elements_value_identical": value_difference_total == 0,
        "all_elements_value_difference_rows": value_difference_total,
        "import_quantity_5611": {
            "rows": import_row[0],
            "value_differences": import_row[1],
            "flag_differences": import_row[2],
            "note_differences": import_row[3],
            "maximum_absolute_value_difference": import_row[4],
            "values_identical": import_row[1] == 0,
        },
        "element_profile": profile.to_dict(orient="records"),
    }
    return result


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    pairs = [diagnose(connection, *pair) for pair in PAIRS]
    connection.close()

    report = {
        "dataset": "FAOSTAT Food Balances",
        "purpose": "Determine whether duplicate item-code series differ in quantitative values or only metadata fields.",
        "pairs": pairs,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print("=" * 72)
    print("FBS DUPLICATE-CODE DIFFERENCE DIAGNOSTIC")
    print("=" * 72)
    for pair in pairs:
        imports = pair["import_quantity_5611"]
        print(f"{pair['label']}: {pair['left_code']} vs {pair['right_code']}")
        print(
            f"  All-element value differences: {pair['all_elements_value_difference_rows']:,}"
        )
        print(f"  Import rows: {imports['rows']:,}")
        print(f"  Import value differences: {imports['value_differences']:,}")
        print(f"  Import flag differences: {imports['flag_differences']:,}")
        print(f"  Import note differences: {imports['note_differences']:,}")
        print(f"  Import values identical: {imports['values_identical']}")
    print(f"Report: {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

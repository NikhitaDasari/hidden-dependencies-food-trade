from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/processed/food_balances.duckdb"


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)

    connection = duckdb.connect(str(DB_PATH), read_only=True)

    result = connection.execute(
        """
        SELECT
            "Element Code" AS element_code,
            "Element" AS element,
            "Unit" AS unit,
            COUNT(*) AS rows,
            COUNT(DISTINCT "Item Code") AS items,
            COUNT(DISTINCT "Area Code") AS areas,
            MIN("Year") AS first_year,
            MAX("Year") AS latest_year
        FROM main.food_balances
        WHERE LOWER("Element") LIKE '%import%'
        GROUP BY
            "Element Code",
            "Element",
            "Unit"
        ORDER BY rows DESC
        """
    ).fetchdf()

    print("=" * 72)
    print("FOOD BALANCE IMPORT ELEMENTS AND UNITS")
    print("=" * 72)
    print(result.to_string(index=False))

    connection.close()


if __name__ == "__main__":
    main()

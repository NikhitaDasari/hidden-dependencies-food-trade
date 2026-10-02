from __future__ import annotations

import argparse
import io
import json
import shutil
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = (
    ROOT
    / "data/raw/faostat/detailed_trade_matrix/Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip"
)
MEMBER = "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).csv"
SILVER = ROOT / "data/interim/faostat/detailed_trade_matrix"
IMPORT_DIR = SILVER / "importer_reported"
EXPORT_DIR = SILVER / "exporter_reported"
PROFILE = ROOT / "outputs/model_results/trade_matrix_silver_profile.json"
TABLES = ROOT / "outputs/tables/trade_matrix_overview"

USECOLS = [
    "Reporter Country Code",
    "Reporter Country Code (M49)",
    "Reporter Countries",
    "Partner Country Code",
    "Partner Country Code (M49)",
    "Partner Countries",
    "Item Code",
    "Item Code (CPC)",
    "Item",
    "Element Code",
    "Element",
    "Year",
    "Unit",
    "Value",
    "Flag",
]
DTYPES = {
    "Reporter Country Code": "Int64",
    "Reporter Country Code (M49)": "string",
    "Reporter Countries": "string",
    "Partner Country Code": "Int64",
    "Partner Country Code (M49)": "string",
    "Partner Countries": "string",
    "Item Code": "Int64",
    "Item Code (CPC)": "string",
    "Item": "string",
    "Element Code": "Int64",
    "Element": "string",
    "Year": "Int64",
    "Unit": "string",
    "Value": "float64",
    "Flag": "string",
}
ELEMENTS = {"Import quantity", "Import value", "Export quantity", "Export value"}


def clean_code(series: pd.Series, width: int | None = None) -> pd.Series:
    value = series.astype("string").str.replace("'", "", regex=False).str.strip()
    return value.str.zfill(width) if width else value


def canonicalize(frame: pd.DataFrame) -> pd.DataFrame:
    is_import = frame["Element"].str.startswith("Import", na=False)
    is_quantity = frame["Element"].str.endswith("quantity", na=False)
    edge = pd.DataFrame(
        {
            "importer_code": frame["Reporter Country Code"].where(
                is_import, frame["Partner Country Code"]
            ),
            "importer_m49": frame["Reporter Country Code (M49)"].where(
                is_import, frame["Partner Country Code (M49)"]
            ),
            "importer": frame["Reporter Countries"].where(
                is_import, frame["Partner Countries"]
            ),
            "exporter_code": frame["Partner Country Code"].where(
                is_import, frame["Reporter Country Code"]
            ),
            "exporter_m49": frame["Partner Country Code (M49)"].where(
                is_import, frame["Reporter Country Code (M49)"]
            ),
            "exporter": frame["Partner Countries"].where(
                is_import, frame["Reporter Countries"]
            ),
            "item_code": frame["Item Code"],
            "cpc_code": frame["Item Code (CPC)"],
            "item": frame["Item"],
            "year": frame["Year"],
            "measure": frame["Element"],
            "unit": frame["Unit"],
            "value": frame["Value"],
            "flag": frame["Flag"],
            "reporting_perspective": is_import.map(
                {True: "importer_reported", False: "exporter_reported"}
            ),
            "value_type": is_quantity.map({True: "quantity", False: "value"}),
        }
    )
    edge["importer_m49"] = clean_code(edge["importer_m49"], 3)
    edge["exporter_m49"] = clean_code(edge["exporter_m49"], 3)
    edge["cpc_code"] = clean_code(edge["cpc_code"])
    return edge


def write_parts(frame: pd.DataFrame, root: Path, chunk_id: int) -> int:
    if frame.empty:
        return 0
    written = 0
    for (year, value_type), part in frame.groupby(
        ["year", "value_type"], observed=True
    ):
        folder = root / f"year={int(year)}" / f"value_type={value_type}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"part-{chunk_id:06d}.parquet"
        pq.write_table(
            pa.Table.from_pandas(part, preserve_index=False),
            path,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        written += len(part)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream FAOSTAT trade ZIP to Silver Parquet"
    )
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--chunk-size", type=int, default=500000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not ARCHIVE.exists():
        raise FileNotFoundError(ARCHIVE)
    if args.start_year > args.end_year:
        raise ValueError("start-year must not exceed end-year")
    if args.overwrite and SILVER.exists():
        shutil.rmtree(SILVER)
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)

    counts = Counter()
    years = Counter()
    items = Counter()
    flags = Counter()
    units = Counter()
    importers: set[int] = set()
    exporters: set[int] = set()
    distinct_items: set[int] = set()
    started = time.monotonic()

    with zipfile.ZipFile(ARCHIVE) as archive:
        if MEMBER not in archive.namelist():
            raise KeyError(f"Missing archive member: {MEMBER}")
        with archive.open(MEMBER) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = pd.read_csv(
                text,
                usecols=USECOLS,
                dtype=DTYPES,
                chunksize=args.chunk_size,
                low_memory=False,
            )
            for chunk_id, chunk in enumerate(reader, 1):
                counts["source_rows"] += len(chunk)
                frame = chunk.loc[
                    chunk["Year"].between(args.start_year, args.end_year)
                ].copy()
                counts["rows_in_year_range"] += len(frame)
                frame = frame.loc[frame["Element"].isin(ELEMENTS)].copy()
                counts["rows_allowed_elements"] += len(frame)
                country_mask = (
                    frame["Reporter Country Code"].notna()
                    & frame["Partner Country Code"].notna()
                    & frame["Reporter Country Code"].lt(5000)
                    & frame["Partner Country Code"].lt(5000)
                )
                frame = frame.loc[country_mask].copy()
                counts["rows_country_to_country"] += len(frame)
                self_trade = frame["Reporter Country Code"].eq(
                    frame["Partner Country Code"]
                )
                counts["rows_self_trade_excluded"] += int(self_trade.sum())
                frame = frame.loc[~self_trade].copy()
                valid = frame["Value"].notna() & frame["Value"].ge(0)
                counts["rows_invalid_value_excluded"] += int((~valid).sum())
                frame = frame.loc[valid].copy()
                if frame.empty:
                    continue
                edges = canonicalize(frame)
                imports = edges.loc[
                    edges["reporting_perspective"].eq("importer_reported")
                ].copy()
                exports = edges.loc[
                    edges["reporting_perspective"].eq("exporter_reported")
                ].copy()
                counts["importer_reported_rows"] += write_parts(
                    imports, IMPORT_DIR, chunk_id
                )
                counts["exporter_reported_rows"] += write_parts(
                    exports, EXPORT_DIR, chunk_id
                )
                years.update(edges["year"].astype(int).value_counts().to_dict())
                flags.update(
                    edges["flag"]
                    .fillna("[Missing]")
                    .astype(str)
                    .value_counts()
                    .to_dict()
                )
                units.update(
                    edges["unit"]
                    .fillna("[Missing]")
                    .astype(str)
                    .value_counts()
                    .to_dict()
                )
                grouped = edges.groupby(["item_code", "item"], dropna=False).size()
                items.update(
                    {(int(k[0]), str(k[1])): int(v) for k, v in grouped.items()}
                )
                importers.update(edges["importer_code"].dropna().astype(int).unique())
                exporters.update(edges["exporter_code"].dropna().astype(int).unique())
                distinct_items.update(edges["item_code"].dropna().astype(int).unique())
                elapsed = (time.monotonic() - started) / 60
                print(
                    f"Chunk {chunk_id:,} | source {counts['source_rows']:,} | silver {len(edges):,} | {elapsed:.1f} min",
                    flush=True,
                )

    pd.DataFrame([{"year": k, "rows": v} for k, v in sorted(years.items())]).to_csv(
        TABLES / "silver_year_profile.csv", index=False
    )
    pd.DataFrame(
        [{"item_code": k[0], "item": k[1], "rows": v} for k, v in items.items()]
    ).sort_values(["rows", "item"], ascending=[False, True]).to_csv(
        TABLES / "silver_item_profile.csv", index=False
    )
    pd.DataFrame([{"flag": k, "rows": v} for k, v in flags.items()]).sort_values(
        "rows", ascending=False
    ).to_csv(TABLES / "silver_flag_profile.csv", index=False)

    parquet_files = list(SILVER.rglob("*.parquet"))
    elapsed = time.monotonic() - started
    profile = {
        "dataset": "FAOSTAT Detailed Trade Matrix",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "archive_member": MEMBER,
        "analysis_period": {"start_year": args.start_year, "end_year": args.end_year},
        "chunk_size": args.chunk_size,
        "counters": dict(counts),
        "distinct_importers": len(importers),
        "distinct_exporters": len(exporters),
        "distinct_items": len(distinct_items),
        "unit_counts": dict(units),
        "flag_counts": dict(flags),
        "parquet_file_count": len(parquet_files),
        "parquet_bytes": sum(p.stat().st_size for p in parquet_files),
        "elapsed_seconds": round(elapsed, 2),
        "silver_locations": {
            "importer_reported": str(IMPORT_DIR.relative_to(ROOT)),
            "exporter_reported": str(EXPORT_DIR.relative_to(ROOT)),
        },
        "quality_controls": [
            "Reporter and partner country codes below 5000",
            "Self-trade excluded",
            "Missing and negative values excluded",
            "M49 values normalized to three digits",
            "Importer and exporter reporting perspectives retained separately",
        ],
    }
    PROFILE.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print("\n" + "=" * 72)
    print("DETAILED TRADE MATRIX SILVER BUILD COMPLETE")
    print("=" * 72)
    print(f"Source rows: {counts['source_rows']:,}")
    print(f"Importer-reported rows: {counts['importer_reported_rows']:,}")
    print(f"Exporter-reported rows: {counts['exporter_reported_rows']:,}")
    print(f"Distinct importers: {len(importers)}")
    print(f"Distinct exporters: {len(exporters)}")
    print(f"Distinct items: {len(distinct_items)}")
    print(f"Parquet files: {len(parquet_files)}")
    print(f"Parquet size GB: {profile['parquet_bytes'] / 1_000_000_000:.3f}")
    print(f"Elapsed minutes: {elapsed / 60:.2f}")
    print(f"Profile: {PROFILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

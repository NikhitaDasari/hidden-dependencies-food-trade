from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRADE_ROOT = ROOT / "data/interim/faostat/detailed_trade_matrix/importer_reported"
READY_PATH = (
    ROOT / "outputs/tables/core_food_fbs_foundation/core_food_fbs_baseline_ready.csv"
)
SCOPES_PATH = (
    ROOT / "outputs/tables/core_food_fbs_foundation/core_food_analytical_scopes.csv"
)
GEO_PATH = (
    ROOT
    / "outputs/tables/core_food_country_foundation/unified_geography_capability.csv"
)
OUT = ROOT / "outputs/tables/core_food_supplier_network"
ANNUAL_PATH = OUT / "core_food_supplier_network_annual.csv"
POOLED_PATH = OUT / "core_food_supplier_network_pooled.csv"
SUMMARY_PATH = OUT / "core_food_supplier_network_summary.csv"
UNMATCHED_IMPORTERS_PATH = OUT / "core_food_supplier_network_unmatched_importers.csv"
UNMATCHED_CHANNELS_PATH = OUT / "core_food_supplier_network_unmatched_channels.csv"
COVERAGE_PATH = OUT / "core_food_supplier_network_coverage_diagnostics.csv"
SUPPLIER_REVIEW_PATH = OUT / "core_food_supplier_network_supplier_review.csv"
REPORT_PATH = ROOT / "outputs/model_results/core_food_supplier_network_summary.json"

YEARS = {2021, 2022, 2023}
MATERIAL_SHARE = 0.01
REMAINING_GATES = "COUNTRY_APPROVAL|MAPPING_ALIGNMENT|CONFIDENCE_REVIEW|FINAL_QA"


def norm_m49(value: object) -> str | None:
    if pd.isna(value):
        return None
    digits = re.sub(r"\D", "", str(value).replace(".0", ""))
    return digits.zfill(3) if digits else None


def to_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return (
        series.astype("string")
        .str.casefold()
        .map({"true": True, "false": False})
        .fillna(False)
    )


def explode_scope_map(scopes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for row in scopes.itertuples(index=False):
        codes = [
            part.strip()
            for part in str(row.trade_item_codes).split(";")
            if part.strip()
        ]
        if not codes:
            continue
        for code in codes:
            rows.append(
                {
                    "analytical_scope_code": row.analytical_scope_code,
                    "core_food_code": row.core_food_code,
                    "core_food": row.core_food,
                    "trade_item_code": int(float(code)),
                    "scope_interpretation": row.scope_interpretation,
                    "family_rollup_allowed": bool(row.family_rollup_allowed),
                }
            )
    mapping = pd.DataFrame(rows).drop_duplicates()
    if mapping.empty:
        raise ValueError("No trade item codes were found in analytical scopes")
    duplicate = mapping.duplicated(["trade_item_code", "analytical_scope_code"])
    if duplicate.any():
        raise ValueError("Duplicate trade-item to analytical-scope mappings")
    return mapping


def coverage_class(
    value: float | None, has_network: bool, fbs_imports: float | None
) -> str:
    if not has_network:
        return "NO_OBSERVED_NETWORK"
    if pd.isna(fbs_imports) or fbs_imports is None or fbs_imports <= 0:
        return "FBS_IMPORT_DENOMINATOR_UNAVAILABLE"
    if value is None or pd.isna(value):
        return "COVERAGE_UNAVAILABLE"
    if value < 0.25:
        return "LOW_COVERAGE"
    if value < 0.75:
        return "PARTIAL_COVERAGE"
    if value <= 1.25:
        return "ALIGNED_COVERAGE"
    if value <= 2.0:
        return "ABOVE_FBS_IMPORTS"
    return "EXTREME_COVERAGE_REVIEW"


def concentration(frame: pd.DataFrame, share_col: str) -> pd.Series:
    shares = frame[share_col].sort_values(ascending=False)
    hhi = float((shares**2).sum())
    return pd.Series(
        {
            "supplier_count": int(frame["exporter_m49"].nunique()),
            "material_supplier_count": int(
                frame.loc[frame[share_col].ge(MATERIAL_SHARE), "exporter_m49"].nunique()
            ),
            "top1_share": float(shares.head(1).sum()),
            "top3_share": float(shares.head(3).sum()),
            "hhi": hhi,
            "effective_supplier_count": 1.0 / hhi if hhi > 0 else np.nan,
        }
    )


def main() -> None:
    for path in [READY_PATH, SCOPES_PATH, GEO_PATH, TRADE_ROOT]:
        if not path.exists():
            raise FileNotFoundError(path)

    ready = pd.read_csv(READY_PATH, dtype={"entity_m49": "string"})
    scopes = pd.read_csv(SCOPES_PATH)
    geo = pd.read_csv(GEO_PATH, dtype={"entity_m49": "string"})
    ready["entity_m49"] = ready["entity_m49"].map(norm_m49)
    geo["entity_m49"] = geo["entity_m49"].map(norm_m49)
    geo["eligible_for_importer_network"] = to_bool(geo["eligible_for_importer_network"])
    geo["eligible_for_supplier_role"] = to_bool(geo["eligible_for_supplier_role"])

    if ready.duplicated(["entity_m49", "analytical_scope_code"]).any():
        raise ValueError("Duplicate linkage-ready economy-scope baselines")
    if to_bool(ready["ready_for_final_ranking"]).any():
        raise ValueError(
            "A linkage-ready baseline is already marked ready for final ranking"
        )

    scope_map = explode_scope_map(scopes)
    valid_importers = geo.loc[
        geo["eligible_for_importer_network"], ["entity_m49", "entity_name"]
    ].rename(
        columns={"entity_m49": "importer_m49", "entity_name": "importer_name_governed"}
    )
    valid_suppliers = geo.loc[
        geo["eligible_for_supplier_role"],
        ["entity_m49", "entity_name", "capability_status"],
    ].rename(
        columns={
            "entity_m49": "exporter_m49",
            "entity_name": "exporter_name_governed",
            "capability_status": "supplier_capability_status",
        }
    )

    linkage = ready.merge(
        valid_importers,
        left_on="entity_m49",
        right_on="importer_m49",
        how="left",
        indicator=True,
    )
    unmatched_importers = linkage.loc[linkage["_merge"].ne("both")].copy()
    linkage = linkage.loc[linkage["_merge"].eq("both")].drop(columns="_merge")

    mapped_scopes = set(scope_map["analytical_scope_code"])
    unmatched_channels = ready.loc[
        ~ready["analytical_scope_code"].isin(mapped_scopes)
    ].copy()
    linkage = linkage.loc[linkage["analytical_scope_code"].isin(mapped_scopes)].copy()

    con = duckdb.connect()
    con.register("scope_map", scope_map)
    con.register(
        "linkage", linkage[["importer_m49", "analytical_scope_code"]].drop_duplicates()
    )
    parquet_glob = str(TRADE_ROOT / "**/*.parquet")
    query = f"""
        SELECT
            LPAD(REGEXP_REPLACE(CAST(t.importer_m49 AS VARCHAR), '[^0-9]', '', 'g'), 3, '0') AS importer_m49,
            ANY_VALUE(t.importer) AS importer_name_trade,
            m.analytical_scope_code,
            m.core_food_code,
            m.core_food,
            LPAD(REGEXP_REPLACE(CAST(t.exporter_m49 AS VARCHAR), '[^0-9]', '', 'g'), 3, '0') AS exporter_m49,
            ANY_VALUE(t.exporter) AS exporter_name_trade,
            CAST(t.year AS INTEGER) AS year,
            SUM(CAST(t.value AS DOUBLE)) AS observed_import_quantity_tonnes,
            COUNT(*) AS source_rows,
            COUNT(DISTINCT CAST(t.item_code AS BIGINT)) AS trade_item_count,
            STRING_AGG(DISTINCT CAST(t.item_code AS VARCHAR), ';' ORDER BY CAST(t.item_code AS VARCHAR)) AS trade_item_codes
        FROM read_parquet('{parquet_glob}', union_by_name=true) t
        JOIN scope_map m
          ON CAST(t.item_code AS BIGINT) = m.trade_item_code
        JOIN linkage l
          ON LPAD(REGEXP_REPLACE(CAST(t.importer_m49 AS VARCHAR), '[^0-9]', '', 'g'), 3, '0') = l.importer_m49
         AND m.analytical_scope_code = l.analytical_scope_code
        WHERE CAST(t.year AS INTEGER) BETWEEN 2021 AND 2023
          AND LOWER(CAST(t.value_type AS VARCHAR)) = 'quantity'
          AND LOWER(CAST(t.reporting_perspective AS VARCHAR)) = 'importer_reported'
          AND CAST(t.value AS DOUBLE) > 0
        GROUP BY 1, 3, 4, 5, 6, 8
    """
    annual = con.execute(query).fetchdf()
    con.close()

    if annual.empty:
        raise ValueError(
            "No bilateral trade observations matched linkage-ready analytical scopes"
        )
    annual["importer_m49"] = annual["importer_m49"].map(norm_m49)
    annual["exporter_m49"] = annual["exporter_m49"].map(norm_m49)
    annual = annual.loc[annual["year"].isin(YEARS)].copy()
    annual = annual.merge(
        valid_suppliers, on="exporter_m49", how="left", indicator=True
    )
    annual["supplier_eligible"] = annual["_merge"].eq("both")

    supplier_review = annual.loc[~annual["supplier_eligible"]].copy()
    annual = annual.loc[annual["supplier_eligible"]].drop(columns="_merge")
    if annual.empty:
        raise ValueError("No observed supplier survived exporter eligibility controls")

    annual["supplier_relationship_type"] = "IMMEDIATE_TRADE_PARTNER"
    annual["agricultural_origin_known"] = False
    annual["origin_inference_prohibited"] = True
    annual["annual_network_total_tonnes"] = annual.groupby(
        ["importer_m49", "analytical_scope_code", "year"]
    )["observed_import_quantity_tonnes"].transform("sum")
    annual["supplier_share"] = (
        annual["observed_import_quantity_tonnes"]
        / annual["annual_network_total_tonnes"]
    )

    annual_keys = ["importer_m49", "analytical_scope_code", "year"]
    share_check = annual.groupby(annual_keys)["supplier_share"].sum()
    if not np.allclose(share_check.to_numpy(), 1.0, atol=1e-10):
        raise ValueError("Annual supplier shares do not sum to one")

    pooled = annual.groupby(
        [
            "importer_m49",
            "importer_name_trade",
            "analytical_scope_code",
            "core_food_code",
            "core_food",
            "exporter_m49",
            "exporter_name_trade",
            "exporter_name_governed",
            "supplier_capability_status",
        ],
        as_index=False,
    ).agg(
        pooled_import_quantity_tonnes=("observed_import_quantity_tonnes", "sum"),
        years_observed=("year", "nunique"),
        source_rows=("source_rows", "sum"),
        trade_item_codes=(
            "trade_item_codes",
            lambda x: ";".join(sorted(set(";".join(map(str, x)).split(";")))),
        ),
    )
    pooled["pooled_network_total_tonnes"] = pooled.groupby(
        ["importer_m49", "analytical_scope_code"]
    )["pooled_import_quantity_tonnes"].transform("sum")
    pooled["pooled_supplier_share"] = (
        pooled["pooled_import_quantity_tonnes"] / pooled["pooled_network_total_tonnes"]
    )
    pooled["supplier_relationship_type"] = "IMMEDIATE_TRADE_PARTNER"
    pooled["agricultural_origin_known"] = False
    pooled["origin_inference_prohibited"] = True

    pooled_share_check = pooled.groupby(["importer_m49", "analytical_scope_code"])[
        "pooled_supplier_share"
    ].sum()
    if not np.allclose(pooled_share_check.to_numpy(), 1.0, atol=1e-10):
        raise ValueError("Pooled supplier shares do not sum to one")

    metrics = (
        pooled.groupby(["importer_m49", "analytical_scope_code"])
        .apply(concentration, share_col="pooled_supplier_share", include_groups=False)
        .reset_index()
    )
    network_totals = pooled.groupby(
        ["importer_m49", "analytical_scope_code"], as_index=False
    ).agg(
        trade_matrix_imports_tonnes=("pooled_import_quantity_tonnes", "sum"),
        years_with_network=("years_observed", "max"),
    )

    # Persistence and turnover use the set of observed immediate suppliers by year.
    top_annual = annual.loc[
        annual.groupby(annual_keys)["supplier_share"].idxmax(),
        ["importer_m49", "analytical_scope_code", "year", "exporter_m49"],
    ]
    persistence = top_annual.groupby(
        ["importer_m49", "analytical_scope_code"], as_index=False
    ).agg(
        top_supplier_years_observed=("year", "nunique"),
        distinct_top_suppliers=("exporter_m49", "nunique"),
    )
    persistence["top_supplier_persistence"] = 1 / persistence["distinct_top_suppliers"]

    supplier_sets = (
        annual.groupby(annual_keys)["exporter_m49"].agg(lambda x: set(x)).reset_index()
    )
    turnover_rows: list[dict[str, object]] = []
    for (importer, scope), group in supplier_sets.groupby(
        ["importer_m49", "analytical_scope_code"]
    ):
        group = group.sort_values("year")
        entries = exits = comparisons = 0
        previous: set[str] | None = None
        for suppliers in group["exporter_m49"]:
            if previous is not None:
                entries += len(suppliers - previous)
                exits += len(previous - suppliers)
                comparisons += 1
            previous = suppliers
        denominator = sum(len(s) for s in group["exporter_m49"])
        turnover_rows.append(
            {
                "importer_m49": importer,
                "analytical_scope_code": scope,
                "supplier_entry_count": entries,
                "supplier_exit_count": exits,
                "supplier_turnover": (entries + exits) / denominator
                if denominator
                else np.nan,
                "year_pair_comparisons": comparisons,
            }
        )
    turnover = pd.DataFrame(turnover_rows)

    summary = linkage.merge(
        network_totals,
        on=["importer_m49", "analytical_scope_code"],
        how="left",
    )
    summary = summary.merge(
        metrics, on=["importer_m49", "analytical_scope_code"], how="left"
    )
    observed_metrics = summary["hhi"].notna()
    summary.loc[observed_metrics, "top1_share"] = summary.loc[
        observed_metrics, "top1_share"
    ].clip(0, 1)
    summary.loc[observed_metrics, "top3_share"] = summary.loc[
        observed_metrics, "top3_share"
    ].clip(0, 1)
    summary.loc[observed_metrics, "hhi"] = summary.loc[observed_metrics, "hhi"].clip(
        0, 1
    )
    summary.loc[observed_metrics, "effective_supplier_count"] = (
        1.0 / summary.loc[observed_metrics, "hhi"]
    )
    summary.loc[observed_metrics, "effective_supplier_count"] = np.minimum(
        summary.loc[observed_metrics, "effective_supplier_count"],
        summary.loc[observed_metrics, "supplier_count"],
    )
    summary = summary.merge(
        persistence, on=["importer_m49", "analytical_scope_code"], how="left"
    )
    summary = summary.merge(
        turnover, on=["importer_m49", "analytical_scope_code"], how="left"
    )
    summary["has_observed_network"] = summary["trade_matrix_imports_tonnes"].notna()
    summary["network_coverage_raw"] = np.where(
        summary["has_observed_network"] & summary["baseline_imports_tonnes"].gt(0),
        summary["trade_matrix_imports_tonnes"] / summary["baseline_imports_tonnes"],
        np.nan,
    )
    summary["network_coverage_class"] = summary.apply(
        lambda row: coverage_class(
            row["network_coverage_raw"],
            bool(row["has_observed_network"]),
            row["baseline_imports_tonnes"],
        ),
        axis=1,
    )
    summary["network_metrics_available"] = summary["has_observed_network"]
    summary["ready_for_final_ranking"] = False
    summary["remaining_gates"] = REMAINING_GATES

    observed = summary["has_observed_network"]
    if not summary.loc[observed, "hhi"].between(0, 1).all():
        raise ValueError("Observed network HHI is outside 0..1")
    if not summary.loc[observed, "effective_supplier_count"].ge(1).all():
        raise ValueError("Observed effective supplier count is below one")
    if summary["ready_for_final_ranking"].any():
        raise ValueError("A supplier network was prematurely marked ready for ranking")
    if not annual["supplier_relationship_type"].eq("IMMEDIATE_TRADE_PARTNER").all():
        raise ValueError("Supplier terminology control failed")
    if annual["agricultural_origin_known"].any():
        raise ValueError("Immediate suppliers were mislabeled as agricultural origins")

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL_PATH, index=False)
    pooled.to_csv(POOLED_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    unmatched_importers.to_csv(UNMATCHED_IMPORTERS_PATH, index=False)
    unmatched_channels.to_csv(UNMATCHED_CHANNELS_PATH, index=False)
    summary.to_csv(COVERAGE_PATH, index=False)
    supplier_review.to_csv(SUPPLIER_REVIEW_PATH, index=False)

    report = {
        "dataset": "Core Food immediate supplier network foundation",
        "baseline_period": "2021-2023",
        "linkage_ready_fbs_baselines": len(ready),
        "importer_eligible_linkages": len(linkage),
        "observed_networks": int(observed.sum()),
        "no_observed_networks": int((~observed).sum()),
        "annual_supplier_edges": len(annual),
        "pooled_supplier_edges": len(pooled),
        "supplier_rows_for_review": len(supplier_review),
        "unmatched_importer_baselines": len(unmatched_importers),
        "unmatched_scope_baselines": len(unmatched_channels),
        "final_rankings_enabled": 0,
        "coverage_counts": {
            str(k): int(v)
            for k, v in summary["network_coverage_class"].value_counts().items()
        },
        "controls": {
            "importer_requires_baseline_observation": True,
            "supplier_requires_baseline_exporter_observation": True,
            "supplier_relationship_is_immediate_trade_partner": True,
            "agricultural_origin_not_inferred": True,
            "analytical_scopes_preserved": True,
            "supplier_shares_sum_to_one": True,
            "network_coverage_uncapped": True,
            "missing_network_not_zero_concentration": True,
            "no_final_ranking_enabled": True,
        },
        "outputs": {
            "annual": str(ANNUAL_PATH.relative_to(ROOT)),
            "pooled": str(POOLED_PATH.relative_to(ROOT)),
            "summary": str(SUMMARY_PATH.relative_to(ROOT)),
            "unmatched_importers": str(UNMATCHED_IMPORTERS_PATH.relative_to(ROOT)),
            "unmatched_channels": str(UNMATCHED_CHANNELS_PATH.relative_to(ROOT)),
            "coverage_diagnostics": str(COVERAGE_PATH.relative_to(ROOT)),
            "supplier_review": str(SUPPLIER_REVIEW_PATH.relative_to(ROOT)),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD SUPPLIER NETWORK BUILD COMPLETE")
    print("=" * 72)
    print(f"Linkage-ready FBS baselines: {len(ready):,}")
    print(f"Importer-eligible linkages: {len(linkage):,}")
    print(f"Observed networks: {observed.sum():,}")
    print(f"No observed network: {(~observed).sum():,}")
    print(f"Annual supplier edges: {len(annual):,}")
    print(f"Pooled supplier edges: {len(pooled):,}")
    print(f"Supplier rows held for review: {len(supplier_review):,}")
    print("No final vulnerability rankings were enabled.")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

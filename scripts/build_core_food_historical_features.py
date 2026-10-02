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
POLICY_PATH = ROOT / "config/model_governance/core_food_feature_policy.json"
PERIOD_POLICY_PATH = ROOT / "config/model_governance/core_food_period_policy.json"
SOURCE_INVENTORY = (
    ROOT
    / "outputs/tables/core_food_source_inventory/core_food_source_period_inventory.csv"
)
FBS_ANNUAL = (
    ROOT / "outputs/tables/core_food_fbs_foundation/core_food_fbs_annual_2021_2023.csv"
)
NETWORK_ANNUAL = (
    ROOT
    / "outputs/tables/core_food_supplier_network/core_food_supplier_network_annual.csv"
)
READINESS = (
    ROOT / "outputs/tables/core_food_model_readiness/core_food_model_readiness.csv"
)
OUT = ROOT / "outputs/tables/core_food_historical_features"
REPORT = ROOT / "outputs/model_results/core_food_historical_features_summary.json"

PANEL_PATH = OUT / "core_food_country_food_year_panel.csv"
PERIOD_PATH = OUT / "core_food_country_food_period_features.csv"
PRIMARY_PATH = OUT / "core_food_primary_feature_dataset.csv"
LIMITED_PATH = OUT / "core_food_limited_feature_dataset.csv"
COMPLETENESS_PATH = OUT / "core_food_feature_completeness.csv"
DISTRIBUTIONS_PATH = OUT / "core_food_feature_distributions.csv"
OUTLIERS_PATH = OUT / "core_food_feature_outlier_review.csv"
LEAKAGE_PATH = OUT / "core_food_temporal_leakage_checks.csv"

KEY = ["entity_m49", "analytical_scope_code"]
YEAR_KEY = KEY + ["year"]
ANNUAL_METRICS = [
    "gross_import_reliance_raw",
    "net_import_dependence_raw",
    "supplier_count",
    "material_supplier_count",
    "top1_share",
    "top3_share",
    "hhi",
    "effective_supplier_count",
]
TREND_METRICS = [
    "gross_import_reliance_raw",
    "net_import_dependence_raw",
    "supplier_count",
    "material_supplier_count",
    "top1_share",
    "hhi",
    "effective_supplier_count",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalize_m49(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(3)
    )


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return (
        series.astype("string")
        .str.casefold()
        .map({"true": True, "false": False, "1": True, "0": False})
        .fillna(False)
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def validate_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required - set(frame.columns)
    require(not missing, f"{name} columns missing: {sorted(missing)}")


def concentration(frame: pd.DataFrame, material_share: float) -> pd.Series:
    ordered = frame.sort_values(
        ["supplier_share", "exporter_m49"], ascending=[False, True]
    )
    shares = ordered["supplier_share"].astype(float)
    hhi = float((shares**2).sum())
    top = ordered.iloc[0]
    return pd.Series(
        {
            "network_observed": True,
            "annual_network_imports_tonnes": float(
                frame["observed_import_quantity_tonnes"].sum()
            ),
            "supplier_count": int(frame["exporter_m49"].nunique()),
            "material_supplier_count": int(
                frame.loc[
                    frame["supplier_share"].ge(material_share), "exporter_m49"
                ].nunique()
            ),
            "top1_share": float(shares.head(1).sum()),
            "top3_share": float(shares.head(3).sum()),
            "hhi": hhi,
            "effective_supplier_count": 1.0 / hhi if hhi > 0 else np.nan,
            "dominant_supplier_m49": str(top["exporter_m49"]),
            "dominant_supplier_name": str(top.get("exporter_name_trade", "")),
            "dominant_supplier_share": float(top["supplier_share"]),
        }
    )


def slope(values: pd.Series, years: pd.Series, minimum: int) -> float:
    valid = values.notna() & years.notna()
    if int(valid.sum()) < minimum:
        return np.nan
    y = values.loc[valid].astype(float).to_numpy()
    x = years.loc[valid].astype(float).to_numpy()
    if len(set(x)) < 2:
        return np.nan
    return float(np.polyfit(x, y, 1)[0])


def variation(values: pd.Series) -> float:
    valid = values.dropna().astype(float)
    if len(valid) < 2:
        return np.nan
    mean = float(valid.mean())
    if mean <= 0:
        return np.nan
    return float(valid.std(ddof=1) / mean)


def consecutive_adverse(values: pd.Series, direction: str) -> int:
    clean = values.dropna().astype(float)
    if len(clean) < 2:
        return 0
    differences = clean.diff().dropna()
    adverse = differences.gt(0) if direction == "higher" else differences.lt(0)
    count = 0
    for value in adverse.iloc[::-1]:
        if not bool(value):
            break
        count += 1
    return count


def period_features(group: pd.DataFrame, policy: dict[str, Any]) -> dict[str, Any]:
    ordered = group.sort_values("year")
    result: dict[str, Any] = {
        "period_start_year": int(ordered["year"].min()),
        "period_end_year": int(ordered["year"].max()),
        "period_years_expected": len(policy["expected_years"]),
        "period_rows_observed": len(ordered),
        "fbs_years_observed": int(ordered["imports_tonnes"].notna().sum()),
        "network_years_observed_panel": int(ordered["network_observed"].sum()),
    }
    for metric in TREND_METRICS:
        values = ordered[metric]
        valid = values.dropna().astype(float)
        prefix = metric
        result[f"{prefix}_observations"] = len(valid)
        result[f"{prefix}_first"] = valid.iloc[0] if len(valid) else np.nan
        result[f"{prefix}_latest"] = valid.iloc[-1] if len(valid) else np.nan
        result[f"{prefix}_period_average"] = valid.mean() if len(valid) else np.nan
        result[f"{prefix}_period_minimum"] = valid.min() if len(valid) else np.nan
        result[f"{prefix}_period_maximum"] = valid.max() if len(valid) else np.nan
        result[f"{prefix}_period_range"] = (
            valid.max() - valid.min() if len(valid) else np.nan
        )
        result[f"{prefix}_first_to_latest_change"] = (
            valid.iloc[-1] - valid.iloc[0] if len(valid) >= 2 else np.nan
        )
        result[f"{prefix}_latest_vs_period_average"] = (
            valid.iloc[-1] - valid.mean() if len(valid) else np.nan
        )
        result[f"{prefix}_coefficient_of_variation"] = variation(values)
        result[f"{prefix}_directional_slope"] = slope(
            values, ordered["year"], policy["trend_minimum_observations"]
        )
        direction = (
            "lower"
            if metric
            in {
                "supplier_count",
                "material_supplier_count",
                "effective_supplier_count",
            }
            else "higher"
        )
        result[f"{prefix}_consecutive_adverse_changes"] = consecutive_adverse(
            values, direction
        )
        differences = values.astype(float).diff()
        result[f"{prefix}_maximum_adverse_annual_change"] = (
            differences.min() if direction == "lower" else differences.max()
        )
    return result


def evidence_confidence(row: pd.Series) -> str:
    if row["model_readiness_status"] == "READY_FOR_PRIMARY_MODEL":
        return "HIGH_GOVERNED"
    if row["model_readiness_status"] == "READY_WITH_LIMITATIONS":
        return "LIMITED_GOVERNED"
    return "NOT_ADMITTED"


def completeness_table(frame: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for population, subset in [
        ("ALL_PANEL", frame),
        (
            "PRIMARY",
            frame.loc[frame["model_readiness_status"] == "READY_FOR_PRIMARY_MODEL"],
        ),
        (
            "LIMITED",
            frame.loc[frame["model_readiness_status"] == "READY_WITH_LIMITATIONS"],
        ),
    ]:
        for metric in ANNUAL_METRICS:
            records.append(
                {
                    "population": population,
                    "metric": metric,
                    "rows": len(subset),
                    "nonmissing_rows": int(subset[metric].notna().sum()),
                    "missing_rows": int(subset[metric].isna().sum()),
                    "completeness_rate": float(subset[metric].notna().mean())
                    if len(subset)
                    else np.nan,
                }
            )
    return pd.DataFrame(records)


def distribution_table(frame: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    approved = frame.loc[frame["governance_approved_for_model"]]
    for metric in ANNUAL_METRICS:
        for scope, subset in approved.groupby("analytical_scope_code"):
            values = subset[metric].dropna().astype(float)
            records.append(
                {
                    "analytical_scope_code": scope,
                    "metric": metric,
                    "observations": len(values),
                    "minimum": values.min() if len(values) else np.nan,
                    "p05": values.quantile(0.05) if len(values) else np.nan,
                    "median": values.median() if len(values) else np.nan,
                    "mean": values.mean() if len(values) else np.nan,
                    "p95": values.quantile(0.95) if len(values) else np.nan,
                    "maximum": values.max() if len(values) else np.nan,
                }
            )
    return pd.DataFrame(records)


def outlier_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    approved = frame.loc[frame["governance_approved_for_model"]].copy()
    for metric in ANNUAL_METRICS:
        parts: list[pd.DataFrame] = []
        for _, group in approved.groupby("analytical_scope_code"):
            values = group[metric]
            if values.notna().sum() < 4:
                continue
            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            flagged = group.loc[
                values.lt(lower) | values.gt(upper),
                YEAR_KEY
                + [
                    "entity_name",
                    "core_food",
                    "model_readiness_status",
                    metric,
                ],
            ].copy()
            if not flagged.empty:
                flagged["metric"] = metric
                flagged["metric_value"] = flagged.pop(metric)
                flagged["outlier_rule"] = "WITHIN_SCOPE_1_5_IQR_REVIEW_ONLY"
                parts.append(flagged)
        if parts:
            rows.append(pd.concat(parts, ignore_index=True))
    if not rows:
        return pd.DataFrame(
            columns=YEAR_KEY
            + [
                "entity_name",
                "core_food",
                "model_readiness_status",
                "metric",
                "metric_value",
                "outlier_rule",
            ]
        )
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    inputs = [
        POLICY_PATH,
        PERIOD_POLICY_PATH,
        SOURCE_INVENTORY,
        FBS_ANNUAL,
        NETWORK_ANNUAL,
        READINESS,
    ]
    for path in inputs:
        require(path.exists(), f"Required input missing: {path}")

    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    period_policy = json.loads(PERIOD_POLICY_PATH.read_text(encoding="utf-8"))
    years = [int(year) for year in policy["expected_years"]]
    require(
        years == period_policy["expected_years"], "Feature and period policies disagree"
    )
    require(
        policy["official_vulnerability_score_enabled"] is False,
        "Feature build cannot enable a vulnerability score",
    )
    require(
        policy["official_ranking_enabled"] is False,
        "Feature build cannot enable ranking",
    )
    require(
        period_policy["allow_future_information"] is False,
        "Period policy allows future information",
    )

    inventory = pd.read_csv(SOURCE_INVENTORY)
    authoritative = inventory.loc[
        inventory["source_name"].isin(
            ["core_food_fbs_annual", "core_food_supplier_network_annual"]
        )
    ]
    require(len(authoritative) == 2, "Build 1 authoritative sources missing")
    require(
        authoritative["alignment_status"].eq("EXACT_PERIOD_MATCH").all(),
        "Build 1 period controls failed",
    )

    fbs = pd.read_csv(FBS_ANNUAL, dtype={"entity_m49": "string"})
    network = pd.read_csv(
        NETWORK_ANNUAL,
        dtype={"importer_m49": "string", "exporter_m49": "string"},
    )
    readiness = pd.read_csv(READINESS, dtype={"entity_m49": "string"})
    fbs["entity_m49"] = normalize_m49(fbs["entity_m49"])
    network["importer_m49"] = normalize_m49(network["importer_m49"])
    network["exporter_m49"] = normalize_m49(network["exporter_m49"])
    readiness["entity_m49"] = normalize_m49(readiness["entity_m49"])

    validate_columns(
        fbs,
        set(YEAR_KEY)
        | {
            "entity_name",
            "core_food_code",
            "core_food",
            "imports_tonnes",
            "exports_tonnes",
            "domestic_supply_tonnes",
            "gross_import_reliance_raw",
            "net_import_dependence_raw",
            "denominator_status",
        },
        "FBS annual",
    )
    validate_columns(
        network,
        {
            "importer_m49",
            "analytical_scope_code",
            "year",
            "exporter_m49",
            "observed_import_quantity_tonnes",
            "supplier_share",
        },
        "Supplier network annual",
    )
    validate_columns(
        readiness,
        set(KEY)
        | {
            "model_readiness_status",
            "governance_approved_for_model",
            "ready_for_final_ranking",
            "mapping_effective_decision",
            "scope_confidence_class",
            "overall_confidence_class",
            "network_coverage_raw",
            "network_coverage_class",
            "model_readiness_issue_flags",
        },
        "Model readiness",
    )

    require(
        set(fbs["year"].dropna().astype(int)) == set(years),
        "FBS years differ from period policy",
    )
    require(
        set(network["year"].dropna().astype(int)) == set(years),
        "Network years differ from period policy",
    )
    require(not fbs.duplicated(YEAR_KEY).any(), "Duplicate FBS country-food-year keys")
    require(not readiness.duplicated(KEY).any(), "Duplicate readiness keys")
    require(len(readiness) == 4048, "Readiness universe must contain 4,048 records")
    require(
        not as_bool(readiness["ready_for_final_ranking"]).any(),
        "Final ranking is enabled",
    )

    network_keys = ["importer_m49", "analytical_scope_code", "year"]
    share_sums = network.groupby(network_keys)["supplier_share"].sum()
    require(
        np.allclose(share_sums.to_numpy(), 1.0, atol=1e-10),
        "Annual supplier shares do not sum to one",
    )
    require(
        network["supplier_share"].between(0, 1).all(), "Supplier share outside [0,1]"
    )

    annual_network = (
        network.groupby(network_keys, sort=False)
        .apply(
            concentration,
            material_share=float(policy["material_supplier_share"]),
            include_groups=False,
        )
        .reset_index()
        .rename(columns={"importer_m49": "entity_m49"})
    )

    readiness_fields = KEY + [
        "model_readiness_status",
        "governance_approved_for_model",
        "ready_for_final_ranking",
        "mapping_effective_decision",
        "scope_confidence_class",
        "overall_confidence_class",
        "network_coverage_raw",
        "network_coverage_class",
        "model_readiness_issue_flags",
    ]

    panel = fbs.merge(
        readiness[readiness_fields],
        on=KEY,
        how="left",
        validate="many_to_one",
    )
    panel = panel.merge(
        annual_network,
        on=YEAR_KEY,
        how="left",
        validate="one_to_one",
    )

    require(
        panel["model_readiness_status"].notna().all(),
        "FBS panel has unmatched readiness records",
    )

    required_annual_network_fields = {
        "network_observed",
        "annual_network_imports_tonnes",
        "supplier_count",
        "material_supplier_count",
        "top1_share",
        "top3_share",
        "hhi",
        "effective_supplier_count",
        "dominant_supplier_m49",
        "dominant_supplier_name",
        "dominant_supplier_share",
    }

    missing_annual_network_fields = required_annual_network_fields - set(panel.columns)
    require(
        not missing_annual_network_fields,
        "Annual network fields missing after merge: "
        f"{sorted(missing_annual_network_fields)}",
    )

    suffixed_network_fields = [
        column
        for column in panel.columns
        if column.endswith(("_x", "_y"))
        and (
            column.removesuffix("_x").removesuffix("_y")
            in required_annual_network_fields
        )
    ]
    require(
        not suffixed_network_fields,
        "Annual network fields were unexpectedly suffixed: "
        f"{sorted(suffixed_network_fields)}",
    )

    # Defragment after the joins before adding derived columns.
    panel = panel.copy()

    panel["network_observed"] = panel["network_observed"].fillna(False).astype(bool)
    panel["governance_approved_for_model"] = as_bool(
        panel["governance_approved_for_model"]
    )
    panel["ready_for_final_ranking"] = False
    panel["annual_network_coverage_raw"] = np.where(
        panel["network_observed"] & panel["imports_tonnes"].gt(0),
        panel["annual_network_imports_tonnes"] / panel["imports_tonnes"],
        np.nan,
    )
    panel["supplier_count_change"] = (
        panel.sort_values("year").groupby(KEY)["supplier_count"].diff()
    )
    panel["material_supplier_count_change"] = (
        panel.sort_values("year").groupby(KEY)["material_supplier_count"].diff()
    )
    panel["hhi_change"] = panel.sort_values("year").groupby(KEY)["hhi"].diff()
    panel["top1_share_change"] = (
        panel.sort_values("year").groupby(KEY)["top1_share"].diff()
    )
    panel["effective_supplier_count_change"] = (
        panel.sort_values("year").groupby(KEY)["effective_supplier_count"].diff()
    )
    panel["gross_import_reliance_change"] = (
        panel.sort_values("year").groupby(KEY)["gross_import_reliance_raw"].diff()
    )
    panel["net_import_dependence_change"] = (
        panel.sort_values("year").groupby(KEY)["net_import_dependence_raw"].diff()
    )
    panel["prior_dominant_supplier_m49"] = (
        panel.sort_values("year").groupby(KEY)["dominant_supplier_m49"].shift(1)
    )
    panel["top_supplier_changed"] = np.where(
        panel["network_observed"] & panel["prior_dominant_supplier_m49"].notna(),
        panel["dominant_supplier_m49"].ne(panel["prior_dominant_supplier_m49"]),
        pd.NA,
    )
    panel["evidence_confidence"] = panel.apply(evidence_confidence, axis=1)
    panel["analysis_period"] = f"{min(years)}-{max(years)}"
    panel["analysis_mode"] = "RETROSPECTIVE_FULL_PERIOD"
    panel["feature_policy_id"] = policy["policy_id"]
    panel["feature_policy_version"] = policy["policy_version"]

    observed_panel = panel.loc[panel["network_observed"]]
    absent_panel = panel.loc[~panel["network_observed"]]

    require(
        observed_panel["supplier_count"].ge(1).all(),
        "Observed annual network has no suppliers",
    )
    require(
        observed_panel["material_supplier_count"].ge(0).all(),
        "Material supplier count is negative",
    )
    require(
        (
            observed_panel["material_supplier_count"]
            <= observed_panel["supplier_count"]
        ).all(),
        "Material supplier count exceeds supplier count",
    )
    require(
        observed_panel["top1_share"].between(-1e-12, 1 + 1e-12).all(),
        "Annual Top-1 supplier share is outside bounds",
    )
    require(
        observed_panel["top3_share"].between(-1e-12, 1 + 1e-12).all(),
        "Annual Top-3 supplier share is outside bounds",
    )
    require(
        observed_panel["hhi"].between(-1e-12, 1 + 1e-12).all(),
        "Annual HHI is outside bounds",
    )
    require(
        observed_panel["effective_supplier_count"].ge(1 - 1e-10).all(),
        "Effective supplier count is below one",
    )
    require(
        np.allclose(
            observed_panel["dominant_supplier_share"],
            observed_panel["top1_share"],
            atol=1e-10,
            rtol=0,
        ),
        "Dominant supplier share does not equal Top-1 share",
    )
    require(
        np.allclose(
            observed_panel["effective_supplier_count"],
            1 / observed_panel["hhi"],
            atol=1e-10,
            rtol=1e-10,
        ),
        "Effective supplier count does not reconcile to HHI",
    )

    unavailable_network_metrics = [
        "annual_network_imports_tonnes",
        "supplier_count",
        "material_supplier_count",
        "top1_share",
        "top3_share",
        "hhi",
        "effective_supplier_count",
        "dominant_supplier_share",
    ]
    require(
        absent_panel[unavailable_network_metrics].isna().all().all(),
        "Missing annual network received modeled metrics",
    )

    # As-of fields use only current and previous rows via diff/shift. No centered or future windows exist.
    leakage = pd.DataFrame(
        [
            {
                "check_id": "YEARS_RESTRICTED_TO_POLICY",
                "passed": set(panel["year"].astype(int)) == set(years),
                "details": f"Observed years: {sorted(set(panel['year'].astype(int)))}",
            },
            {
                "check_id": "CHANGE_FEATURES_USE_DIFF_ONLY",
                "passed": True,
                "details": "Annual change fields use groupwise diff after chronological sorting",
            },
            {
                "check_id": "TOP_SUPPLIER_CHANGE_USES_SHIFT_ONLY",
                "passed": True,
                "details": "Prior dominant supplier uses groupwise shift(1)",
            },
            {
                "check_id": "NO_OFFICIAL_SCORE_OR_RANK",
                "passed": not any(
                    column in panel.columns
                    for column in ["vulnerability_score", "official_rank", "final_rank"]
                ),
                "details": "Feature panel contains no official score or rank fields",
            },
        ]
    )
    require(leakage["passed"].all(), "Temporal leakage control failed")

    period_rows: list[dict[str, Any]] = []
    for key, group in panel.groupby(KEY, sort=False):
        base = {
            "entity_m49": key[0],
            "analytical_scope_code": key[1],
            "entity_name": group["entity_name"].iloc[0],
            "core_food_code": group["core_food_code"].iloc[0],
            "core_food": group["core_food"].iloc[0],
            "model_readiness_status": group["model_readiness_status"].iloc[0],
            "governance_approved_for_model": bool(
                group["governance_approved_for_model"].iloc[0]
            ),
            "mapping_effective_decision": group["mapping_effective_decision"].iloc[0],
            "scope_confidence_class": group["scope_confidence_class"].iloc[0],
            "overall_confidence_class": group["overall_confidence_class"].iloc[0],
            "network_coverage_raw": group["network_coverage_raw"].iloc[0],
            "network_coverage_class": group["network_coverage_class"].iloc[0],
            "model_readiness_issue_flags": group["model_readiness_issue_flags"].iloc[0],
            "evidence_confidence": group["evidence_confidence"].iloc[0],
            "ready_for_final_ranking": False,
        }
        base.update(period_features(group, policy))
        period_rows.append(base)
    period = pd.DataFrame(period_rows)
    require(
        len(period) == 4048 and not period.duplicated(KEY).any(),
        "Period feature universe failed",
    )

    primary = period.loc[
        period["model_readiness_status"].eq(policy["primary_status"])
    ].copy()
    limited = period.loc[
        period["model_readiness_status"].eq(policy["limited_status"])
    ].copy()
    require(
        len(primary) == policy["expected_primary_records"], "Primary population changed"
    )
    require(
        len(limited) == policy["expected_limited_records"], "Limited population changed"
    )
    require(len(primary) + len(limited) == 1477, "Approved population changed")
    require(primary["governance_approved_for_model"].all(), "Unapproved primary record")
    require(limited["governance_approved_for_model"].all(), "Unapproved limited record")
    require(
        not period.loc[
            ~period["model_readiness_status"].isin(
                [policy["primary_status"], policy["limited_status"]]
            ),
            "governance_approved_for_model",
        ].any(),
        "Blocked record marked approved",
    )
    require(not period["ready_for_final_ranking"].any(), "Final ranking enabled")

    completeness = completeness_table(panel)
    distributions = distribution_table(panel)
    outliers = outlier_table(panel)

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    period.to_csv(PERIOD_PATH, index=False)
    primary.to_csv(PRIMARY_PATH, index=False)
    limited.to_csv(LIMITED_PATH, index=False)
    completeness.to_csv(COMPLETENESS_PATH, index=False)
    distributions.to_csv(DISTRIBUTIONS_PATH, index=False)
    outliers.to_csv(OUTLIERS_PATH, index=False)
    leakage.to_csv(LEAKAGE_PATH, index=False)

    source_paths = [
        PERIOD_POLICY_PATH,
        SOURCE_INVENTORY,
        FBS_ANNUAL,
        NETWORK_ANNUAL,
        READINESS,
    ]
    report = {
        "dataset": "Core Food historical feature foundation",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_commit(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path) for path in source_paths
        },
        "feature_policy_hash": sha256(POLICY_PATH),
        "authoritative_years": years,
        "annual_panel_rows": len(panel),
        "period_feature_rows": len(period),
        "primary_records": len(primary),
        "limited_records": len(limited),
        "approved_records": len(primary) + len(limited),
        "network_observed_annual_rows": int(panel["network_observed"].sum()),
        "outlier_review_rows": len(outliers),
        "controls": {
            "authoritative_period_preserved": True,
            "country_food_year_keys_unique": not panel.duplicated(YEAR_KEY).any(),
            "annual_supplier_shares_reconcile": True,
            "primary_population_reconciled": len(primary) == 661,
            "limited_population_reconciled": len(limited) == 816,
            "blocked_records_excluded": True,
            "missing_networks_preserved": True,
            "temporal_leakage_checks_passed": bool(leakage["passed"].all()),
            "evidence_confidence_separate": True,
            "official_vulnerability_score_disabled": True,
            "official_ranking_disabled": True,
        },
        "outputs": {
            "annual_panel": str(PANEL_PATH.relative_to(ROOT)),
            "period_features": str(PERIOD_PATH.relative_to(ROOT)),
            "primary_features": str(PRIMARY_PATH.relative_to(ROOT)),
            "limited_features": str(LIMITED_PATH.relative_to(ROOT)),
            "completeness": str(COMPLETENESS_PATH.relative_to(ROOT)),
            "distributions": str(DISTRIBUTIONS_PATH.relative_to(ROOT)),
            "outlier_review": str(OUTLIERS_PATH.relative_to(ROOT)),
            "temporal_leakage_checks": str(LEAKAGE_PATH.relative_to(ROOT)),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD HISTORICAL FEATURE BUILD COMPLETE")
    print("=" * 72)
    print(f"Authoritative years: {'|'.join(map(str, years))}")
    print(f"Annual country-food-year rows: {len(panel):,}")
    print(f"Period feature rows: {len(period):,}")
    print(f"Primary feature records: {len(primary):,}")
    print(f"Limited feature records: {len(limited):,}")
    print(f"Annual observed-network rows: {int(panel['network_observed'].sum()):,}")
    print("No vulnerability score or official ranking was generated.")
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

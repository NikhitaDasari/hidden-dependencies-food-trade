from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/model_governance/core_food_model_specification.json"
FEATURE_POLICY_PATH = ROOT / "config/model_governance/core_food_feature_policy.json"
PRIMARY_PATH = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_primary_feature_dataset.csv"
)
LIMITED_PATH = (
    ROOT
    / "outputs/tables/core_food_historical_features/core_food_limited_feature_dataset.csv"
)
OUT = ROOT / "outputs/tables/core_food_model_specification"
REPORT = ROOT / "outputs/model_results/core_food_model_specification_summary.json"

COMPONENTS_PATH = OUT / "core_food_scenario_components.csv"
RESULTS_PATH = OUT / "core_food_scenario_results.csv"
CORRELATIONS_PATH = OUT / "core_food_scenario_correlations.csv"
OVERLAP_PATH = OUT / "core_food_top_band_overlap.csv"
STABILITY_PATH = OUT / "core_food_band_stability.csv"
LEAVE_ONE_OUT_PATH = OUT / "core_food_leave_one_dimension_out.csv"
WEIGHT_PATH = OUT / "core_food_weight_sensitivity.csv"
NORMALIZATION_PATH = OUT / "core_food_normalization_sensitivity.csv"
POPULATION_PATH = OUT / "core_food_primary_limited_sensitivity.csv"
REVIEW_PATH = OUT / "core_food_specification_review.csv"

KEY = ["entity_m49", "analytical_scope_code"]
IDENTITY = KEY + ["entity_name", "core_food_code", "core_food"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


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


def normalize_m49(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(3)
    )


def validate_policy(policy: dict[str, Any]) -> None:
    require(
        policy["official_vulnerability_score_enabled"] is False,
        "Official score enabled",
    )
    require(policy["official_ranking_enabled"] is False, "Official ranking enabled")
    require(len(policy["scenarios"]) >= 5, "At least five scenarios are required")
    for scenario, definition in policy["scenarios"].items():
        weights = definition["metrics"]
        require(weights, f"Scenario {scenario} has no metrics")
        require(
            abs(sum(weights.values()) - 1.0) < 1e-12,
            f"Scenario {scenario} weights do not sum to one",
        )
        dimensions: dict[str, int] = {}
        for metric in weights:
            require(metric in policy["metrics"], f"Unknown metric {metric}")
            dimension = policy["metrics"][metric]["dimension"]
            dimensions[dimension] = dimensions.get(dimension, 0) + 1
        require(
            dimensions.get("CONCENTRATION", 0) <= 1,
            f"Scenario {scenario} double counts concentration",
        )


def percentile(values: pd.Series) -> pd.Series:
    return values.rank(method="average", pct=True)


def transform_metric(
    frame: pd.DataFrame,
    source: str,
    direction: str,
    transformation: str,
    policy: dict[str, Any],
) -> pd.Series:
    values = pd.to_numeric(frame[source], errors="coerce")
    oriented = -values if direction == "LOWER_IS_MORE_VULNERABLE" else values
    if transformation == "WITHIN_SCOPE_PERCENTILE":
        return oriented.groupby(frame["analytical_scope_code"]).transform(percentile)
    if transformation == "WITHIN_SCOPE_EMPIRICAL_CDF":
        return oriented.groupby(frame["analytical_scope_code"]).transform(percentile)
    if transformation == "POOLED_PERCENTILE_SENSITIVITY":
        return percentile(oriented)
    if transformation == "WINSORIZED_WITHIN_SCOPE":
        lower = float(policy["winsor_lower_quantile"])
        upper = float(policy["winsor_upper_quantile"])
        clipped = oriented.groupby(frame["analytical_scope_code"]).transform(
            lambda series: series.clip(series.quantile(lower), series.quantile(upper))
        )
        return clipped.groupby(frame["analytical_scope_code"]).transform(percentile)
    raise ValueError(f"Unsupported transformation: {transformation}")


def population_frame(
    primary: pd.DataFrame, limited: pd.DataFrame, name: str
) -> pd.DataFrame:
    if name == "PRIMARY_ONLY":
        result = primary.copy()
    elif name == "PRIMARY_PLUS_LIMITED":
        result = pd.concat([primary, limited], ignore_index=True)
    else:
        raise ValueError(f"Unknown population: {name}")
    result["analysis_population"] = name
    return result


def build_scenario(
    frame: pd.DataFrame,
    population: str,
    scenario: str,
    metric_weights: dict[str, float],
    transformation: str,
    policy: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    components = frame[
        IDENTITY + ["model_readiness_status", "evidence_confidence"]
    ].copy()
    components["analysis_population"] = population
    components["scenario_id"] = scenario
    components["transformation"] = transformation
    transformed_columns: list[str] = []
    complete = pd.Series(True, index=frame.index)
    for metric, weight in metric_weights.items():
        definition = policy["metrics"][metric]
        source = definition["source_column"]
        complete &= frame[source].notna()
        column = f"component__{metric}"
        components[column] = transform_metric(
            frame, source, definition["direction"], transformation, policy
        )
        components[f"weight__{metric}"] = weight
        transformed_columns.append(column)
    components["scenario_complete"] = complete
    weighted = pd.Series(0.0, index=frame.index)
    for metric, weight in metric_weights.items():
        weighted += components[f"component__{metric}"] * weight
    components["development_index"] = weighted.where(complete)
    components["result_classification"] = policy["result_classification"]
    components["official_ranking_enabled"] = False

    results = components[
        IDENTITY
        + [
            "model_readiness_status",
            "evidence_confidence",
            "analysis_population",
            "scenario_id",
            "transformation",
            "scenario_complete",
            "development_index",
            "result_classification",
            "official_ranking_enabled",
        ]
    ].copy()
    valid = results["scenario_complete"] & results["development_index"].notna()
    results["development_percentile"] = np.nan
    results.loc[valid, "development_percentile"] = (
        results.loc[valid]
        .groupby("analytical_scope_code")["development_index"]
        .transform(percentile)
    )
    high = float(policy["high_band_percentile"])
    low = float(policy["low_band_percentile"])
    results["development_band"] = "INCOMPLETE"
    results.loc[
        valid & results["development_percentile"].ge(high), "development_band"
    ] = "HIGH"
    results.loc[
        valid & results["development_percentile"].le(low), "development_band"
    ] = "LOW"
    results.loc[
        valid
        & results["development_percentile"].gt(low)
        & results["development_percentile"].lt(high),
        "development_band",
    ] = "MIDDLE"
    return components, results


def pairwise_correlations(results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base = results.loc[
        results["transformation"].eq("WITHIN_SCOPE_PERCENTILE")
        & results["scenario_complete"]
    ]
    for population, group in base.groupby("analysis_population"):
        scenarios = sorted(group["scenario_id"].unique())
        for left, right in combinations(scenarios, 2):
            a = group.loc[
                group["scenario_id"].eq(left), KEY + ["development_percentile"]
            ]
            b = group.loc[
                group["scenario_id"].eq(right), KEY + ["development_percentile"]
            ]
            merged = a.merge(b, on=KEY, suffixes=("_left", "_right"))
            rows.append(
                {
                    "analysis_population": population,
                    "scenario_left": left,
                    "scenario_right": right,
                    "common_records": len(merged),
                    "spearman_correlation": merged["development_percentile_left"].corr(
                        merged["development_percentile_right"], method="spearman"
                    ),
                    "kendall_correlation": merged["development_percentile_left"].corr(
                        merged["development_percentile_right"], method="kendall"
                    ),
                }
            )
    return pd.DataFrame(rows)


def overlap_table(results: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base = results.loc[
        results["transformation"].eq("WITHIN_SCOPE_PERCENTILE")
        & results["scenario_complete"]
    ]
    thresholds = {
        "TOP_DECILE": float(policy["top_decile_threshold"]),
        "TOP_QUINTILE": float(policy["top_quintile_threshold"]),
    }
    for population, group in base.groupby("analysis_population"):
        scenarios = sorted(group["scenario_id"].unique())
        for left, right in combinations(scenarios, 2):
            for band, threshold in thresholds.items():
                left_keys = set(
                    map(
                        tuple,
                        group.loc[
                            group["scenario_id"].eq(left)
                            & group["development_percentile"].ge(threshold),
                            KEY,
                        ].to_numpy(),
                    )
                )
                right_keys = set(
                    map(
                        tuple,
                        group.loc[
                            group["scenario_id"].eq(right)
                            & group["development_percentile"].ge(threshold),
                            KEY,
                        ].to_numpy(),
                    )
                )
                union = left_keys | right_keys
                rows.append(
                    {
                        "analysis_population": population,
                        "scenario_left": left,
                        "scenario_right": right,
                        "band": band,
                        "left_count": len(left_keys),
                        "right_count": len(right_keys),
                        "intersection_count": len(left_keys & right_keys),
                        "jaccard_overlap": len(left_keys & right_keys) / len(union)
                        if union
                        else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def stability_table(results: pd.DataFrame) -> pd.DataFrame:
    base = results.loc[
        results["analysis_population"].eq("PRIMARY_ONLY")
        & results["transformation"].eq("WITHIN_SCOPE_PERCENTILE")
        & results["scenario_complete"]
    ].copy()
    grouped = base.groupby(IDENTITY + ["evidence_confidence"], as_index=False).agg(
        scenarios_available=("scenario_id", "nunique"),
        high_scenario_count=("development_band", lambda x: int((x == "HIGH").sum())),
        low_scenario_count=("development_band", lambda x: int((x == "LOW").sum())),
        average_development_percentile=("development_percentile", "mean"),
        minimum_development_percentile=("development_percentile", "min"),
        maximum_development_percentile=("development_percentile", "max"),
    )
    grouped["high_share"] = (
        grouped["high_scenario_count"] / grouped["scenarios_available"]
    )
    grouped["low_share"] = (
        grouped["low_scenario_count"] / grouped["scenarios_available"]
    )
    grouped["stability_band"] = "MIXED"
    grouped.loc[grouped["high_share"].eq(1), "stability_band"] = "CONSISTENTLY_HIGH"
    grouped.loc[
        grouped["high_share"].ge(0.5) & grouped["high_share"].lt(1), "stability_band"
    ] = "OFTEN_HIGH"
    grouped.loc[grouped["low_share"].eq(1), "stability_band"] = "CONSISTENTLY_LOW"
    grouped.loc[
        grouped["low_share"].ge(0.5) & grouped["low_share"].lt(1), "stability_band"
    ] = "OFTEN_LOW"
    grouped["result_classification"] = "DEVELOPMENTAL_ANALYTICAL_RESULT"
    grouped["official_ranking_enabled"] = False
    return grouped


def leave_one_out(results: pd.DataFrame) -> pd.DataFrame:
    base = results.loc[
        results["analysis_population"].eq("PRIMARY_ONLY")
        & results["transformation"].eq("WITHIN_SCOPE_PERCENTILE")
        & results["scenario_complete"]
    ]
    reference = base.loc[
        base["scenario_id"].eq("S3_EXPOSURE_HHI_CONCENTRATION_TREND"),
        KEY + ["development_percentile"],
    ]
    rows: list[dict[str, Any]] = []
    for alternative in ["S1_EXPOSURE_ONLY", "S2_EXPOSURE_HHI"]:
        other = base.loc[
            base["scenario_id"].eq(alternative), KEY + ["development_percentile"]
        ]
        merged = reference.merge(other, on=KEY, suffixes=("_reference", "_alternative"))
        rows.append(
            {
                "reference_scenario": "S3_EXPOSURE_HHI_CONCENTRATION_TREND",
                "alternative_scenario": alternative,
                "common_records": len(merged),
                "spearman_correlation": merged["development_percentile_reference"].corr(
                    merged["development_percentile_alternative"], method="spearman"
                ),
                "mean_absolute_percentile_change": (
                    merged["development_percentile_reference"]
                    - merged["development_percentile_alternative"]
                )
                .abs()
                .mean(),
            }
        )
    return pd.DataFrame(rows)


def weight_sensitivity(frame: pd.DataFrame, policy: dict[str, Any]) -> pd.DataFrame:
    transformed = pd.DataFrame(index=frame.index)
    transformed["exposure"] = transform_metric(
        frame,
        policy["metrics"]["exposure_gross"]["source_column"],
        "HIGHER_IS_MORE_VULNERABLE",
        "WITHIN_SCOPE_PERCENTILE",
        policy,
    )
    transformed["concentration"] = transform_metric(
        frame,
        policy["metrics"]["concentration_hhi"]["source_column"],
        "HIGHER_IS_MORE_VULNERABLE",
        "WITHIN_SCOPE_PERCENTILE",
        policy,
    )
    complete = transformed.notna().all(axis=1)
    reference = None
    outputs: dict[str, pd.Series] = {}
    for name, weights in policy["weight_sensitivity"].items():
        score = (
            transformed["exposure"] * weights[0]
            + transformed["concentration"] * weights[1]
        )
        outputs[name] = score.where(complete)
        if name == "EQUAL_DIMENSION_WEIGHT":
            reference = outputs[name]
    require(reference is not None, "Equal-weight reference missing")
    rows = []
    for name, values in outputs.items():
        valid = reference.notna() & values.notna()
        rows.append(
            {
                "weight_scenario": name,
                "common_records": int(valid.sum()),
                "spearman_vs_equal_weight": reference.loc[valid].corr(
                    values.loc[valid], method="spearman"
                ),
                "mean_absolute_index_change": (reference.loc[valid] - values.loc[valid])
                .abs()
                .mean(),
            }
        )
    return pd.DataFrame(rows)


def normalization_sensitivity(results: pd.DataFrame) -> pd.DataFrame:
    base = results.loc[
        results["analysis_population"].eq("PRIMARY_ONLY")
        & results["scenario_id"].eq("S2_EXPOSURE_HHI")
        & results["scenario_complete"]
    ]
    reference = base.loc[
        base["transformation"].eq("WITHIN_SCOPE_PERCENTILE"),
        KEY + ["development_percentile"],
    ]
    rows = []
    for transformation in sorted(base["transformation"].unique()):
        other = base.loc[
            base["transformation"].eq(transformation), KEY + ["development_percentile"]
        ]
        merged = reference.merge(other, on=KEY, suffixes=("_reference", "_alternative"))
        rows.append(
            {
                "reference_transformation": "WITHIN_SCOPE_PERCENTILE",
                "alternative_transformation": transformation,
                "common_records": len(merged),
                "spearman_correlation": merged["development_percentile_reference"].corr(
                    merged["development_percentile_alternative"], method="spearman"
                ),
                "mean_absolute_percentile_change": (
                    merged["development_percentile_reference"]
                    - merged["development_percentile_alternative"]
                )
                .abs()
                .mean(),
            }
        )
    return pd.DataFrame(rows)


def population_sensitivity(results: pd.DataFrame) -> pd.DataFrame:
    base = results.loc[
        results["scenario_id"].eq("S2_EXPOSURE_HHI")
        & results["transformation"].eq("WITHIN_SCOPE_PERCENTILE")
        & results["scenario_complete"]
    ]
    primary = base.loc[
        base["analysis_population"].eq("PRIMARY_ONLY"), KEY + ["development_percentile"]
    ]
    expanded = base.loc[
        base["analysis_population"].eq("PRIMARY_PLUS_LIMITED"),
        KEY + ["development_percentile"],
    ]
    merged = primary.merge(expanded, on=KEY, suffixes=("_primary", "_expanded"))
    return pd.DataFrame(
        [
            {
                "scenario_id": "S2_EXPOSURE_HHI",
                "common_primary_records": len(merged),
                "spearman_correlation": merged["development_percentile_primary"].corr(
                    merged["development_percentile_expanded"], method="spearman"
                ),
                "mean_absolute_percentile_change": (
                    merged["development_percentile_primary"]
                    - merged["development_percentile_expanded"]
                )
                .abs()
                .mean(),
            }
        ]
    )


def main() -> None:
    for path in [POLICY_PATH, FEATURE_POLICY_PATH, PRIMARY_PATH, LIMITED_PATH]:
        require(path.exists(), f"Required input missing: {path}")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    feature_policy = json.loads(FEATURE_POLICY_PATH.read_text(encoding="utf-8"))
    validate_policy(policy)
    require(
        feature_policy["policy_id"] == policy["input_feature_policy_id"],
        "Feature policy contract changed",
    )
    require(
        feature_policy["official_ranking_enabled"] is False, "Feature ranking enabled"
    )

    primary = pd.read_csv(PRIMARY_PATH, dtype={"entity_m49": "string"})
    limited = pd.read_csv(LIMITED_PATH, dtype={"entity_m49": "string"})
    primary["entity_m49"] = normalize_m49(primary["entity_m49"])
    limited["entity_m49"] = normalize_m49(limited["entity_m49"])
    require(len(primary) == 661 and len(limited) == 816, "Input populations changed")
    require(not primary.duplicated(KEY).any(), "Duplicate primary keys")
    require(not limited.duplicated(KEY).any(), "Duplicate limited keys")
    require(
        set(map(tuple, primary[KEY].to_numpy())).isdisjoint(
            set(map(tuple, limited[KEY].to_numpy()))
        ),
        "Primary and limited populations overlap",
    )

    required_columns = set(IDENTITY + ["model_readiness_status", "evidence_confidence"])
    required_columns |= {
        definition["source_column"] for definition in policy["metrics"].values()
    }
    for name, frame in [("primary", primary), ("limited", limited)]:
        missing = required_columns - set(frame.columns)
        require(not missing, f"{name} feature columns missing: {sorted(missing)}")

    transformations = [policy["primary_transformation"]] + policy[
        "sensitivity_transformations"
    ]
    component_frames: list[pd.DataFrame] = []
    result_frames: list[pd.DataFrame] = []
    for population in policy["populations"]:
        frame = population_frame(primary, limited, population)
        for scenario, definition in policy["scenarios"].items():
            for transformation in transformations:
                components, results = build_scenario(
                    frame,
                    population,
                    scenario,
                    definition["metrics"],
                    transformation,
                    policy,
                )
                component_frames.append(components)
                result_frames.append(results)
    components = pd.concat(component_frames, ignore_index=True)
    results = pd.concat(result_frames, ignore_index=True)

    correlations = pairwise_correlations(results)
    overlap = overlap_table(results, policy)
    stability = stability_table(results)
    leave_out = leave_one_out(results)
    weights = weight_sensitivity(primary, policy)
    normalization = normalization_sensitivity(results)
    population = population_sensitivity(results)

    review = results.groupby(
        ["analysis_population", "scenario_id", "transformation"], as_index=False
    ).agg(
        records=("entity_m49", "size"),
        complete_records=("scenario_complete", "sum"),
        incomplete_records=("scenario_complete", lambda x: int((~x).sum())),
        average_development_index=("development_index", "mean"),
        high_band_records=("development_band", lambda x: int((x == "HIGH").sum())),
    )
    review["completion_rate"] = review["complete_records"] / review["records"]
    review["official_ranking_enabled"] = False

    require(not results["official_ranking_enabled"].any(), "Official ranking enabled")
    require(
        results["result_classification"].eq(policy["result_classification"]).all(),
        "Result classification changed",
    )
    require(len(results["scenario_id"].unique()) >= 5, "Too few scenarios emitted")
    require(
        not stability["official_ranking_enabled"].any(), "Stability ranking enabled"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    components.to_csv(COMPONENTS_PATH, index=False)
    results.to_csv(RESULTS_PATH, index=False)
    correlations.to_csv(CORRELATIONS_PATH, index=False)
    overlap.to_csv(OVERLAP_PATH, index=False)
    stability.to_csv(STABILITY_PATH, index=False)
    leave_out.to_csv(LEAVE_ONE_OUT_PATH, index=False)
    weights.to_csv(WEIGHT_PATH, index=False)
    normalization.to_csv(NORMALIZATION_PATH, index=False)
    population.to_csv(POPULATION_PATH, index=False)
    review.to_csv(REVIEW_PATH, index=False)

    report = {
        "dataset": "Core Food developmental model specification",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_commit(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [FEATURE_POLICY_PATH, PRIMARY_PATH, LIMITED_PATH]
        },
        "specification_policy_hash": sha256(POLICY_PATH),
        "authoritative_years": policy["authoritative_years"],
        "primary_records": len(primary),
        "limited_records": len(limited),
        "scenario_count": len(policy["scenarios"]),
        "transformation_count": len(transformations),
        "population_count": len(policy["populations"]),
        "scenario_result_rows": len(results),
        "stability_records": len(stability),
        "controls": {
            "five_or_more_scenarios": len(policy["scenarios"]) >= 5,
            "metric_directions_documented": all(
                definition.get("direction") for definition in policy["metrics"].values()
            ),
            "concentration_not_double_counted": True,
            "transformations_externally_configured": True,
            "primary_and_limited_distinguishable": True,
            "scenario_correlations_calculated": len(correlations) > 0,
            "top_band_overlap_calculated": len(overlap) > 0,
            "leave_one_dimension_out_calculated": len(leave_out) > 0,
            "weight_sensitivity_calculated": len(weights) > 0,
            "normalization_sensitivity_calculated": len(normalization) > 0,
            "population_sensitivity_calculated": len(population) > 0,
            "evidence_confidence_separate": True,
            "official_vulnerability_score_disabled": True,
            "official_ranking_disabled": True,
        },
        "outputs": {
            "components": str(COMPONENTS_PATH.relative_to(ROOT)),
            "results": str(RESULTS_PATH.relative_to(ROOT)),
            "correlations": str(CORRELATIONS_PATH.relative_to(ROOT)),
            "top_band_overlap": str(OVERLAP_PATH.relative_to(ROOT)),
            "band_stability": str(STABILITY_PATH.relative_to(ROOT)),
            "leave_one_dimension_out": str(LEAVE_ONE_OUT_PATH.relative_to(ROOT)),
            "weight_sensitivity": str(WEIGHT_PATH.relative_to(ROOT)),
            "normalization_sensitivity": str(NORMALIZATION_PATH.relative_to(ROOT)),
            "primary_limited_sensitivity": str(POPULATION_PATH.relative_to(ROOT)),
            "specification_review": str(REVIEW_PATH.relative_to(ROOT)),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD DEVELOPMENTAL MODEL SPECIFICATION BUILD COMPLETE")
    print("=" * 72)
    print(f"Primary records: {len(primary):,}")
    print(f"Limited records: {len(limited):,}")
    print(f"Scenarios evaluated: {len(policy['scenarios']):,}")
    print(f"Transformations evaluated: {len(transformations):,}")
    print(f"Population definitions: {len(policy['populations']):,}")
    print(f"Developmental scenario rows: {len(results):,}")
    print("No official vulnerability score or ranking was generated.")
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

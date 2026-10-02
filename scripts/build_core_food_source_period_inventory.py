from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/model_governance/core_food_period_policy.json"
OUT = ROOT / "outputs/tables/core_food_source_inventory"
REPORT = ROOT / "outputs/model_results/core_food_source_period_inventory_summary.json"
INVENTORY_PATH = OUT / "core_food_source_period_inventory.csv"
ISSUES_PATH = OUT / "core_food_source_alignment_issues.csv"
ADMISSION_PATH = OUT / "core_food_external_source_admission.csv"

ALLOWED_ALIGNMENT = {
    "EXACT_PERIOD_MATCH",
    "SUPERSET_FILTERED_TO_PERIOD",
    "PARTIAL_PERIOD_COVERAGE",
    "NO_PERIOD_OVERLAP",
    "UNDATED_STATIC_REFERENCE",
    "PUBLICATION_LAG_REVIEW",
    "INVALID_DATE_FIELD",
    "SOURCE_MISSING",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
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


def compact_years(years: list[int]) -> str:
    return "|".join(str(year) for year in years)


def parse_years(path: Path, date_field: str) -> tuple[list[int], int]:
    if path.suffix.casefold() != ".csv":
        raise ValueError(f"Dated source must be CSV: {path}")
    header = pd.read_csv(path, nrows=0)
    if date_field not in header.columns:
        raise KeyError(f"Date field {date_field!r} missing from {path}")
    values = pd.read_csv(path, usecols=[date_field])[date_field]
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().any():
        years = numeric.dropna().astype(int)
    else:
        parsed = pd.to_datetime(values, errors="coerce")
        years = parsed.dt.year.dropna().astype(int)
    valid = sorted(set(years.loc[years.between(1900, 2100)].tolist()))
    if not valid:
        raise ValueError(f"No valid years found in {path}:{date_field}")
    return valid, len(values)


def row_count(path: Path) -> int | None:
    if path.suffix.casefold() == ".csv":
        return sum(1 for _ in path.open("rb")) - 1
    if path.suffix.casefold() == ".json":
        return 1
    return None


def classify_alignment(
    years: list[int], expected: list[int], publication_lag_known: bool
) -> str:
    if publication_lag_known:
        return "PUBLICATION_LAG_REVIEW"
    observed = set(years)
    target = set(expected)
    if observed == target:
        return "EXACT_PERIOD_MATCH"
    if target < observed:
        return "SUPERSET_FILTERED_TO_PERIOD"
    if observed & target:
        return "PARTIAL_PERIOD_COVERAGE"
    return "NO_PERIOD_OVERLAP"


def primary_admission(
    alignment: str, source_type: str, primary_candidate: bool, policy: dict[str, Any]
) -> tuple[bool, bool, str]:
    if source_type.startswith("STATIC") or source_type in {
        "DERIVED_STATIC",
        "GOVERNED_DERIVED",
    }:
        return False, False, "Static or derived reference; not an annual risk signal"
    if not primary_candidate:
        return False, False, "Source is not proposed for primary model features"
    if alignment == "EXACT_PERIOD_MATCH":
        return True, False, "Exact match to authoritative datathon period"
    if (
        alignment == "SUPERSET_FILTERED_TO_PERIOD"
        and policy["allow_superset_filtering"]
    ):
        return True, False, "Eligible only after strict filtering to datathon years"
    if alignment == "PARTIAL_PERIOD_COVERAGE":
        return False, True, "Partial temporal coverage; sensitivity analysis only"
    return False, False, f"Not admitted because alignment is {alignment}"


def load_external_manifest(policy: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = ROOT / policy["external_manifest_path"]
    if not manifest.exists():
        return []
    frame = pd.read_csv(manifest)
    required = {"source_name", "source_path", "source_type", "date_field"}
    missing = required - set(frame.columns)
    require(not missing, f"External manifest columns missing: {sorted(missing)}")
    if frame["source_name"].duplicated().any():
        raise ValueError("Duplicate source names in external source manifest")
    for column, default in {
        "required": False,
        "primary_candidate": False,
        "publication_lag_known": False,
    }.items():
        if column not in frame:
            frame[column] = default
    return frame.to_dict("records")


def inspect_source(
    source: dict[str, Any], expected: list[int], policy: dict[str, Any]
) -> dict[str, Any]:
    path = ROOT / str(source["source_path"])
    date_field_raw = source.get("date_field")
    date_field = (
        None if pd.isna(date_field_raw) else str(date_field_raw).strip() or None
    )
    source_type = str(source["source_type"])
    required = bool(source.get("required", False))
    primary_candidate = bool(source.get("primary_candidate", False))
    publication_lag_known = bool(source.get("publication_lag_known", False))
    base: dict[str, Any] = {
        "source_name": str(source["source_name"]),
        "source_path": str(source["source_path"]),
        "source_type": source_type,
        "date_field": date_field or "",
        "required": required,
        "primary_candidate": primary_candidate,
        "file_exists": path.exists(),
        "file_size_bytes": path.stat().st_size if path.exists() else None,
        "source_hash": sha256(path),
        "publication_lag_known": publication_lag_known,
    }
    if not path.exists():
        base.update(
            {
                "row_count": None,
                "minimum_year": None,
                "maximum_year": None,
                "years_available": "",
                "year_count": 0,
                "missing_expected_years": compact_years(expected),
                "extra_years": "",
                "alignment_status": "SOURCE_MISSING",
                "primary_model_allowed": False,
                "sensitivity_only": False,
                "admission_reason": "Required source missing"
                if required
                else "Optional source missing",
            }
        )
        return base
    if date_field is None:
        alignment = "UNDATED_STATIC_REFERENCE"
        base.update(
            {
                "row_count": row_count(path),
                "minimum_year": None,
                "maximum_year": None,
                "years_available": "",
                "year_count": 0,
                "missing_expected_years": "",
                "extra_years": "",
                "alignment_status": alignment,
            }
        )
    else:
        try:
            years, count = parse_years(path, date_field)
            alignment = classify_alignment(years, expected, publication_lag_known)
            base.update(
                {
                    "row_count": count,
                    "minimum_year": min(years),
                    "maximum_year": max(years),
                    "years_available": compact_years(years),
                    "year_count": len(years),
                    "missing_expected_years": compact_years(
                        sorted(set(expected) - set(years))
                    ),
                    "extra_years": compact_years(sorted(set(years) - set(expected))),
                    "alignment_status": alignment,
                }
            )
        except (KeyError, ValueError) as error:
            alignment = "INVALID_DATE_FIELD"
            base.update(
                {
                    "row_count": row_count(path),
                    "minimum_year": None,
                    "maximum_year": None,
                    "years_available": "",
                    "year_count": 0,
                    "missing_expected_years": compact_years(expected),
                    "extra_years": "",
                    "alignment_status": alignment,
                    "inspection_error": str(error),
                }
            )
    allowed, sensitivity, reason = primary_admission(
        alignment, source_type, primary_candidate, policy
    )
    base["primary_model_allowed"] = allowed
    base["sensitivity_only"] = sensitivity
    base["admission_reason"] = reason
    return base


def main() -> None:
    require(POLICY_PATH.exists(), f"Period policy missing: {POLICY_PATH}")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    expected = [int(year) for year in policy["expected_years"]]
    require(
        expected == sorted(set(expected)), "Expected years must be unique and sorted"
    )
    require(
        policy["period_policy"] == "DATATHON_SOURCE_ALIGNED", "Invalid period policy"
    )
    require(
        policy["allow_future_information"] is False,
        "Future information must remain prohibited",
    )
    require(
        policy["allow_partial_external_coverage_in_primary"] is False,
        "Partial external coverage cannot enter the primary model",
    )
    require(
        policy["official_ranking_enabled"] is False,
        "Period inventory cannot enable ranking",
    )

    sources = list(policy["sources"]) + load_external_manifest(policy)
    names = [str(source["source_name"]) for source in sources]
    require(len(names) == len(set(names)), "Source names must be unique")
    records = [inspect_source(source, expected, policy) for source in sources]
    inventory = pd.DataFrame(records)

    required_missing = inventory["required"] & ~inventory["file_exists"]
    require(
        not required_missing.any(),
        f"Required sources missing: {inventory.loc[required_missing, 'source_name'].tolist()}",
    )
    authoritative = inventory.loc[
        inventory["source_name"].isin(policy["authoritative_year_sources"])
    ]
    require(
        len(authoritative) == len(policy["authoritative_year_sources"]),
        "Authoritative year source missing from inventory",
    )
    require(
        authoritative["alignment_status"].eq("EXACT_PERIOD_MATCH").all(),
        "Authoritative sources do not exactly match expected datathon years",
    )
    derived_year_sets = [
        {int(value) for value in years.split("|") if value}
        for years in authoritative["years_available"]
    ]
    common_years = sorted(set.intersection(*derived_year_sets))
    require(
        common_years == expected,
        f"Authoritative period mismatch: expected {expected}, derived {common_years}",
    )

    invalid = inventory["alignment_status"].isin(
        {"SOURCE_MISSING", "INVALID_DATE_FIELD", "NO_PERIOD_OVERLAP"}
    )
    primary_partial = inventory["primary_model_allowed"] & inventory[
        "alignment_status"
    ].eq("PARTIAL_PERIOD_COVERAGE")
    require(
        not primary_partial.any(), "Partial-period source admitted to primary model"
    )
    require(
        set(inventory["alignment_status"]) <= ALLOWED_ALIGNMENT,
        "Unknown alignment status emitted",
    )

    issues = inventory.loc[
        invalid
        | inventory["alignment_status"].isin(
            {"PARTIAL_PERIOD_COVERAGE", "PUBLICATION_LAG_REVIEW"}
        )
    ].copy()
    external = inventory.loc[
        inventory["source_type"].str.startswith("EXTERNAL", na=False)
    ].copy()

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    inventory.sort_values(["source_type", "source_name"]).to_csv(
        INVENTORY_PATH, index=False
    )
    issues.sort_values(["alignment_status", "source_name"]).to_csv(
        ISSUES_PATH, index=False
    )
    external.to_csv(ADMISSION_PATH, index=False)

    report = {
        "dataset": "Core Food datathon source-period inventory",
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_commit(),
        "policy_hash": sha256(POLICY_PATH),
        "authoritative_years": common_years,
        "authoritative_year_sources": policy["authoritative_year_sources"],
        "sources_inspected": len(inventory),
        "required_sources": int(inventory["required"].sum()),
        "external_sources": len(external),
        "alignment_counts": {
            str(key): int(value)
            for key, value in inventory["alignment_status"].value_counts().items()
        },
        "issue_count": len(issues),
        "controls": {
            "authoritative_datathon_years_identified": True,
            "required_sources_present": True,
            "authoritative_sources_exact_match": True,
            "external_sources_restricted_to_period": True,
            "partial_external_coverage_not_primary": True,
            "future_information_prohibited": True,
            "source_hashes_recorded": bool(
                inventory.loc[inventory["file_exists"], "source_hash"].notna().all()
            ),
            "official_ranking_disabled": True,
        },
        "outputs": {
            "inventory": str(INVENTORY_PATH.relative_to(ROOT)),
            "issues": str(ISSUES_PATH.relative_to(ROOT)),
            "external_admission": str(ADMISSION_PATH.relative_to(ROOT)),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("=" * 72)
    print("CORE FOOD SOURCE-PERIOD INVENTORY BUILD COMPLETE")
    print("=" * 72)
    print(f"Authoritative datathon years: {compact_years(common_years)}")
    print(f"Sources inspected: {len(inventory):,}")
    print(f"Required sources: {int(inventory['required'].sum()):,}")
    print(f"External sources registered: {len(external):,}")
    print(f"Alignment issues requiring review: {len(issues):,}")
    print("No analytical feature, vulnerability score, or ranking was generated.")
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

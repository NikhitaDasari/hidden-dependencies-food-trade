from __future__ import annotations

import platform
import sys

import duckdb
import numpy
import pandas
import plotly
import requests
import sklearn
import streamlit
import yaml


def main() -> None:
    packages = {
        "Python": sys.version.split()[0],
        "Platform": platform.platform(),
        "pandas": pandas.__version__,
        "numpy": numpy.__version__,
        "duckdb": duckdb.__version__,
        "requests": requests.__version__,
        "scikit-learn": sklearn.__version__,
        "streamlit": streamlit.__version__,
        "plotly": plotly.__version__,
        "PyYAML": yaml.__version__,
    }

    print("=" * 60)
    print("WOMEN IN DATA 2026 ENVIRONMENT VALIDATION")
    print("=" * 60)

    for name, version in packages.items():
        print(f"{name:<20} {version}")

    result = duckdb.sql(
        "SELECT 1 AS environment_ready"
    ).fetchone()[0]

    if result != 1:
        raise RuntimeError("DuckDB validation failed.")

    print("=" * 60)
    print("Environment ready.")
    print("=" * 60)


if __name__ == "__main__":
    main()

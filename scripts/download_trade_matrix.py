from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "faostat" / "detailed_trade_matrix"
ZIP_PATH = RAW_DIR / "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip"
MANIFEST_PATH = RAW_DIR / "trade_matrix_manifest.json"

CANDIDATE_URLS = [
    "https://bulks-faostat.fao.org/production/Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip",
    "https://bulks-faostat.fao.org/production/Trade_DetailedTradeMatrix_E_All_Data.zip",
]


def calculate_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def download_file(url: str, destination: Path) -> None:
    temporary_path = destination.with_suffix(".part")

    with requests.get(
        url,
        stream=True,
        timeout=(30, 900),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
            ),
            "Accept": "application/zip,application/octet-stream,*/*",
            "Referer": "https://www.fao.org/",
        },
    ) as response:
        response.raise_for_status()

        with temporary_path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)

    if not zipfile.is_zipfile(temporary_path):
        temporary_path.unlink(missing_ok=True)
        raise ValueError("Downloaded response is not a valid ZIP archive.")

    temporary_path.replace(destination)


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    successful_url = None
    errors = []

    for url in CANDIDATE_URLS:
        print(f"Trying: {url}")

        try:
            download_file(url, ZIP_PATH)
            successful_url = url
            print(f"Download succeeded: {ZIP_PATH}")
            break
        except Exception as error:
            errors.append({"url": url, "error": str(error)})
            print(f"Failed: {error}")

    if successful_url is None:
        print("\nNo validated endpoint succeeded.", file=sys.stderr)
        print(
            "Open the FAOSTAT Trade Matrix dataset page and copy the current "
            "normalized bulk ZIP URL.",
            file=sys.stderr,
        )

        for failure in errors:
            print(
                f"- {failure['url']}: {failure['error']}",
                file=sys.stderr,
            )

        return 1

    manifest = {
        "dataset": "FAOSTAT Detailed Trade Matrix",
        "provider": "Food and Agriculture Organization",
        "source_page": "https://www.fao.org/faostat/en/#data/TM",
        "download_url": successful_url,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_file": str(ZIP_PATH.relative_to(ROOT)),
        "file_size_bytes": ZIP_PATH.stat().st_size,
        "sha256": calculate_sha256(ZIP_PATH),
        "archive_validated": True,
    }

    with MANIFEST_PATH.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    print("\nDownload manifest:")
    print(json.dumps(manifest, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Download annual ERA5 solar data from the Open-Meteo archive API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY_ROOT / "config" / "pv_config.json"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "data" / "raw"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARIABLES = (
    "temperature_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
    "global_tilted_irradiance",
)


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        config = json.load(file)

    required = {
        "latitude",
        "longitude",
        "start_year",
        "end_year",
        "model",
        "peak_power_kw",
        "technology",
        "mounting",
        "slope",
        "azimuth",
        "system_loss_percent",
        "temperature_coefficient_per_c",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise ValueError(f"Missing configuration keys: {', '.join(missing)}")
    if config["start_year"] > config["end_year"]:
        raise ValueError("start_year must not be greater than end_year")
    if config["peak_power_kw"] <= 0:
        raise ValueError("peak_power_kw must be greater than zero")
    return config


def api_parameters(config: dict[str, Any], year: int) -> dict[str, Any]:
    return {
        "latitude": config["latitude"],
        "longitude": config["longitude"],
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": ",".join(HOURLY_VARIABLES),
        "models": str(config["model"]).lower(),
        "tilt": config["slope"],
        "azimuth": config["azimuth"],
        "timezone": "GMT",
        "wind_speed_unit": "ms",
    }


def http_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def validate_response(payload: dict[str, Any], year: int) -> None:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError(f"Open-Meteo response for {year} has no hourly object")
    missing = [name for name in ("time", *HOURLY_VARIABLES) if name not in hourly]
    if missing:
        raise ValueError(
            f"Open-Meteo response for {year} is missing: {', '.join(missing)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing annual raw files."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config.resolve())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    skipped = 0
    failures: list[tuple[int, str]] = []

    with http_session() as session:
        for year in range(int(config["start_year"]), int(config["end_year"]) + 1):
            output = output_dir / f"open_meteo_era5_{year}.json"
            if output.exists() and not args.force:
                print(f"[{year}] Existing raw file retained: {output}", flush=True)
                skipped += 1
                continue

            print(f"[{year}] Requesting Open-Meteo ERA5 data...", flush=True)
            try:
                response = session.get(
                    OPEN_METEO_ARCHIVE_URL,
                    params=api_parameters(config, year),
                    timeout=(30, 300),
                )
                response.raise_for_status()
                payload = response.json()
                validate_response(payload, year)
            except (requests.RequestException, ValueError) as error:
                failures.append((year, str(error)))
                print(f"[{year}] Download failed: {error}", flush=True)
                continue

            temporary_output = output.with_suffix(output.suffix + ".tmp")
            temporary_output.write_bytes(response.content)
            temporary_output.replace(output)
            downloaded += 1
            print(f"[{year}] Response saved: {output}", flush=True)

    print(f"Download complete: {downloaded} downloaded, {skipped} retained.")
    if failures:
        failed_years = ", ".join(str(year) for year, _ in failures)
        raise RuntimeError(f"Open-Meteo download failed for years: {failed_years}")


if __name__ == "__main__":
    main()

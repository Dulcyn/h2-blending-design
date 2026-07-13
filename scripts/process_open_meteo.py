"""Convert annual Open-Meteo ERA5 files into an hourly PV capacity-factor dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from pvlib.pvsystem import pvwatts_dc
from pvlib.temperature import faiman


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPOSITORY_ROOT / "config" / "pv_config.json"
DEFAULT_INPUT_DIR = REPOSITORY_ROOT / "data" / "raw"
DEFAULT_ALIGNMENT = REPOSITORY_ROOT / "data" / "ppnet_metar.csv"
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT / "data" / "processed" / "pv_capacity_factor_ppnet_2013_2019.csv"
)
DEFAULT_SUMMARY = REPOSITORY_ROOT / "data" / "processed" / "pv_dataset_summary.json"
RAW_COLUMNS = {
    "temperature_2m": "air_temperature_c",
    "wind_speed_10m": "wind_speed_10m_m_s",
    "shortwave_radiation": "ghi_w_m2",
    "direct_normal_irradiance": "dni_w_m2",
    "diffuse_radiation": "dhi_w_m2",
    "global_tilted_irradiance": "irradiance_plane_of_array_w_m2",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_annual_data(
    config: dict[str, Any], input_dir: Path
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    years = range(int(config["start_year"]), int(config["end_year"]) + 1)
    paths = [input_dir / f"open_meteo_era5_{year}.json" for year in years]
    missing_files = [str(path) for path in paths if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(
            "Missing annual raw files:\n" + "\n".join(missing_files)
        )

    frames: list[pd.DataFrame] = []
    sources: list[dict[str, Any]] = []
    required = {"time", *RAW_COLUMNS}
    for path in paths:
        payload = load_json(path)
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            raise ValueError(f"{path} has no hourly object")
        missing_columns = sorted(required - hourly.keys())
        if missing_columns:
            raise ValueError(f"{path} is missing fields: {', '.join(missing_columns)}")

        frame = pd.DataFrame(hourly)
        frames.append(frame)
        try:
            source_file = str(path.relative_to(REPOSITORY_ROOT))
        except ValueError:
            source_file = str(path)
        sources.append(
            {
                "file": source_file,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "timezone": payload.get("timezone"),
                "hourly_units": payload.get("hourly_units", {}),
            }
        )

    return pd.concat(frames, ignore_index=True), sources


def examples(values: pd.Index | pd.Series, limit: int = 10) -> list[str]:
    return [str(value) for value in values[:limit]]


def load_alignment(path: Path) -> tuple[pd.Series, dict[str, Any]]:
    date_columns = ["year", "month", "day", "hour"]
    gas_data = pd.read_csv(path, sep=";", usecols=date_columns)
    timestamps = pd.to_datetime(gas_data[date_columns], utc=True, errors="coerce")
    invalid_count = int(timestamps.isna().sum())
    duplicate_count = int(timestamps.duplicated(keep="first").sum())
    if invalid_count or duplicate_count:
        raise ValueError(
            "Alignment file must contain unique valid hourly timestamps; "
            f"invalid={invalid_count}, duplicates={duplicate_count}"
        )
    metadata = {
        "file": str(path.relative_to(REPOSITORY_ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": int(len(timestamps)),
        "timestamp_min": timestamps.min().isoformat(),
        "timestamp_max": timestamps.max().isoformat(),
        "timezone_assumption": "UTC",
        "chronological_order": bool(timestamps.is_monotonic_increasing),
        "duplicate_timestamp_count": duplicate_count,
        "invalid_timestamp_count": invalid_count,
    }
    return timestamps, metadata


def process(
    config_path: Path,
    input_dir: Path,
    alignment_path: Path,
    output_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    config = load_json(config_path)
    source, sources = load_annual_data(config, input_dir)
    timestamps = pd.to_datetime(source["time"], utc=True, errors="coerce")
    alignment_timestamps, alignment_metadata = load_alignment(alignment_path)

    weather = pd.DataFrame({"timestamp": timestamps})
    for raw_name, output_name in RAW_COLUMNS.items():
        weather[output_name] = pd.to_numeric(source[raw_name], errors="coerce")

    source_ordered = bool(weather["timestamp"].is_monotonic_increasing)
    source_duplicate_mask = weather["timestamp"].duplicated(keep=False) & weather[
        "timestamp"
    ].notna()
    source_duplicate_count = int(
        weather["timestamp"].duplicated(keep="first").sum()
    )
    source_duplicate_values = weather.loc[
        source_duplicate_mask, "timestamp"
    ].drop_duplicates().sort_values()
    source_invalid_timestamp_count = int(weather["timestamp"].isna().sum())
    if source_duplicate_count:
        raise ValueError("Raw Open-Meteo files contain duplicate timestamps")

    weather = weather.sort_values(
        "timestamp", kind="stable", na_position="last"
    ).reset_index(drop=True)
    frame = pd.DataFrame({"timestamp": alignment_timestamps}).merge(
        weather,
        on="timestamp",
        how="left",
        validate="one_to_one",
    )
    frame.insert(1, "year", frame["timestamp"].dt.year.astype("Int64"))
    frame.insert(2, "month", frame["timestamp"].dt.month.astype("Int64"))
    frame.insert(3, "day", frame["timestamp"].dt.day.astype("Int64"))
    frame.insert(4, "hour", frame["timestamp"].dt.hour.astype("Int64"))

    poa = frame["irradiance_plane_of_array_w_m2"]
    frame["cell_temperature_c"] = faiman(
        poa,
        frame["air_temperature_c"],
        frame["wind_speed_10m_m_s"],
    )
    peak_power_w = float(config["peak_power_kw"]) * 1000
    dc_power_w = pvwatts_dc(
        poa,
        frame["cell_temperature_c"],
        peak_power_w,
        float(config["temperature_coefficient_per_c"]),
    )
    retained_fraction = 1 - float(config["system_loss_percent"]) / 100
    frame["pv_power_kw"] = (dc_power_w * retained_fraction / 1000).clip(lower=0)
    frame["pv_capacity_factor"] = (
        frame["pv_power_kw"] / float(config["peak_power_kw"])
    )

    valid_timestamps = frame["timestamp"].dropna()
    expected_timestamps = pd.DatetimeIndex(alignment_timestamps)
    observed_timestamps = pd.DatetimeIndex(weather["timestamp"].dropna().unique())
    missing_hours = expected_timestamps.difference(observed_timestamps)
    output_timestamps = pd.DatetimeIndex(valid_timestamps.drop_duplicates())
    unexpected_hours = output_timestamps.difference(expected_timestamps)

    requested_years = sorted(int(year) for year in valid_timestamps.dt.year.unique())
    observations_by_year = frame.groupby("year", dropna=True).size().to_dict()
    annual_generation = frame.groupby("year", dropna=True)["pv_power_kw"].sum(
        min_count=1
    )
    present_years = sorted(int(year) for year in frame["year"].dropna().unique())
    missing_years = sorted(set(requested_years) - set(present_years))
    capacity_factor = frame["pv_capacity_factor"]
    negative_mask = capacity_factor < 0
    above_one_mask = capacity_factor > 1

    expected_counts = alignment_timestamps.dt.year.value_counts().to_dict()
    expected_by_year = {
        str(year): int(expected_counts.get(year, 0)) for year in requested_years
    }
    actual_by_year = {
        str(year): int(observations_by_year.get(year, 0)) for year in requested_years
    }
    generation_by_year = {
        str(year): (
            round(
                float(annual_generation.loc[year])
                / float(config["peak_power_kw"]),
                6,
            )
            if year in annual_generation.index and pd.notna(annual_generation.loc[year])
            else None
        )
        for year in requested_years
    }
    missing_values = {
        column: int(frame[column].isna().sum()) for column in frame.columns
    }

    summary: dict[str, Any] = {
        "source_files": sources,
        "gas_dataset_alignment": alignment_metadata,
        "configuration": config,
        "pv_model": {
            "library": "pvlib",
            "dc_model": "PVWatts",
            "cell_temperature_model": "Faiman",
            "system_losses_applied_percent": config["system_loss_percent"],
            "upper_power_clipping_applied": False,
        },
        "row_count": int(len(frame)),
        "timestamp_min": (
            valid_timestamps.min().isoformat() if not valid_timestamps.empty else None
        ),
        "timestamp_max": (
            valid_timestamps.max().isoformat() if not valid_timestamps.empty else None
        ),
        "validation": {
            "missing_values_by_column": missing_values,
            "invalid_timestamp_count": int(frame["timestamp"].isna().sum()),
            "duplicate_timestamp_count": int(
                frame["timestamp"].duplicated(keep="first").sum()
            ),
            "duplicate_timestamps": [],
            "raw_source_invalid_timestamp_count": source_invalid_timestamp_count,
            "raw_source_duplicate_timestamp_count": source_duplicate_count,
            "raw_source_duplicate_timestamps": examples(source_duplicate_values),
            "source_chronological_order": source_ordered,
            "alignment_chronological_order": alignment_metadata[
                "chronological_order"
            ],
            "output_chronological_order": bool(valid_timestamps.is_monotonic_increasing),
            "missing_hour_count": int(len(missing_hours)),
            "missing_hours_sample": examples(missing_hours),
            "unexpected_hour_count": int(len(unexpected_hours)),
            "unexpected_hours_sample": examples(unexpected_hours),
            "requested_years": requested_years,
            "present_years": present_years,
            "missing_years": missing_years,
            "observations_by_year": actual_by_year,
            "expected_observations_by_year": expected_by_year,
            "negative_capacity_factor_count": int(negative_mask.sum()),
            "capacity_factor_above_one_count": int(above_one_mask.sum()),
            "capacity_factor_min": round(float(capacity_factor.min()), 9),
            "capacity_factor_max": round(float(capacity_factor.max()), 9),
            "annual_generation_kwh_per_kwp": generation_by_year,
        },
    }

    required_columns = [
        "timestamp",
        "year",
        "month",
        "day",
        "hour",
        "pv_power_kw",
        "pv_capacity_factor",
    ]
    optional_columns = [
        column for column in frame.columns if column not in required_columns
    ]
    csv_frame = frame[required_columns + optional_columns].copy()
    csv_frame["timestamp"] = csv_frame["timestamp"].dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_frame.to_csv(output_path, index=False, float_format="%.9g")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--alignment-file", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve()
    config = load_json(config_path)
    alignment_path = (
        args.alignment_file.resolve()
        if args.alignment_file
        else REPOSITORY_ROOT / config.get("alignment_file", DEFAULT_ALIGNMENT)
    )
    summary = process(
        config_path,
        args.input_dir.resolve(),
        alignment_path.resolve(),
        args.output.resolve(),
        args.summary.resolve(),
    )
    validation = summary["validation"]
    print(f"Processed {summary['row_count']} hourly observations.")
    print(f"Missing hours: {validation['missing_hour_count']}")
    print(f"Duplicate timestamps: {validation['duplicate_timestamp_count']}")
    print(f"Processed CSV saved to: {args.output.resolve()}")
    print(f"Validation summary saved to: {args.summary.resolve()}")


if __name__ == "__main__":
    main()

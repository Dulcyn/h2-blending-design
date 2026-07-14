"""Create one aligned full-year gas and PV scenario for optimization.

Run this script from the repository root.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


GAS_FILE = Path("data/gas/ppnet_metar.csv")
PV_FILE = Path("data/pv/processed/pv_capacity_factor_ppnet_2013_2019.csv")
PARAMETERS_FILE = Path("data/parameters.json")
OUTPUT_DIR = Path("data/scenarios/yearly")

OUTLIER_IQR_MULTIPLIER = 3.0
MAX_INVALID_GAS_FRACTION = 0.01
NEIGHBOR_OFFSETS_DAYS = (-14, -7, 7, 14)


def expected_timestamps(year: int) -> pd.DatetimeIndex:
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
    return pd.date_range(start, end, freq="h", inclusive="left")


def load_gas_lhv() -> float:
    with PARAMETERS_FILE.open(encoding="utf-8") as file:
        parameters = json.load(file)
    lhv = float(parameters["gas"]["lhv"])
    if lhv <= 0:
        raise ValueError("Gas LHV must be positive")
    return lhv


def load_aligned_data() -> tuple[pd.DataFrame, float]:
    date_columns = ["year", "month", "day", "hour"]
    gas = pd.read_csv(GAS_FILE, sep=";", usecols=[*date_columns, "consumption"])
    gas_frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(gas[date_columns], utc=True, errors="coerce"),
            "gas_consumption_sm3_h": pd.to_numeric(gas["consumption"], errors="coerce"),
        }
    )
    pv = pd.read_csv(PV_FILE, usecols=["timestamp", "pv_capacity_factor"])
    pv_frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(pv["timestamp"], utc=True, errors="coerce"),
            "pv_capacity_factor": pd.to_numeric(pv["pv_capacity_factor"], errors="coerce"),
        }
    )

    for name, frame in (("gas", gas_frame), ("PV", pv_frame)):
        if frame["timestamp"].isna().any():
            raise ValueError(f"{name} input contains invalid timestamps")
        if frame["timestamp"].duplicated().any():
            raise ValueError(f"{name} input contains duplicated timestamps")

    hourly = gas_frame.merge(pv_frame, on="timestamp", how="inner", validate="one_to_one")
    hourly = hourly.sort_values("timestamp", ignore_index=True)
    if len(hourly) != len(gas_frame) or len(hourly) != len(pv_frame):
        raise ValueError("Gas and PV timestamps are not aligned exactly")
    if hourly["pv_capacity_factor"].isna().any() or not hourly["pv_capacity_factor"].between(0, 1).all():
        raise ValueError("PV capacity factor must be complete and between zero and one")

    valid_gas = hourly.loc[
        hourly["gas_consumption_sm3_h"].notna() & hourly["gas_consumption_sm3_h"].ge(0),
        "gas_consumption_sm3_h",
    ]
    first_quartile, third_quartile = valid_gas.quantile([0.25, 0.75])
    gas_upper_fence = third_quartile + OUTLIER_IQR_MULTIPLIER * (third_quartile - first_quartile)
    hourly["gas_invalid"] = (
        hourly["gas_consumption_sm3_h"].isna()
        | hourly["gas_consumption_sm3_h"].lt(0)
        | hourly["gas_consumption_sm3_h"].gt(gas_upper_fence)
    )
    return hourly, float(gas_upper_fence)


def full_years(hourly: pd.DataFrame) -> list[int]:
    years = []
    for year, frame in hourly.groupby(hourly["timestamp"].dt.year, sort=True):
        timestamps = pd.DatetimeIndex(frame["timestamp"])
        if timestamps.equals(expected_timestamps(int(year))):
            years.append(int(year))
    if not years:
        raise ValueError("No complete calendar year is available")
    return years


def impute_gas(frame: pd.DataFrame) -> pd.Series:
    gas = frame.set_index("timestamp")["gas_consumption_sm3_h"].copy()
    invalid = frame.set_index("timestamp")["gas_invalid"]
    gas.loc[invalid] = np.nan
    observed = gas.dropna()

    for timestamp in gas.index[gas.isna()]:
        neighbors = [
            observed.get(timestamp + pd.Timedelta(days=offset), np.nan)
            for offset in NEIGHBOR_OFFSETS_DAYS
        ]
        neighbors = [value for value in neighbors if pd.notna(value)]
        if neighbors:
            gas.loc[timestamp] = float(np.median(neighbors))

    gas = gas.interpolate(method="time", limit_direction="both")
    if gas.isna().any() or gas.lt(0).any():
        raise ValueError("Gas imputation produced invalid values")
    return gas


def select_year(hourly: pd.DataFrame) -> tuple[int, pd.DataFrame, dict[int, pd.Series]]:
    records = []
    cleaned: dict[int, pd.Series] = {}
    for year in full_years(hourly):
        frame = hourly.loc[hourly["timestamp"].dt.year.eq(year)].copy()
        gas = impute_gas(frame)
        cleaned[year] = gas
        invalid_count = int(frame["gas_invalid"].sum())
        records.append(
            {
                "year": year,
                "hours": len(frame),
                "invalid_gas_hours": invalid_count,
                "invalid_gas_fraction": invalid_count / len(frame),
                "gas_mean_sm3_h": float(gas.mean()),
                "pv_yield_kwh_kwp": float(frame["pv_capacity_factor"].sum()),
            }
        )

    selection = pd.DataFrame(records).set_index("year")
    selection["eligible"] = selection["invalid_gas_fraction"].le(MAX_INVALID_GAS_FRACTION)
    eligible = selection.loc[selection["eligible"]].copy()
    if eligible.empty:
        raise ValueError("No full year satisfies the gas-data quality threshold")

    attributes = eligible[["gas_mean_sm3_h", "pv_yield_kwh_kwp"]]
    standard_deviation = attributes.std(ddof=0)
    if standard_deviation.eq(0).any():
        raise ValueError("Year-selection attributes must have nonzero variation")
    standardized = (attributes - attributes.mean()) / standard_deviation
    eligible["joint_distance"] = np.sqrt(0.5 * standardized.pow(2).sum(axis=1))
    selection["joint_distance"] = eligible["joint_distance"]
    selected_year = int(eligible["joint_distance"].idxmin())
    selection["selected"] = selection.index == selected_year
    return selected_year, selection.reset_index(), cleaned


def write_outputs(
    hourly: pd.DataFrame,
    selected_year: int,
    selection: pd.DataFrame,
    cleaned: dict[int, pd.Series],
    gas_upper_fence: float,
    gas_lhv: float,
) -> None:
    frame = hourly.loc[hourly["timestamp"].dt.year.eq(selected_year)].copy()
    frame["gas_consumption_sm3_h"] = cleaned[selected_year].to_numpy()
    frame["hour_of_year"] = np.arange(len(frame))
    frame["gas_demand_mw"] = frame["gas_consumption_sm3_h"] * gas_lhv / 1000

    timestamp = frame["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    gas_output = pd.DataFrame(
        {
            "timestamp": timestamp,
            "hour_of_year": frame["hour_of_year"],
            "gas_consumption_sm3_h": frame["gas_consumption_sm3_h"],
            "gas_demand_mw": frame["gas_demand_mw"],
            "gas_imputed": frame["gas_invalid"],
        }
    )
    pv_output = pd.DataFrame(
        {
            "timestamp": timestamp,
            "hour_of_year": frame["hour_of_year"],
            "pv_capacity_factor": frame["pv_capacity_factor"],
        }
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gas_output.to_csv(OUTPUT_DIR / f"gas_{selected_year}.csv", index=False, lineterminator="\n")
    pv_output.to_csv(OUTPUT_DIR / f"pv_{selected_year}.csv", index=False, lineterminator="\n")
    selection.to_csv(OUTPUT_DIR / "year_selection.csv", index=False, lineterminator="\n")

    selected = selection.loc[selection["selected"]].iloc[0]
    metadata = {
        "selected_year": selected_year,
        "selection_method": "Minimum equal-weight standardized distance to the eligible-year centroid using annual mean gas consumption and annual PV yield.",
        "quality_threshold": {"maximum_invalid_gas_fraction": MAX_INVALID_GAS_FRACTION},
        "gas_imputation": "Median of valid observations at the same hour 7 and 14 days before and after; time interpolation is the fallback.",
        "source_files": {"gas": str(GAS_FILE), "pv": str(PV_FILE), "parameters": str(PARAMETERS_FILE)},
        "start_timestamp": gas_output["timestamp"].iloc[0],
        "end_timestamp": gas_output["timestamp"].iloc[-1],
        "observations": len(frame),
        "invalid_gas_hours_repaired": int(selected["invalid_gas_hours"]),
        "gas_upper_fence_sm3_h": gas_upper_fence,
        "gas_lhv_kwh_sm3": gas_lhv,
        "annual_gas_energy_mwh": float(gas_output["gas_demand_mw"].sum()),
        "annual_pv_yield_kwh_kwp": float(pv_output["pv_capacity_factor"].sum()),
        "joint_selection_distance": float(selected["joint_distance"]),
    }
    with (OUTPUT_DIR / "scenario_metadata.json").open("w", encoding="utf-8", newline="\n") as file:
        json.dump(metadata, file, indent=2)
        file.write("\n")


def main() -> None:
    hourly, gas_upper_fence = load_aligned_data()
    selected_year, selection, cleaned = select_year(hourly)
    write_outputs(hourly, selected_year, selection, cleaned, gas_upper_fence, load_gas_lhv())
    print(f"Selected year: {selected_year}")
    print(f"Outputs written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

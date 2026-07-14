"""Create joint representative gas-demand and PV weeks with k-medoids.

The daily representative-scenario pipeline is independent and remains unchanged.
Run this script from the repository root.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from create_representative_scenarios import (
    configure_plot_style,
    fit_kmedoids,
    joint_distance,
    order_scenarios,
    standardize,
    write_csv,
)


GAS_FILE = Path("data/gas/ppnet_metar.csv")
PV_FILE = Path("data/pv/processed/pv_capacity_factor_ppnet_2013_2019.csv")
PARAMETERS_FILE = Path("data/parameters.json")
OUTPUT_DIR = Path("data/scenarios/weekly")

CLUSTERS = 11
RESTARTS = 8
MAX_ITERATIONS = 100
SEED = 42
OUTLIER_IQR_MULTIPLIER = 3.0
HOURS_PER_WEEK = 168
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def load_gas_lhv(path: Path) -> float:
    with path.open(encoding="utf-8") as file:
        parameters = json.load(file)
    lhv = float(parameters["gas"]["lhv"])
    if lhv <= 0:
        raise ValueError("Gas LHV must be greater than zero")
    return lhv


def load_aligned_hourly_data(
    gas_path: Path,
    pv_path: Path,
    outlier_iqr_multiplier: float,
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    if outlier_iqr_multiplier <= 0:
        raise ValueError("OUTLIER_IQR_MULTIPLIER must be positive")

    date_columns = ["year", "month", "day", "hour"]
    gas = pd.read_csv(
        gas_path,
        sep=";",
        usecols=[*date_columns, "consumption"],
    )
    gas_frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                gas[date_columns], utc=True, errors="coerce"
            ),
            "gas_consumption_sm3_h": pd.to_numeric(
                gas["consumption"], errors="coerce"
            ),
        }
    )

    pv = pd.read_csv(pv_path, usecols=["timestamp", "pv_capacity_factor"])
    pv_frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(pv["timestamp"], utc=True, errors="coerce"),
            "pv_capacity_factor": pd.to_numeric(
                pv["pv_capacity_factor"], errors="coerce"
            ),
        }
    )

    for name, frame in (("gas", gas_frame), ("PV", pv_frame)):
        if frame["timestamp"].isna().any():
            raise ValueError(f"{name} input contains invalid timestamps")
        if frame["timestamp"].duplicated().any():
            raise ValueError(f"{name} input contains duplicated timestamps")

    hourly = gas_frame.merge(
        pv_frame,
        on="timestamp",
        how="inner",
        validate="one_to_one",
    ).sort_values("timestamp", ignore_index=True)
    if len(hourly) != len(gas_frame) or len(hourly) != len(pv_frame):
        raise ValueError("Gas and PV timestamps are not aligned exactly")

    dates = hourly["timestamp"].dt.floor("D")
    hourly["week_start"] = dates - pd.to_timedelta(
        hourly["timestamp"].dt.weekday, unit="D"
    )
    hourly["hour_of_week"] = (
        hourly["timestamp"].dt.weekday * 24 + hourly["timestamp"].dt.hour
    )

    missing_values = hourly[
        ["gas_consumption_sm3_h", "pv_capacity_factor"]
    ].isna().any(axis=1)
    valid_gas = hourly.loc[
        hourly["gas_consumption_sm3_h"].notna()
        & hourly["gas_consumption_sm3_h"].ge(0),
        "gas_consumption_sm3_h",
    ]
    first_quartile, third_quartile = valid_gas.quantile([0.25, 0.75])
    interquartile_range = third_quartile - first_quartile
    gas_upper_fence = third_quartile + outlier_iqr_multiplier * interquartile_range

    negative_gas = hourly["gas_consumption_sm3_h"].lt(0)
    gas_outliers = hourly["gas_consumption_sm3_h"].gt(gas_upper_fence)
    invalid_pv = (
        hourly["pv_capacity_factor"].notna()
        & ~hourly["pv_capacity_factor"].between(0, 1)
    )
    invalid_values = missing_values | negative_gas | gas_outliers | invalid_pv

    week_counts = hourly.groupby("week_start", sort=True).size()
    partial_weeks = set(week_counts[week_counts.ne(HOURS_PER_WEEK)].index)
    data_invalid_weeks = set(hourly.loc[invalid_values, "week_start"])
    excluded_weeks = partial_weeks | data_invalid_weeks
    hourly = hourly.loc[~hourly["week_start"].isin(excluded_weeks)].copy()

    retained_counts = hourly.groupby("week_start", sort=True).size()
    if not retained_counts.eq(HOURS_PER_WEEK).all():
        invalid = retained_counts[retained_counts.ne(HOURS_PER_WEEK)].index
        examples = [date.strftime("%Y-%m-%d") for date in invalid[:5]]
        raise ValueError(f"Incomplete weeks found: {', '.join(examples)}")
    if (hourly["gas_consumption_sm3_h"] < 0).any():
        raise ValueError("Gas consumption contains negative values")
    if not hourly["pv_capacity_factor"].between(0, 1).all():
        raise ValueError("PV capacity factor must be between zero and one")

    quality = {
        "aligned_hour_count": len(gas_frame),
        "candidate_week_count": len(week_counts),
        "valid_week_count": len(retained_counts),
        "missing_hour_count": int(missing_values.sum()),
        "negative_gas_hour_count": int(negative_gas.sum()),
        "gas_outlier_hour_count": int(gas_outliers.sum()),
        "invalid_pv_hour_count": int(invalid_pv.sum()),
        "partial_week_count": len(partial_weeks),
        "data_invalid_week_count": len(data_invalid_weeks),
        "excluded_week_count": len(excluded_weeks),
        "gas_upper_fence_sm3_h": float(gas_upper_fence),
    }
    return hourly, quality


def weekly_matrices(
    hourly: pd.DataFrame,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    gas = hourly.pivot(
        index="week_start",
        columns="hour_of_week",
        values="gas_consumption_sm3_h",
    ).reindex(columns=range(HOURS_PER_WEEK))
    pv = hourly.pivot(
        index="week_start",
        columns="hour_of_week",
        values="pv_capacity_factor",
    ).reindex(columns=range(HOURS_PER_WEEK))
    if gas.isna().any().any() or pv.isna().any().any():
        raise ValueError("Weekly profiles must contain every hour from 0 through 167")
    if not gas.index.equals(pv.index):
        raise ValueError("Weekly gas and PV indexes do not match")
    if not gas.index.to_series().dt.weekday.eq(0).all():
        raise ValueError("Every representative week must start on Monday")
    return gas.index, gas.to_numpy(dtype=float), pv.to_numpy(dtype=float)


def extreme_weeks(gas: np.ndarray, pv: np.ndarray) -> dict[int, list[str]]:
    gas_total = gas.sum(axis=1)
    gas_peak = gas.max(axis=1)
    pv_total = pv.sum(axis=1)
    gas_weekly_z = (gas_total - gas_total.mean()) / gas_total.std()
    pv_weekly_z = (pv_total - pv_total.mean()) / pv_total.std()

    reasons: dict[int, list[str]] = defaultdict(list)
    candidates = (
        (int(np.argmax(gas_total)), "maximum_weekly_gas"),
        (int(np.argmax(gas_peak)), "maximum_hourly_gas"),
        (int(np.argmax(gas_weekly_z - pv_weekly_z)), "high_gas_low_pv"),
        (int(np.argmin(gas_weekly_z + pv_weekly_z)), "low_gas_low_pv"),
        (int(np.argmin(pv_total)), "minimum_weekly_pv"),
        (int(np.argmax(pv_total)), "maximum_weekly_pv"),
    )
    for index, reason in candidates:
        reasons[index].append(reason)
    return dict(reasons)


def scenario_frames(
    week_starts: pd.DatetimeIndex,
    gas: np.ndarray,
    pv: np.ndarray,
    medoids: np.ndarray,
    labels: np.ndarray,
    distances: np.ndarray,
    extreme_reasons: dict[int, list[str]],
    gas_lhv: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scenario_names = [f"p{index}" for index in range(1, len(medoids) + 1)]
    gas_mw = gas[medoids] * gas_lhv / 1000
    hour_of_week = np.arange(HOURS_PER_WEEK)
    gas_frame = pd.DataFrame(
        {
            "hour_of_week": hour_of_week,
            "day_of_week": np.repeat(DAY_NAMES, 24),
            "hour": np.tile(np.arange(24), 7),
        }
    )
    pv_frame = gas_frame.copy()
    metadata_rows = []

    for cluster, (name, medoid) in enumerate(zip(scenario_names, medoids)):
        members = np.flatnonzero(labels == cluster)
        assignment_distances = distances[members, medoid]
        gas_frame[name] = gas_mw[cluster]
        pv_frame[name] = pv[medoid]
        reasons = extreme_reasons.get(int(medoid), [])
        week_start = week_starts[medoid]
        metadata_rows.append(
            {
                "scenario": name,
                "source_week_start": week_start.strftime("%Y-%m-%d"),
                "source_week_end": (week_start + pd.Timedelta(days=6)).strftime(
                    "%Y-%m-%d"
                ),
                "scenario_type": "extreme" if reasons else "typical",
                "extreme_reason": ";".join(reasons),
                "weight_weeks": len(members),
                "probability": len(members) / len(week_starts),
                "weekly_gas_energy_mwh": gas_mw[cluster].sum(),
                "peak_gas_demand_mw": gas_mw[cluster].max(),
                "weekly_pv_energy_kwh_per_kwp": pv[medoid].sum(),
                "mean_assignment_distance": assignment_distances.mean(),
                "max_assignment_distance": assignment_distances.max(),
            }
        )

    metadata = pd.DataFrame(metadata_rows)
    if int(metadata["weight_weeks"].sum()) != len(week_starts):
        raise RuntimeError("Scenario weights do not cover every input week")
    if not np.isclose(metadata["probability"].sum(), 1.0):
        raise RuntimeError("Scenario probabilities do not sum to one")
    return gas_frame, pv_frame, metadata


def write_pca_plot(
    gas: np.ndarray,
    pv: np.ndarray,
    medoids: np.ndarray,
    labels: np.ndarray,
    extreme_reasons: dict[int, list[str]],
    path: Path,
) -> np.ndarray:
    features = np.hstack((standardize(gas), standardize(pv))).astype(float)
    centered = features - features.mean(axis=0)
    _, singular_values, components = np.linalg.svd(centered, full_matrices=False)
    scores = centered @ components[:2].T
    explained_variance_ratio = singular_values**2 / np.sum(singular_values**2)

    scenario_names = [f"p{index}" for index in range(1, len(medoids) + 1)]
    colors = plt.get_cmap("tab20")(np.linspace(0, 1, len(medoids)))
    figure, axis = plt.subplots(figsize=(12, 8))
    for cluster, color in enumerate(colors):
        members = labels == cluster
        axis.scatter(
            scores[members, 0],
            scores[members, 1],
            s=24,
            color=color,
            alpha=0.45,
            edgecolors="none",
        )

    medoid_scores = scores[medoids]
    extreme_mask = np.asarray(
        [int(medoid) in extreme_reasons for medoid in medoids], dtype=bool
    )
    typical_mask = ~extreme_mask
    axis.scatter(
        medoid_scores[typical_mask, 0],
        medoid_scores[typical_mask, 1],
        s=300,
        c=colors[typical_mask],
        marker="*",
        edgecolors="black",
        linewidths=1.4,
        zorder=5,
    )
    axis.scatter(
        medoid_scores[extreme_mask, 0],
        medoid_scores[extreme_mask, 1],
        s=380,
        c=colors[extreme_mask],
        marker="*",
        edgecolors="#b30000",
        linewidths=3,
        zorder=5,
    )
    for index, (name, medoid) in enumerate(zip(scenario_names, medoids)):
        is_extreme = int(medoid) in extreme_reasons
        place_left = is_extreme and int(extreme_mask[:index].sum()) % 2 == 1
        offset = (-7, 9) if place_left else (7, 7)
        axis.annotate(
            f"{name} (E)" if is_extreme else name,
            medoid_scores[index],
            xytext=offset,
            textcoords="offset points",
            horizontalalignment="right" if place_left else "left",
            fontsize=9,
            weight=500,
            color="#8b0000" if is_extreme else "black",
            bbox={
                "boxstyle": "round,pad=0.2",
                "fc": "#fff0f0" if is_extreme else "white",
                "ec": "#b30000" if is_extreme else "black",
                "alpha": 0.85,
            },
            zorder=6,
        )

    axis.set_title("PCA of joint gas-PV representative weeks")
    axis.set_xlabel(f"PC1 ({explained_variance_ratio[0] * 100:.1f}% variance)")
    axis.set_ylabel(f"PC2 ({explained_variance_ratio[1] * 100:.1f}% variance)")
    axis.grid(alpha=0.25)
    axis.text(
        0.01,
        0.01,
        "Stars = medoids; red stars marked (E) = extreme weeks.",
        transform=axis.transAxes,
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "alpha": 0.85},
    )
    figure.tight_layout()
    temporary = path.with_suffix(path.suffix + ".tmp")
    figure.savefig(temporary, format="pdf", dpi=200, bbox_inches="tight")
    plt.close(figure)
    temporary.replace(path)
    return explained_variance_ratio[:2]


def write_representative_profiles_plot(
    gas_frame: pd.DataFrame,
    pv_frame: pd.DataFrame,
    metadata: pd.DataFrame,
    path: Path,
) -> None:
    columns = 3
    rows = int(np.ceil(len(metadata) / columns))
    figure, axes = plt.subplots(rows, columns, figsize=(13, 14), sharex=True)
    axes = np.asarray(axes).reshape(-1)
    hours = gas_frame["hour_of_week"]
    gas_color = "#1f4e79"
    pv_color = "#d47f00"
    legend_lines = None

    for index, scenario in metadata.iterrows():
        axis = axes[index]
        pv_axis = axis.twinx()
        name = scenario["scenario"]
        gas_line = axis.plot(
            hours,
            gas_frame[name],
            color=gas_color,
            linewidth=1.4,
            label="Gas demand",
        )[0]
        pv_line = pv_axis.plot(
            hours,
            pv_frame[name],
            color=pv_color,
            linewidth=1.2,
            label="PV capacity factor",
        )[0]
        if legend_lines is None:
            legend_lines = (gas_line, pv_line)

        is_extreme = scenario["scenario_type"] == "extreme"
        title = (
            f"{name}{' (E)' if is_extreme else ''} - "
            f"{scenario['source_week_start']} to {scenario['source_week_end']}\n"
            f"probability = {100 * float(scenario['probability']):.2f}%"
        )
        if is_extreme:
            reason = str(scenario["extreme_reason"]).replace("_", " ")
            title += f" · {reason}"
        axis.set_title(title, fontsize=8, color="#8b0000" if is_extreme else "black")
        axis.set_xlim(0, HOURS_PER_WEEK - 1)
        axis.set_xticks(np.arange(0, HOURS_PER_WEEK, 24), DAY_NAMES)
        axis.set_ylim(bottom=0)
        pv_axis.set_ylim(-0.03, 1.03)
        axis.tick_params(axis="y", colors=gas_color, labelsize=8)
        pv_axis.tick_params(axis="y", colors=pv_color, labelsize=8)
        axis.tick_params(axis="x", labelsize=8)
        axis.grid(alpha=0.25)

    for axis in axes[len(metadata) :]:
        axis.set_visible(False)

    if legend_lines is None:
        raise ValueError("No representative scenarios available to plot")
    figure.suptitle("Joint representative gas-demand and PV weeks", y=0.995)
    figure.supxlabel("Day of week (UTC)", y=0.015)
    figure.text(
        0.006,
        0.5,
        "Gas demand (MW, LHV)",
        color=gas_color,
        fontweight=500,
        rotation="vertical",
        va="center",
    )
    figure.text(
        0.994,
        0.5,
        "PV capacity factor",
        color=pv_color,
        fontweight=500,
        rotation=-90,
        va="center",
        ha="right",
    )
    figure.legend(
        legend_lines,
        [line.get_label() for line in legend_lines],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.978),
        ncol=2,
        frameon=True,
        prop={"weight": 500, "size": 9},
    )
    figure.tight_layout(rect=(0.025, 0.025, 0.975, 0.95))
    temporary = path.with_suffix(path.suffix + ".tmp")
    figure.savefig(temporary, format="pdf", dpi=200, bbox_inches="tight")
    plt.close(figure)
    temporary.replace(path)


def main() -> None:
    outputs = {
        "gas": OUTPUT_DIR / "gas_representative_weeks.csv",
        "pv": OUTPUT_DIR / "pv_representative_weeks.csv",
        "metadata": OUTPUT_DIR / "scenario_metadata.csv",
        "pca_plot": OUTPUT_DIR / "representative_weeks_pca.pdf",
        "profiles_plot": OUTPUT_DIR / "representative_weeks_profiles.pdf",
    }

    gas_lhv = load_gas_lhv(PARAMETERS_FILE)
    hourly, quality = load_aligned_hourly_data(
        GAS_FILE,
        PV_FILE,
        OUTLIER_IQR_MULTIPLIER,
    )
    week_starts, gas, pv = weekly_matrices(hourly)
    distances = joint_distance(gas, pv)
    extremes = extreme_weeks(gas, pv)
    medoids, labels, objective = fit_kmedoids(
        distances,
        CLUSTERS,
        list(extremes),
        RESTARTS,
        MAX_ITERATIONS,
        SEED,
    )
    medoids, labels = order_scenarios(week_starts, medoids, distances)
    gas_frame, pv_frame, metadata = scenario_frames(
        week_starts,
        gas,
        pv,
        medoids,
        labels,
        distances,
        extremes,
        gas_lhv,
    )
    metadata["gas_lhv_kwh_sm3"] = gas_lhv
    metadata["valid_input_weeks"] = len(week_starts)
    metadata["excluded_input_weeks"] = quality["excluded_week_count"]
    metadata["partial_input_weeks"] = quality["partial_week_count"]
    metadata["gas_upper_fence_sm3_h"] = quality["gas_upper_fence_sm3_h"]
    metadata["cluster_seed"] = SEED
    metadata["cluster_restarts"] = RESTARTS

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    configure_plot_style()
    pca_variance = write_pca_plot(
        gas,
        pv,
        medoids,
        labels,
        extremes,
        outputs["pca_plot"],
    )
    metadata["pca_pc1_explained_variance"] = pca_variance[0]
    metadata["pca_pc2_explained_variance"] = pca_variance[1]
    write_representative_profiles_plot(
        gas_frame,
        pv_frame,
        metadata,
        outputs["profiles_plot"],
    )
    write_csv(gas_frame, outputs["gas"])
    write_csv(pv_frame, outputs["pv"])
    write_csv(metadata, outputs["metadata"])

    print(f"Aligned hourly observations: {quality['aligned_hour_count']}")
    print(f"Candidate calendar weeks: {quality['candidate_week_count']}")
    print(f"Complete valid weeks: {len(week_starts)}")
    print(
        "Excluded input weeks: "
        f"{quality['excluded_week_count']} "
        f"(partial weeks: {quality['partial_week_count']}, "
        f"weeks with invalid data: {quality['data_invalid_week_count']})"
    )
    print(
        "Invalid input hours: "
        f"missing={quality['missing_hour_count']}, "
        f"negative gas={quality['negative_gas_hour_count']}, "
        f"gas outliers={quality['gas_outlier_hour_count']}, "
        f"invalid PV={quality['invalid_pv_hour_count']}"
    )
    print(
        "Gas outlier upper fence (Sm3/h): "
        f"{quality['gas_upper_fence_sm3_h']:.3f}"
    )
    print(f"Representative scenarios: {len(metadata)}")
    print(f"Fixed distinct extreme weeks: {len(extremes)}")
    print(f"Total k-medoids distance: {objective:.6f}")
    print(f"Scenario probabilities sum: {metadata['probability'].sum():.12f}")
    for path in outputs.values():
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()

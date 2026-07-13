"""Create joint representative gas-demand and PV days with k-medoids.

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
from matplotlib import font_manager


GAS_FILE = Path("data/gas/ppnet_metar.csv")
PV_FILE = Path(
    "data/pv/processed/pv_capacity_factor_ppnet_2013_2019.csv"
)
PARAMETERS_FILE = Path("data/info/parameters.json")
FONT_FILE = Path("data/Gulliver.otf")
OUTPUT_DIR = Path("data/scenarios")

CLUSTERS = 11
RESTARTS = 8
MAX_ITERATIONS = 100
SEED = 42
OUTLIER_IQR_MULTIPLIER = 3.0


def configure_plot_style() -> None:
    if not FONT_FILE.exists():
        raise FileNotFoundError(f"Plot font not found: {FONT_FILE}")
    font_manager.fontManager.addfont(str(FONT_FILE))
    font_properties = font_manager.FontProperties(fname=str(FONT_FILE))
    plt.rcParams.update(
        {
            "font.family": font_properties.get_name(),
            "font.weight": 500,
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.labelweight": 500,
            "axes.titlesize": 10,
            "axes.titleweight": 500,
            "figure.labelweight": 500,
            "figure.titleweight": 500,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 9,
            "axes.unicode_minus": False,
        }
    )


def load_gas_lhv(path: Path) -> float:
    with path.open(encoding="utf-8") as file:
        parameters = json.load(file)
    lhv = float(parameters["gas"]["lhv"])
    if lhv <= 0:
        raise ValueError("Gas LHV must be greater than zero")
    return lhv


def load_aligned_hourly_data(
    gas_path: Path, pv_path: Path, outlier_iqr_multiplier: float
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
        pv_frame, on="timestamp", how="inner", validate="one_to_one"
    ).sort_values("timestamp", ignore_index=True)
    if len(hourly) != len(gas_frame) or len(hourly) != len(pv_frame):
        raise ValueError("Gas and PV timestamps are not aligned exactly")
    hourly["date"] = hourly["timestamp"].dt.floor("D")
    hourly["hour"] = hourly["timestamp"].dt.hour
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
    invalid_pv = ~hourly["pv_capacity_factor"].between(0, 1)
    invalid_values = (
        missing_values
        | negative_gas
        | gas_outliers
        | invalid_pv
    )
    excluded_dates = hourly.loc[invalid_values, "date"].unique()
    hourly = hourly.loc[~hourly["date"].isin(excluded_dates)].copy()

    if (hourly["gas_consumption_sm3_h"] < 0).any():
        raise ValueError("Gas consumption contains negative values")
    if not hourly["pv_capacity_factor"].between(0, 1).all():
        raise ValueError("PV capacity factor must be between zero and one")

    counts = hourly.groupby("date", sort=True).size()
    if not counts.eq(24).all():
        invalid = counts[counts.ne(24)].index.strftime("%Y-%m-%d").tolist()
        raise ValueError(f"Incomplete days found: {', '.join(invalid[:5])}")
    quality = {
        "missing_hour_count": int(missing_values.sum()),
        "negative_gas_hour_count": int(negative_gas.sum()),
        "gas_outlier_hour_count": int(gas_outliers.sum()),
        "invalid_pv_hour_count": int(invalid_pv.sum()),
        "excluded_day_count": len(excluded_dates),
        "gas_upper_fence_sm3_h": float(gas_upper_fence),
    }
    return hourly, quality


def daily_matrices(hourly: pd.DataFrame) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    gas = hourly.pivot(
        index="date", columns="hour", values="gas_consumption_sm3_h"
    ).reindex(columns=range(24))
    pv = hourly.pivot(
        index="date", columns="hour", values="pv_capacity_factor"
    ).reindex(columns=range(24))
    if gas.isna().any().any() or pv.isna().any().any():
        raise ValueError("Daily profiles must contain every hour from 0 through 23")
    if not gas.index.equals(pv.index):
        raise ValueError("Daily gas and PV indexes do not match")
    return gas.index, gas.to_numpy(dtype=float), pv.to_numpy(dtype=float)


def standardize(values: np.ndarray) -> np.ndarray:
    mean = float(values.mean())
    deviation = float(values.std())
    if deviation == 0:
        raise ValueError("Cannot cluster a constant input series")
    return ((values - mean) / deviation).astype(np.float32)


def pairwise_mean_squared_distance(values: np.ndarray) -> np.ndarray:
    norms = np.sum(values * values, axis=1, dtype=np.float32)
    distances = norms[:, None] + norms[None, :] - 2 * (values @ values.T)
    distances /= values.shape[1]
    np.maximum(distances, 0, out=distances)
    return distances


def joint_distance(gas: np.ndarray, pv: np.ndarray) -> np.ndarray:
    combined = 0.5 * pairwise_mean_squared_distance(standardize(gas))
    combined += 0.5 * pairwise_mean_squared_distance(standardize(pv))
    np.sqrt(combined, out=combined)
    return combined


def extreme_days(gas: np.ndarray, pv: np.ndarray) -> dict[int, list[str]]:
    gas_total = gas.sum(axis=1)
    gas_peak = gas.max(axis=1)
    pv_total = pv.sum(axis=1)
    gas_daily_z = (gas_total - gas_total.mean()) / gas_total.std()
    pv_daily_z = (pv_total - pv_total.mean()) / pv_total.std()

    reasons: dict[int, list[str]] = defaultdict(list)
    candidates = (
        (int(np.argmax(gas_total)), "maximum_daily_gas"),
        (int(np.argmax(gas_peak)), "maximum_hourly_gas"),
        (int(np.argmax(gas_daily_z - pv_daily_z)), "high_gas_low_pv"),
        (int(np.argmin(gas_daily_z + pv_daily_z)), "low_gas_low_pv"),
        (int(np.argmax(pv_total)), "maximum_daily_pv"),
    )
    for index, reason in candidates:
        reasons[index].append(reason)
    return dict(reasons)


def initialize_medoids(
    distances: np.ndarray,
    clusters: int,
    fixed_medoids: list[int],
    rng: np.random.Generator,
) -> np.ndarray:
    medoids = list(fixed_medoids)
    while len(medoids) < clusters:
        nearest = distances[:, medoids].min(axis=1)
        nearest[medoids] = 0
        weights = nearest.astype(np.float64) ** 2
        if weights.sum() == 0:
            available = np.setdiff1d(np.arange(len(distances)), medoids)
            selected = int(rng.choice(available))
        else:
            selected = int(rng.choice(len(distances), p=weights / weights.sum()))
        if selected not in medoids:
            medoids.append(selected)
    return np.asarray(medoids, dtype=int)


def update_medoids(
    distances: np.ndarray,
    medoids: np.ndarray,
    labels: np.ndarray,
    fixed_medoids: set[int],
) -> np.ndarray:
    updated = medoids.copy()
    for cluster, current in enumerate(medoids):
        if int(current) in fixed_medoids:
            continue
        members = np.flatnonzero(labels == cluster)
        within_cluster_cost = distances[np.ix_(members, members)].sum(axis=1)
        updated[cluster] = members[int(np.argmin(within_cluster_cost))]
    return updated


def fit_kmedoids(
    distances: np.ndarray,
    clusters: int,
    fixed_medoids: list[int],
    restarts: int,
    max_iterations: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    observations = len(distances)
    if not 1 <= clusters <= observations:
        raise ValueError("clusters must be between 1 and the number of days")
    if len(fixed_medoids) > clusters:
        raise ValueError("clusters is smaller than the number of fixed extreme days")
    if restarts < 1 or max_iterations < 1:
        raise ValueError("restarts and max-iterations must be positive")

    fixed_set = set(fixed_medoids)
    rng = np.random.default_rng(seed)
    best: tuple[np.ndarray, np.ndarray, float] | None = None
    for _ in range(restarts):
        medoids = initialize_medoids(distances, clusters, fixed_medoids, rng)
        for _ in range(max_iterations):
            labels = np.argmin(distances[:, medoids], axis=1)
            updated = update_medoids(distances, medoids, labels, fixed_set)
            if np.array_equal(updated, medoids):
                break
            medoids = updated

        labels = np.argmin(distances[:, medoids], axis=1)
        objective = float(distances[np.arange(observations), medoids[labels]].sum())
        if best is None or objective < best[2]:
            best = medoids.copy(), labels.copy(), objective

    if best is None:
        raise RuntimeError("k-medoids did not produce a solution")
    return best


def order_scenarios(
    dates: pd.DatetimeIndex,
    medoids: np.ndarray,
    distances: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    medoids = medoids[np.argsort(dates[medoids])]
    labels = np.argmin(distances[:, medoids], axis=1)
    return medoids, labels


def scenario_frames(
    dates: pd.DatetimeIndex,
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
    gas_frame = pd.DataFrame({"hour": range(24)})
    pv_frame = pd.DataFrame({"hour": range(24)})
    metadata_rows = []

    for cluster, (name, medoid) in enumerate(zip(scenario_names, medoids)):
        members = np.flatnonzero(labels == cluster)
        assignment_distances = distances[members, medoid]
        gas_frame[name] = gas_mw[cluster]
        pv_frame[name] = pv[medoid]
        reasons = extreme_reasons.get(int(medoid), [])
        metadata_rows.append(
            {
                "scenario": name,
                "source_date": dates[medoid].strftime("%Y-%m-%d"),
                "scenario_type": "extreme" if reasons else "typical",
                "extreme_reason": ";".join(reasons),
                "weight_days": len(members),
                "probability": len(members) / len(dates),
                "daily_gas_energy_mwh": gas_mw[cluster].sum(),
                "peak_gas_demand_mw": gas_mw[cluster].max(),
                "daily_pv_energy_kwh_per_kwp": pv[medoid].sum(),
                "mean_assignment_distance": assignment_distances.mean(),
                "max_assignment_distance": assignment_distances.max(),
            }
        )

    metadata = pd.DataFrame(metadata_rows)
    if int(metadata["weight_days"].sum()) != len(dates):
        raise RuntimeError("Scenario weights do not cover every input day")
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
    colors = plt.get_cmap("tab10")(np.linspace(0, 1, len(medoids)))
    figure, axis = plt.subplots(figsize=(12, 8))
    for cluster, (name, color) in enumerate(zip(scenario_names, colors)):
        members = labels == cluster
        axis.scatter(
            scores[members, 0],
            scores[members, 1],
            s=18,
            color=color,
            alpha=0.35,
            edgecolors="none",
            label=name,
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
    bottom_threshold = np.percentile(scores[:, 1], 1)
    bottom_extremes = np.flatnonzero(
        extreme_mask & (medoid_scores[:, 1] <= bottom_threshold)
    )
    for index, (name, medoid) in enumerate(zip(scenario_names, medoids)):
        is_extreme = int(medoid) in extreme_reasons
        extreme_position = int(extreme_mask[:index].sum())
        place_left = is_extreme and extreme_position % 2 == 1
        if index in bottom_extremes:
            bottom_position = int(np.flatnonzero(bottom_extremes == index)[0])
            place_left = bottom_position % 2 == 0
            offset = (-7, 12) if place_left else (7, 30)
        else:
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

    axis.set_title("PCA of joint gas-PV representative days")
    axis.set_xlabel(f"PC1 ({explained_variance_ratio[0] * 100:.1f}% variance)")
    axis.set_ylabel(f"PC2 ({explained_variance_ratio[1] * 100:.1f}% variance)")
    axis.grid(alpha=0.25)
    axis.legend(
        title="Cluster",
        ncol=2,
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        frameon=True,
    )
    axis.text(
        0.01,
        0.01,
        "Stars = medoids; red stars marked (E) = extreme days.",
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
    figure, axes = plt.subplots(rows, columns, figsize=(12, 13.5), sharex=True)
    axes = np.asarray(axes).reshape(-1)
    hours = gas_frame["hour"]
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
            linewidth=1.8,
            label="Gas demand",
        )[0]
        pv_line = pv_axis.plot(
            hours,
            pv_frame[name],
            color=pv_color,
            linewidth=1.8,
            label="PV capacity factor",
        )[0]
        if legend_lines is None:
            legend_lines = (gas_line, pv_line)

        is_extreme = scenario["scenario_type"] == "extreme"
        title = (
            f"{name}{' (E)' if is_extreme else ''} - "
            f"{scenario['source_date']}\n"
            f"probability = {100 * float(scenario['probability']):.2f}%"
        )
        if is_extreme:
            reason = str(scenario["extreme_reason"]).replace("_", " ")
            title += f" · {reason}"
        axis.set_title(title, fontsize=9, color="#8b0000" if is_extreme else "black")
        axis.set_xlim(0, 23)
        axis.set_xticks([0, 6, 12, 18, 23])
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
    figure.suptitle("Joint representative gas-demand and PV days", y=0.995)
    figure.supxlabel("Hour (UTC)", y=0.015)
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


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, float_format="%.15g")
    temporary.replace(path)


def main() -> None:
    output_dir = OUTPUT_DIR
    outputs = {
        "gas": output_dir / "gas_representative_days.csv",
        "pv": output_dir / "pv_representative_days.csv",
        "metadata": output_dir / "scenario_metadata.csv",
        "pca_plot": output_dir / "representative_scenarios_pca.pdf",
        "profiles_plot": output_dir / "representative_days_profiles.pdf",
    }

    gas_lhv = load_gas_lhv(PARAMETERS_FILE)
    hourly, quality = load_aligned_hourly_data(
        GAS_FILE,
        PV_FILE,
        OUTLIER_IQR_MULTIPLIER,
    )
    dates, gas, pv = daily_matrices(hourly)
    distances = joint_distance(gas, pv)
    extremes = extreme_days(gas, pv)
    medoids, labels, objective = fit_kmedoids(
        distances,
        CLUSTERS,
        list(extremes),
        RESTARTS,
        MAX_ITERATIONS,
        SEED,
    )
    medoids, labels = order_scenarios(dates, medoids, distances)
    gas_frame, pv_frame, metadata = scenario_frames(
        dates, gas, pv, medoids, labels, distances, extremes, gas_lhv
    )
    metadata["gas_lhv_kwh_sm3"] = gas_lhv
    metadata["valid_input_days"] = len(dates)
    metadata["excluded_input_days"] = quality["excluded_day_count"]
    metadata["gas_upper_fence_sm3_h"] = quality["gas_upper_fence_sm3_h"]
    metadata["cluster_seed"] = SEED
    metadata["cluster_restarts"] = RESTARTS

    output_dir.mkdir(parents=True, exist_ok=True)
    configure_plot_style()
    pca_variance = write_pca_plot(
        gas, pv, medoids, labels, extremes, outputs["pca_plot"]
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

    print(f"Aligned hourly observations: {len(hourly)}")
    print(f"Complete daily profiles: {len(dates)}")
    print(
        "Excluded input days: "
        f"{quality['excluded_day_count']} "
        f"(missing hours: {quality['missing_hour_count']}, "
        f"negative gas hours: {quality['negative_gas_hour_count']}, "
        f"gas outlier hours: {quality['gas_outlier_hour_count']})"
    )
    print(
        "Gas outlier upper fence (Sm3/h): "
        f"{quality['gas_upper_fence_sm3_h']:.3f}"
    )
    print(f"Representative scenarios: {len(metadata)}")
    print(f"Fixed extreme days: {len(extremes)}")
    print(f"Total k-medoids distance: {objective:.6f}")
    print(f"Scenario probabilities sum: {metadata['probability'].sum():.12f}")
    for path in outputs.values():
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()

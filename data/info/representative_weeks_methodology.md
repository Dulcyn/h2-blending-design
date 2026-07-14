# Mathematical formulation of the representative weeks

## Purpose

The weekly pipeline complements the existing representative-day pipeline. It
does not modify or replace any daily scenario. Its implementation is in
`scripts/create_representative_weeks.py`, and its outputs are isolated under
`data/scenarios/weekly/`.

Each scenario is a medoid: one complete historical week whose gas-demand and PV
profiles retain their original temporal relationship. Synthetic combinations
of gas from one week and PV from another week are not created.

## Candidate weeks

Let $w\in\mathcal{W}$ denote a valid week and
$h\in\mathcal{H}=\{0,\ldots,167\}$ its hour, where hour 0 is Monday 00:00 UTC
and hour 167 is Sunday 23:00 UTC. The profiles are

$$
\mathbf{g}_w=(g_{w,0},\ldots,g_{w,167}),\qquad
\mathbf{p}_w=(p_{w,0},\ldots,p_{w,167}),
$$

where $g$ is gas consumption in $\mathrm{Sm^3/h}$ and $p$ is the dimensionless
PV capacity factor.

Gas and PV timestamps must be valid, unique, and aligned one-to-one. A whole
week is excluded if it is incomplete or if any hour contains:

- missing gas or PV data;
- negative gas consumption;
- a PV capacity factor outside $[0,1]$;
- gas consumption above the upper Tukey fence
  $Q_{0.75}+3(Q_{0.75}-Q_{0.25})$.

No hourly interpolation is performed. This preserves the observed multiday
sequence inside every retained week.

## Joint weekly distance

Gas and PV are standardized separately over all valid weeks and hours. For gas,

$$
\widetilde{g}_{w,h}=\frac{g_{w,h}-\mu_g}{\sigma_g},
$$

with an analogous expression for $\widetilde{p}_{w,h}$. One global mean and
population standard deviation are used for each attribute.

The distance between weeks $i$ and $j$ is

$$
D_{i,j}=\sqrt{
\frac{1}{2}\left[\frac{1}{168}\sum_h
(\widetilde{g}_{i,h}-\widetilde{g}_{j,h})^2\right]
+\frac{1}{2}\left[\frac{1}{168}\sum_h
(\widetilde{p}_{i,h}-\widetilde{p}_{j,h})^2\right]
}.
$$

Gas and PV therefore have equal weight. Clustering uses all 336 hourly
attributes; PCA is used only for a two-dimensional visualization.

## Extreme weeks

Define weekly gas energy proxy $G_w=\sum_h g_{w,h}$, hourly gas peak
$M_w=\max_h g_{w,h}$, and weekly PV yield $P_w=\sum_h p_{w,h}$. Also define
standardized weekly totals $z^G_w$ and $z^P_w$.

Six criteria select fixed candidate medoids:

$$
\arg\max_w G_w,\quad
\arg\max_w M_w,\quad
\arg\max_w(z^G_w-z^P_w),
$$

$$
\arg\min_w(z^G_w+z^P_w),\quad
\arg\min_w P_w,\quad
\arg\max_w P_w.
$$

They represent maximum weekly gas, maximum hourly gas, high gas with low PV,
low gas with low PV, minimum weekly PV, and maximum weekly PV. When multiple
criteria select the same week, that week remains one medoid and records every
reason.

The explicit minimum-PV week is included because multiday renewable shortages
are important for sizing the electrolyzer, grid connection, BESS, and hydrogen
storage.

## Constrained k-medoids

With $y_j=1$ when week $j$ is a medoid and $z_{i,j}=1$ when week $i$ is assigned
to it, the underlying discrete model is

$$
\min\sum_i\sum_j D_{i,j}z_{i,j}
$$

subject to

$$
\sum_jz_{i,j}=1,\qquad z_{i,j}\leq y_j,\qquad
\sum_jy_j=K,
$$

$$
y_e=1\quad\forall e\in\mathcal{E},\qquad y_j,z_{i,j}\in\{0,1\}.
$$

The implementation uses the same reproducible alternating k-medoids heuristic
as the daily pipeline: fixed extremes, distance-weighted initialization,
nearest-medoid assignment, within-cluster medoid updates, eight restarts, and
seed 42. It is not guaranteed to find the global optimum of the binary model.

## Weights and probabilities

For cluster $C_k$, the scenario weight and empirical probability are

$$
W_k=|C_k|,\qquad \pi_k=\frac{W_k}{|\mathcal{W}|}.
$$

The implementation verifies that all valid weeks are assigned exactly once and
that $\sum_k\pi_k=1$. These probabilities preserve weekly cluster frequency;
they do not restore the original chronological order between weeks.

## Current reproducible result

| Parameter | Value |
|---|---:|
| Candidate calendar weeks | 339 |
| Complete valid weeks | 271 |
| Excluded weeks | 68 |
| Representative weeks, $K$ | 11 |
| Distinct fixed extreme weeks | 5 |
| Typical medoids | 6 |
| Random restarts | 8 |
| Random seed | 42 |
| Gas/PV distance weights | 0.5 / 0.5 |
| PC1 explained variance | 78.98% |
| PC2 explained variance | 6.10% |

The maximum weekly gas and maximum hourly gas criteria select the same week,
starting on 2018-02-26, which explains why six criteria produce five distinct
fixed extreme medoids. The retained sample still contains weeks starting in
every month and every input year from 2013 through 2019. Excluding complete
weeks is more conservative than the daily filter and removes about 20% of the
339 calendar-week candidates; this should be considered when testing scenario
sensitivity.

## Generated files

- `data/scenarios/weekly/gas_representative_weeks.csv`;
- `data/scenarios/weekly/pv_representative_weeks.csv`;
- `data/scenarios/weekly/scenario_metadata.csv`;
- `data/scenarios/weekly/representative_weeks_pca.pdf`;
- `data/scenarios/weekly/representative_weeks_profiles.pdf`.

The CSV profiles contain 168 ordered rows per scenario. Gas is expressed as MW
on an LHV basis, and PV remains a capacity factor. The metadata contains source
dates, probabilities, extreme reasons, energy summaries, and validation data.

Run from the repository root with:

```powershell
.\.venv\Scripts\python.exe scripts\create_representative_weeks.py
```

## Limitations

- Chronology is preserved inside each week but not between representative
  weeks.
- A cyclic storage condition imposed independently on each week cannot model
  seasonal storage.
- Scenario probabilities should weight operating costs, while shared design
  capacities and feasibility constraints must apply to every scenario.
- The choice of 11 scenarios and equal gas/PV weights should be tested through
  sensitivity analysis against the resulting optimal capacities.

## References

1. Kaufman, L., and Rousseeuw, P. J. (1990). “Partitioning Around Medoids
   (Program PAM).” [doi:10.1002/9780470316801.ch2](https://doi.org/10.1002/9780470316801.ch2).
2. Kotzur, L., Markewitz, P., Robinius, M., and Stolten, D. (2018). “Impact of
   different time series aggregation methods on optimal energy system design.”
   [doi:10.1016/j.renene.2017.10.017](https://doi.org/10.1016/j.renene.2017.10.017).
3. Teichgraeber, H., and Brandt, A. R. (2019). “Clustering methods to find
   representative periods for the optimization of energy systems.”
   [doi:10.1016/j.apenergy.2019.02.012](https://doi.org/10.1016/j.apenergy.2019.02.012).
4. Kotzur, L., Markewitz, P., Robinius, M., and Stolten, D. (2018). “Time series
   aggregation for energy system design: Modeling seasonal storage.”
   [doi:10.1016/j.apenergy.2018.01.023](https://doi.org/10.1016/j.apenergy.2018.01.023).

# Mathematical formulation of the representative scenarios

## 1. Purpose

The representative-scenario dataset reduces the aligned hourly gas-demand and
PV time series to a small set of joint 24-hour scenarios. The implementation is
in `scripts/create_representative_scenarios.py`.

Each representative scenario is a **medoid**, meaning an actual historical day.
Gas demand and PV generation therefore always come from the same date; the
method does not create synthetic combinations of gas and PV profiles.

## 2. Input data and notation

The method uses:

- hourly natural-gas consumption from `data/gas/ppnet_metar.csv`;
- hourly PV capacity factors from
  `data/pv/processed/pv_capacity_factor_ppnet_2013_2019.csv`;
- the natural-gas lower heating value (LHV) from
  `data/info/parameters.json`.

Both time series cover the Prague region and are aligned in UTC. The PV series
is generated for Prague Airport (LKPR), at latitude 50.100833 and longitude
14.260000, using Open-Meteo ERA5 weather data and pvlib.

Let:

- $d \in \mathcal{D}$ denote a valid historical day;
- $h \in \mathcal{H}=\{0,\ldots,23\}$ denote an hour;
- $N=|\mathcal{D}|$ denote the number of valid days;
- $g_{d,h}$ denote gas consumption in $\mathrm{Sm^3/h}$;
- $p_{d,h}$ denote the dimensionless PV capacity factor;
- $K$ denote the requested number of representative scenarios.

The daily profiles are

$$
\mathbf{g}_d=(g_{d,0},\ldots,g_{d,23}), \qquad
\mathbf{p}_d=(p_{d,0},\ldots,p_{d,23}).
$$

## 3. Alignment and data-quality filtering

Gas and PV timestamps must be valid, unique, and exactly aligned one-to-one.
The observations are sorted chronologically and divided into UTC days.

Gas outliers are identified with an upper Tukey fence. Using all non-missing,
non-negative hourly gas observations,

$$
IQR=Q_{0.75}-Q_{0.25}, \qquad
U_g=Q_{0.75}+3IQR.
$$

A complete day is excluded if any hour has:

- a missing gas or PV value;
- negative gas consumption;
- gas consumption greater than $U_g$;
- a PV capacity factor outside $[0,1]$.

Every retained day must contain exactly the 24 hours from 00:00 to 23:00. The
entire day is removed instead of interpolating individual invalid hours, which
preserves the observed relationship between its gas and PV profiles.

## 4. Standardization and joint distance

Gas demand and PV have different units and magnitudes. They are standardized
separately over all retained days and hours using population statistics:

$$
\mu_g=\frac{1}{24N}\sum_{d\in\mathcal{D}}\sum_{h\in\mathcal{H}}g_{d,h},
\qquad
\sigma_g=\sqrt{\frac{1}{24N}\sum_{d,h}(g_{d,h}-\mu_g)^2},
$$

$$
\widetilde{g}_{d,h}=\frac{g_{d,h}-\mu_g}{\sigma_g}.
$$

The same calculation gives $\widetilde{p}_{d,h}$ using $\mu_p$ and $\sigma_p$.
This is full-series standardization: one mean and one standard deviation are
used for gas, and another pair is used for PV.

For two days $i$ and $j$, the joint distance is

$$
D_{i,j}=
\sqrt{
\frac{1}{2}\left(\frac{1}{24}\sum_{h\in\mathcal{H}}
(\widetilde{g}_{i,h}-\widetilde{g}_{j,h})^2\right)
+
\frac{1}{2}\left(\frac{1}{24}\sum_{h\in\mathcal{H}}
(\widetilde{p}_{i,h}-\widetilde{p}_{j,h})^2\right)
}.
$$

Thus, gas and PV have equal weight in the clustering distance. The hourly shape
and magnitude of both profiles are evaluated jointly.

## 5. Extreme-day selection

Pure clustering may omit rare but important operating conditions. Five
criteria therefore select historical candidate days that are fixed as medoids
before the remaining medoids are selected.

Define

$$
G_d=\sum_h g_{d,h}, \qquad
M_d=\max_h g_{d,h}, \qquad
P_d=\sum_h p_{d,h},
$$

and the standardized daily totals, also using population standard deviations,

$$
z^G_d=\frac{G_d-\overline{G}}{s_G}, \qquad
z^P_d=\frac{P_d-\overline{P}}{s_P}.
$$

The extreme-day criteria are:

$$
e_1=\arg\max_d G_d
\quad\text{(maximum daily gas)},
$$

$$
e_2=\arg\max_d M_d
\quad\text{(maximum hourly gas)},
$$

$$
e_3=\arg\max_d (z^G_d-z^P_d)
\quad\text{(high gas and low PV)},
$$

$$
e_4=\arg\min_d (z^G_d+z^P_d)
\quad\text{(low gas and low PV)},
$$

$$
e_5=\arg\max_d P_d
\quad\text{(maximum daily PV)}.
$$

If more than one criterion selects the same date, that date remains a single
fixed medoid and stores all applicable reasons.

## 6. Constrained k-medoids model

The underlying discrete optimization problem can be written as a $K$-medoids,
or discrete $p$-median, formulation. Let:

- $y_j=1$ if historical day $j$ is selected as a medoid;
- $z_{i,j}=1$ if day $i$ is assigned to medoid $j$;
- $\mathcal{E}$ be the set of fixed extreme days.

The exact formulation is

$$
\min_{y,z}\quad
\sum_{i\in\mathcal{D}}\sum_{j\in\mathcal{D}}D_{i,j}z_{i,j}
$$

subject to

$$
\sum_{j\in\mathcal{D}}z_{i,j}=1
\qquad \forall i\in\mathcal{D},
$$

$$
z_{i,j}\le y_j
\qquad \forall i,j\in\mathcal{D},
$$

$$
\sum_{j\in\mathcal{D}}y_j=K,
$$

$$
y_e=1
\qquad \forall e\in\mathcal{E},
$$

$$
y_j,z_{i,j}\in\{0,1\}.
$$

The current script does not solve this binary model globally. It uses a
reproducible alternating k-medoids heuristic:

1. Fix all extreme days as initial medoids.
2. Add the remaining medoids with initialization probabilities proportional to
   the squared distance from the nearest medoid already selected.
3. Assign each day to its nearest medoid.
4. For every non-fixed cluster, choose the cluster member that minimizes the
   sum of distances to the other members.
5. Repeat assignment and update until the medoids stop changing or the
   iteration limit is reached.
6. Run several restarts and retain the solution with the smallest total
   assignment distance.

Because this is a heuristic, the result is locally optimal for the update rule
but is not guaranteed to be the global optimum of the binary formulation.

## 7. Scenario weights and probabilities

Let $C_k$ be the set of historical days assigned to representative medoid $k$.
Its weight and empirical probability are

$$
w_k=|C_k|, \qquad
\pi_k=\frac{w_k}{N}.
$$

The implementation validates

$$
\sum_{k=1}^{K}w_k=N, \qquad
\sum_{k=1}^{K}\pi_k=1.
$$

The probabilities describe the frequency of each cluster in the cleaned input
sample. They do not represent a fitted probability distribution or independent
gas/PV combinations.

## 8. Output-unit conversion

The selected gas profiles are converted from volumetric flow to thermal power
using the LHV parameter:

$$
P^{gas}_{k,h}\,[\mathrm{MW}]
=\frac{g_{k,h}\,[\mathrm{Sm^3/h}]\;LHV\,[\mathrm{kWh/Sm^3}]}{1000}.
$$

For one-hour intervals,

$$
E^{gas}_k\,[\mathrm{MWh}]=\sum_h P^{gas}_{k,h}.
$$

The PV output remains a capacity factor. Since the reference PV capacity is
$1\ \mathrm{kWp}$ and the interval is one hour,

$$
E^{PV}_k\,[\mathrm{kWh/kWp}]=\sum_h p_{k,h}.
$$

## 9. PCA visualization

Principal component analysis is used only to visualize the result. It does not
change the clustering or the selected medoids.

For every day, the 48-dimensional feature vector is

$$
\mathbf{x}_d=(\widetilde{g}_{d,0},\ldots,\widetilde{g}_{d,23},
\widetilde{p}_{d,0},\ldots,\widetilde{p}_{d,23}).
$$

After centering each feature, the matrix $\mathbf{X}_c$ is decomposed by SVD:

$$
\mathbf{X}_c=\mathbf{U}\mathbf{\Sigma}\mathbf{V}^{\mathsf{T}}.
$$

The plotted coordinates are the first two columns of
$\mathbf{U}\mathbf{\Sigma}$, and the variance explained by component $r$ is

$$
\eta_r=\frac{\sigma_r^2}{\sum_q\sigma_q^2}.
$$

Points are colored by cluster. Stars mark medoids, while red stars labeled
`(E)` mark fixed extreme days.

## 10. Reproducible configuration and current result

The script currently uses:

| Parameter | Value |
|---|---:|
| Number of scenarios, $K$ | 11 |
| Fixed extreme criteria | 5 |
| Random restarts | 8 |
| Maximum iterations per restart | 100 |
| Random seed | 42 |
| Gas outlier multiplier | $3IQR$ |
| Gas/PV distance weights | 0.5 / 0.5 |
| Gas LHV | 8.9608 kWh/Sm3 |

For the current aligned dataset, 2,248 complete days are retained and 124 days
are excluded. The resulting set contains six typical medoids and five extreme
medoids. PC1 and PC2 explain approximately 81.53% and 14.15% of the variance,
respectively.

The generated files are:

- `data/scenarios/gas_representative_days.csv`;
- `data/scenarios/pv_representative_days.csv`;
- `data/scenarios/scenario_metadata.csv`;
- `data/scenarios/representative_scenarios_pca.pdf` (Gulliver font);
- `data/scenarios/representative_days_profiles.pdf` (Gulliver font).

Run the method from the repository root with:

```powershell
python scripts/create_representative_scenarios.py
```

## 11. Modeling limitations

- Representative days reduce computation but discard the chronological order
  and transitions between historical days.
- Scenario probabilities preserve cluster frequency, not the original sequence.
- Independent representative days cannot directly reproduce interday or
  seasonal storage dynamics. A future stochastic model must explicitly define
  how storage states are linked across scenarios or representative periods.
- Fixed extreme days improve coverage of rare conditions, but they do not prove
  feasibility for every omitted historical day.
- The number of scenarios and the equal gas/PV weights are modeling choices and
  should be tested through sensitivity analysis against optimization results.

## 12. References and data sources

### Representative-period methodology

1. Kaufman, L., and Rousseeuw, P. J. (1990). “Partitioning Around
   Medoids (Program PAM).” In *Finding Groups in Data*, 68–125.
   [doi:10.1002/9780470316801.ch2](https://doi.org/10.1002/9780470316801.ch2).
2. Kotzur, L., Markewitz, P., Robinius, M., and Stolten, D. (2018).
   “Impact of different time series aggregation methods on optimal energy
   system design.” *Renewable Energy*, 117, 1285–1293.
   [doi:10.1016/j.renene.2017.10.017](https://doi.org/10.1016/j.renene.2017.10.017).
3. Teichgraeber, H., and Brandt, A. R. (2019). “Clustering methods to find
   representative periods for the optimization of energy systems: An initial
   framework and comparison.” *Applied Energy*, 239, 1283–1293.
   [doi:10.1016/j.apenergy.2019.02.012](https://doi.org/10.1016/j.apenergy.2019.02.012).
4. Teichgraeber, H., Lindenmeyer, C. P., Baumgärtner, N., Kotzur, L., Stolten,
   D., Robinius, M., Bardow, A., and Brandt, A. R. (2020). “Extreme events in
   time series aggregation: A case study for optimal residential energy supply
   systems.” *Applied Energy*, 263, 115223.
   [doi:10.1016/j.apenergy.2020.115223](https://doi.org/10.1016/j.apenergy.2020.115223).
5. Kotzur, L., Markewitz, P., Robinius, M., and Stolten, D. (2018). “Time
   series aggregation for energy system design: Modeling seasonal storage.”
   *Applied Energy*, 213, 123–135.
   [doi:10.1016/j.apenergy.2018.01.023](https://doi.org/10.1016/j.apenergy.2018.01.023).

### Input-data provenance

6. Svoboda, R., Basterrech, S., Kozal, J., Platoš, J., and Woźniak, M.
   “A Natural Gas Consumption Forecasting System for Continual Learning
   Scenarios based on Hoeffding Trees with Change Point Detection Mechanism.”
   [arXiv:2309.03720](https://arxiv.org/abs/2309.03720) and
   [VŠB dataset page](https://ai.vsb.cz/).
7. Open-Meteo.
   [Historical Weather API documentation](https://open-meteo.com/en/docs/historical-weather-api).
8. Copernicus Climate Change Service.
   [ERA5 hourly data on single levels](https://doi.org/10.24381/cds.adbb2d47).
9. pvlib python.
   [PVWatts DC model](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)
   and
   [temperature-model documentation](https://pvlib-python.readthedocs.io/en/stable/user_guide/modeling_topics/temperature.html).

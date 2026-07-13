# h2-blending-design

Optimization model for hydrogen blending with hourly gas-demand and photovoltaic-generation data.

## Photovoltaic data pipeline

The PV dataset is generated for Prague Airport (LKPR) and aligned with the timestamps in `data/gas/ppnet_metar.csv`.

### Configuration

The pipeline configuration is stored in `config/pv_config.json`:

- location: Prague Airport (LKPR), 50.100833, 14.260000;
- period: 2013-2019;
- weather source: Open-Meteo Historical Weather API with ERA5 data;
- PV system: 1 kWp crystalline silicon, 35-degree tilt, south-facing;
- system losses: 14%;
- timestamp reference: UTC.

### Data organization

```text
data/info/  model parameters, costs, probabilities, and source notes
data/gas/   gas-demand datasets and PPNet metadata
data/pv/    PV profiles, raw ERA5 responses, and processed outputs
data/scenarios/  joint representative gas and PV days
```

### Run the pipeline

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\download_open_meteo.py
.\.venv\Scripts\python.exe scripts\process_open_meteo.py
```

The download script saves one raw ERA5 JSON file per year. Existing files are preserved, allowing interrupted downloads to resume. Use `--force` to download them again:

```powershell
.\.venv\Scripts\python.exe scripts\download_open_meteo.py --force
```

The processing script estimates cell temperature with the Faiman model, calculates DC power with PVWatts, aligns the results with the gas dataset, and performs dataset validations.

### Generated files

```text
data/pv/raw/open_meteo_era5_<year>.json
data/pv/processed/pv_capacity_factor_ppnet_2013_2019.csv
data/pv/processed/pv_dataset_summary.json
```

The raw files contain temperature, wind speed, and solar irradiance data. The processed CSV contains hourly PV power and capacity factor. Validation results are stored in the summary JSON.

## Representative scenarios

Create joint representative days after processing the PV data:

```powershell
.\.venv\Scripts\python.exe scripts\create_representative_scenarios.py
```

The script aligns gas and PV by timestamp and applies k-medoids to their combined 24-hour profiles. Each scenario is a real historical day, so gas and PV from different dates are never combined. Days containing missing, negative, or extreme gas outliers are excluded instead of being interpolated. Outliers use the upper Tukey fence with three interquartile ranges. High-gas, high-gas/low-PV, low-gas/low-PV, and high-PV extreme days are retained.

Input paths and clustering settings are constants at the beginning of the script. The default configuration creates 11 scenarios and replaces the generated files on each execution.

The script also creates a PCA visualization of the clusters. Stars identify the representative historical days; extreme scenarios have a red outline and an `(E)` label. PCA is used only for visualization; clustering still uses all 48 hourly gas and PV attributes. The PDF uses the Gulliver font stored in `data/Gulliver.otf`.

```text
data/scenarios/gas_representative_days.csv
data/scenarios/pv_representative_days.csv
data/scenarios/scenario_metadata.csv
data/scenarios/representative_scenarios_pca.pdf
data/scenarios/representative_days_profiles.pdf
```

### Sources

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [ERA5 hourly data on single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
- [pvlib temperature models](https://pvlib-python.readthedocs.io/en/stable/user_guide/modeling_topics/temperature.html)
- [pvlib PVWatts DC model](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)
- [VSB natural-gas forecasting dataset](https://ai.vsb.cz/)
- [Representative-period clustering for energy-system optimization](https://optimization-online.org/wp-content/uploads/2018/09/6814.pdf)

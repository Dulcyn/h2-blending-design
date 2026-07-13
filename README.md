# h2-blending-design

Optimization model for hydrogen blending with hourly gas-demand and photovoltaic-generation data.

## Photovoltaic data pipeline

The PV dataset is generated for Prague Airport (LKPR) and aligned with the timestamps in `data/ppnet_metar.csv`.

### Configuration

The pipeline configuration is stored in `config/pv_config.json`:

- location: Prague Airport (LKPR), 50.100833, 14.260000;
- period: 2013-2019;
- weather source: Open-Meteo Historical Weather API with ERA5 data;
- PV system: 1 kWp crystalline silicon, 35-degree tilt, south-facing;
- system losses: 14%;
- timestamp reference: UTC.

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
data/raw/open_meteo_era5_<year>.json
data/processed/pv_capacity_factor_ppnet_2013_2019.csv
data/processed/pv_dataset_summary.json
```

The raw files contain temperature, wind speed, and solar irradiance data. The processed CSV contains hourly PV power and capacity factor. Validation results are stored in the summary JSON.

### Sources

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [ERA5 hourly data on single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
- [pvlib temperature models](https://pvlib-python.readthedocs.io/en/stable/user_guide/modeling_topics/temperature.html)
- [pvlib PVWatts DC model](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)
- [VSB natural-gas forecasting dataset](https://ai.vsb.cz/)

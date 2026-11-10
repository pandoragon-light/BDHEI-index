# Station climate example

`station_monthly_climate.csv` contains generated monthly temperature and precipitation for two synthetic stations from 1981 to 2010. It includes station ID, date, latitude, longitude, temperature in Celsius and monthly precipitation in mm.

Run from the repository directory:

```powershell
bdhei station-indices --config configs/station_climate.example.yaml
```

Results contain the climate inputs, SPEI, STI and BDHEI. Change `spei_scale` at the top of the configuration to select SPEI-1 or SPEI-3. These sample values are generated for demonstrating the program and testing the workflow.

# NASA data used by the game

Fetched by `tools/fetch_nasa_data.py` on 2026-11-14. The game reads these files from disk only and never needs the internet.

## donki_flr.json
- URL: https://api.nasa.gov/DONKI/FLR?startDate=<start>&endDate=<end>&api_key=<NASA_API_KEY>
- Fetched: 2026-11-14
- Used for: radiation storms (solar flares)
- Status: NOT AVAILABLE (no file saved). api.nasa.gov answered HTTP 404 `{"status":404,"path":"/DONKI-API/get/FLR/"}` for every window tried on 2026-11-14 (last 30 days, 60-day windows, other months), so no flares could be fetched. The game keeps radiation storms on its built-in timer with no NASA label. Retry with `python tools/fetch_nasa_data.py --only donki --key <your key>`; the endpoint may work later.

## donki_sep.json
- URL: https://api.nasa.gov/DONKI/SEP?startDate=<start>&endDate=<end>&api_key=<NASA_API_KEY>
- Fetched: 2026-11-14
- Used for: radiation storms (solar energetic particle events)
- Status: NOT AVAILABLE (no file saved). The last 30 days (2026-10-15 to 2026-11-14) returned HTTP 200 with an empty list `[]`: no SEP events in that window. Wider windows were then blocked by the DEMO_KEY rate limit (HTTP 429). Retry with `--key <your own key>` to look further back (the API allows 60 days per call). Until a file exists the game keeps storms on its built-in timer with no NASA label.

## diviner_equator.csv
- URL: https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/global_cumul_avg_cyl_00n10n_002.tab  (HTTP Range, bytes 78105713-78116560: 96 rows of the 156 MB table)
- Fetched: 2026-11-14
- Used for: lunar surface temperature vs local lunar time, equator, lon 0.25 E, lat 0.25 N: day maximum, night minimum and the simulated temperature
- Status: OK, 96 bins of 0.25 h, column tbol (bolometric brightness temperature); empty = bin with no observations

## diviner_south_pole.csv
- URL: https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/global_cumul_avg_cyl_90s80s_002.tab  (HTTP Range, bytes 78105713-78116560: 96 rows of the 156 MB table)
- Fetched: 2026-11-14
- Used for: lunar surface temperature vs local lunar time, south pole region, lon 0.25 E, lat 89.75 S: day maximum, night minimum and the simulated temperature
- Status: OK, 96 bins of 0.25 h, column tbol (bolometric brightness temperature); empty = bin with no observations

## meo_impacts.json
- URL: https://www3.nasa.gov/sites/default/files/atoms/files/alamo_lunar_impact_observations443.pdf  (listed on https://www.nasa.gov/meteoroid-environment-office/lunar-impact-monitoring/lunar-impacts/)
- Fetched: 2026-11-14
- Used for: lunar impact flashes seen by NASA's Meteoroid Environment Office (MSFC ALaMO candidate database, last updated 1-Feb-2020): the tower's shots follow this list in date order
- Status: OK, 404 flashes parsed (first 2005-11-07, last 2020-11-21). The PDF is called a 'candidate' database by NASA; the game says 'NASA lunar impact monitoring'

## veggie_facts.json
- URL: https://www.nasa.gov/wp-content/uploads/2019/04/veggie_fact_sheet_508.pdf
- Fetched: 2026-11-14
- Used for: Greenhouse action: grow delay, power cost and the fact shown on use
- Status: OK, 33 days to harvest, about 70 W (read from the NASA Facts sheet)

## Credits shown in the game
- Radiation storms: `Source: NASA DONKI`
- Temperature: `Source: NASA LRO Diviner`
- Asteroid warnings: `Source: NASA lunar impact monitoring`
- Greenhouse: `Source: NASA Veggie`

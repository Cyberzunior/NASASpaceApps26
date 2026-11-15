#!/usr/bin/env python3
"""Download every NASA dataset the game uses into data/nasa/ and write data/nasa/SOURCES.md.

    python tools/fetch_nasa_data.py [--key DEMO_KEY] [--only donki,diviner,meo,veggie]

The game reads these files from disk only; it never needs the internet. Run this once with a network.
Needs only the standard library, except `pypdf` for the two PDFs (pip install pypdf). Without pypdf those two
datasets are skipped and SOURCES.md says so. Nothing is invented: a dataset that cannot be fetched is reported as such.
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "nasa")
UA = {"User-Agent": "Mozilla/5.0 (T-Minus_6 data fetch)"}
NOTES = []      # (file, url, what, status text)


def get(url, headers=None, timeout=60, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:      # noqa: BLE001
            last = e
    raise RuntimeError("%s: %s" % (url, last))


def save(name, data):
    os.makedirs(OUT, exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(os.path.join(OUT, name), mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f:
        f.write(data)


def today():
    return datetime.date.today().isoformat()


# ------------------------------------------------------------------ 9.1 DONKI
def fetch_donki(key):
    end = datetime.date.today()
    for kind, name in (("FLR", "solar flares"), ("SEP", "solar energetic particle events")):
        got, used, errors = None, None, []
        # the last 30 days first, as asked; if that holds no events, go back in 60-day steps (the API maximum)
        windows = [(end - datetime.timedelta(days=30), end)]
        for i in range(0, 6):
            windows.append((end - datetime.timedelta(days=60 * (i + 1)), end - datetime.timedelta(days=60 * i)))
        for a, b in windows:
            url = "https://api.nasa.gov/DONKI/%s?startDate=%s&endDate=%s&api_key=%s" % (kind, a, b, key)
            try:
                raw = json.loads(get(url, tries=2).decode("utf-8") or "[]")
            except Exception as e:      # noqa: BLE001
                errors.append("%s..%s: %s" % (a, b, str(e)[-60:]))
                if "429" in str(e):             # rate limit (DEMO_KEY: about 30 calls an hour): stop, do not burn more calls
                    errors.append("rate limited by api.nasa.gov (HTTP 429): retry later or pass --key with your own key")
                    break
                continue
            if isinstance(raw, list) and raw:
                got, used = raw, (a, b)
                break
            used = (a, b)
        fname = "donki_%s.json" % kind.lower()
        shown = "https://api.nasa.gov/DONKI/%s?startDate=<start>&endDate=<end>&api_key=<NASA_API_KEY>" % kind
        if got:
            save(fname, json.dumps({"fetched": today(), "window": [str(used[0]), str(used[1])], "events": got}, indent=1))
            win30 = used[0] == end - datetime.timedelta(days=30)
            NOTES.append((fname, shown, "radiation storms (%s)" % name,
                          "OK, %d events, window %s to %s%s" % (len(got), used[0], used[1],
                                                                "" if win30 else " (the last 30 days held no events, so the window moved back)")))
        else:
            NOTES.append((fname, shown, "radiation storms (%s)" % name,
                          "NOT AVAILABLE: no events returned. " + ("; ".join(errors[:3]) if errors else "all windows empty")))
            print("DONKI %s: nothing usable (%s)" % (kind, "; ".join(errors[:2])))


# ------------------------------------------------------------------ 9.2 Diviner
GCP = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/"
ROW = 113           # RECORD_BYTES of the Diviner GCP tables
SITES = (("equator", "global_cumul_avg_cyl_00n10n_002.tab", 0.25, 0.25, "equator, lon 0.25 E, lat 0.25 N"),
         ("south_pole", "global_cumul_avg_cyl_90s80s_002.tab", 0.25, -89.75, "south pole region, lon 0.25 E, lat 89.75 S"))


def fetch_diviner():
    for key, tab, lon, lat, label in SITES:
        # rows are ordered longitude, then latitude (20 bins of 0.5 deg per 10 deg band), then 96 local-time bins
        lon_i = int((lon + 180.0) / 0.5)
        band0 = -90.0 if lat < 0 else 0.0
        lat_i = int((lat - (-90.0 if "90s80s" in tab else band0)) / 0.5)
        if "90s80s" in tab:
            lat_i = int((lat + 90.0) / 0.5)
        first = 1 + (lon_i * 20 + lat_i) * 96
        url = GCP + tab
        rng = "bytes=%d-%d" % (first * ROW, (first + 96) * ROW - 1)
        fname = "diviner_%s.csv" % key
        try:
            text = get(url, {"Range": rng}).decode("ascii")
            rows = [[c.strip() for c in l.split(",")] for l in text.splitlines() if l.strip()]
            if len(rows) != 96 or any(abs(float(r[0]) - lon) > 0.01 or abs(float(r[1]) - lat) > 0.01 for r in rows):
                raise ValueError("unexpected cell (%s,%s) in the byte range" % (rows[0][0], rows[0][1]))
        except Exception as e:      # noqa: BLE001
            NOTES.append((fname, url, "lunar surface temperature vs local time (%s)" % label, "NOT AVAILABLE: %s" % e))
            print("Diviner %s failed: %s" % (key, e))
            continue
        with open(os.path.join(OUT, fname), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["local_time_h", "tbol_K", "tbol_C", "lon_deg", "lat_deg"])
            for r in rows:
                k = float(r[10])
                w.writerow([r[2], "" if k < -9000 else "%.2f" % k, "" if k < -9000 else "%.2f" % (k - 273.15), r[0], r[1]])
        NOTES.append((fname, url + "  (HTTP Range, bytes %d-%d: 96 rows of the 156 MB table)" % (first * ROW, (first + 96) * ROW - 1),
                      "lunar surface temperature vs local lunar time, %s: day maximum, night minimum and the simulated temperature" % label,
                      "OK, 96 bins of 0.25 h, column tbol (bolometric brightness temperature); empty = bin with no observations"))


# ------------------------------------------------------------------ 9.4 MEO impact flashes
MEO_URL = "https://www3.nasa.gov/sites/default/files/atoms/files/alamo_lunar_impact_observations443.pdf"
MEO_PAGE = "https://www.nasa.gov/meteoroid-environment-office/lunar-impact-monitoring/lunar-impacts/"
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
LINE = re.compile(r"^(\d+)\s+(\d{1,2})-([A-Z][a-z]{2})-(\d{4})\s+(\d{1,2}:\d{2}:\d{2}(?:\.\d)?)\s+(\S+)\s+([\d.]+)\s*([EW])\s+([\d.]+)\s*([NS])\s+(.+?)\s+[\d.]+\s+0\.\d+\s")


def fetch_meo():
    try:
        import pypdf
    except ImportError:
        NOTES.append(("meo_impacts.json", MEO_URL, "lunar impact flashes (tower schedule)", "NOT AVAILABLE: pypdf not installed"))
        print("pypdf missing: skipping the MEO list (pip install pypdf)")
        return
    try:
        pdf = get(MEO_URL, timeout=120)
        save("meo_lunar_impact_observations.pdf", pdf)
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        seen, out = set(), []
        for page in reader.pages:
            for line in (page.extract_text() or "").splitlines():
                m = LINE.match(line.strip())
                if not m or m.group(1) in seen or m.group(3) not in MONTHS:
                    continue
                seen.add(m.group(1))
                n, d, mon, y, hms, typ, lo, ew, la, ns, region = m.groups()
                out.append({"flash": int(n), "date": "%s-%02d-%02d" % (y, MONTHS[mon], int(d)), "time_ut": hms, "type": typ,
                            "lon": float(lo) * (1 if ew == "E" else -1), "lat": float(la) * (1 if ns == "N" else -1),
                            "region": region.strip()})
        out.sort(key=lambda e: (e["date"], e["time_ut"]))
        if len(out) < 50:
            raise ValueError("only %d rows parsed" % len(out))
        save("meo_impacts.json", json.dumps({"fetched": today(), "source": MEO_URL, "impacts": out}, indent=1))
        NOTES.append(("meo_impacts.json", MEO_URL + "  (listed on " + MEO_PAGE + ")",
                      "lunar impact flashes seen by NASA's Meteoroid Environment Office (MSFC ALaMO candidate database, last updated 1-Feb-2020): "
                      "the tower's shots follow this list in date order",
                      "OK, %d flashes parsed (first %s, last %s). The PDF is called a 'candidate' database by NASA; "
                      "the game says 'NASA lunar impact monitoring'" % (len(out), out[0]["date"], out[-1]["date"])))
    except Exception as e:      # noqa: BLE001
        NOTES.append(("meo_impacts.json", MEO_URL, "lunar impact flashes (tower schedule)", "NOT AVAILABLE: %s" % e))
        print("MEO failed:", e)


# ------------------------------------------------------------------ 9.5 Veggie
VEG_URL = "https://www.nasa.gov/wp-content/uploads/2019/04/veggie_fact_sheet_508.pdf"


def fetch_veggie():
    try:
        import io
        import pypdf
        pdf = get(VEG_URL, timeout=120)
        save("veggie_fact_sheet.pdf", pdf)
        text = " ".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
        text = re.sub(r"\s+", " ", text)
        days = re.search(r"grew for (\d+) days", text)
        watts = re.search(r"runs on about (\d+) watts", text)
        crop = re.search(r"['‘]Outredgeous['’] red romaine lettuce", text)
        if not (days and watts and crop):
            raise ValueError("expected sentences not found in the fact sheet (days=%s watts=%s crop=%s)" % (bool(days), bool(watts), bool(crop)))
        save("veggie_facts.json", json.dumps({
            "fetched": today(), "source": VEG_URL, "crop": "'Outredgeous' red romaine lettuce", "mission": "VEG-01 on the ISS",
            "days_to_harvest": int(days.group(1)), "power_watts": int(watts.group(1)),
            "quotes": ["grew for %s days" % days.group(1), "Veggie runs on about %s watts for the lights, fans and control electronics" % watts.group(1)]}, indent=1))
        NOTES.append(("veggie_facts.json", VEG_URL, "Greenhouse action: grow delay, power cost and the fact shown on use",
                      "OK, %s days to harvest, about %s W (read from the NASA Facts sheet)" % (days.group(1), watts.group(1))))
    except Exception as e:      # noqa: BLE001
        NOTES.append(("veggie_facts.json", VEG_URL, "Greenhouse action", "NOT AVAILABLE: %s" % e))
        print("Veggie failed:", e)


# ------------------------------------------------------------------ SOURCES.md
def write_sources():
    lines = ["# NASA data used by the game", "",
             "Fetched by `tools/fetch_nasa_data.py` on %s. The game reads these files from disk only and never needs the internet." % today(), ""]
    for fname, url, use, status in NOTES:
        lines += ["## %s" % fname, "- URL: %s" % url, "- Fetched: %s" % today(), "- Used for: %s" % use, "- Status: %s" % status, ""]
    lines += ["## Credits shown in the game",
              "- Radiation storms: `Source: NASA DONKI`", "- Temperature: `Source: NASA LRO Diviner`",
              "- Asteroid warnings: `Source: NASA lunar impact monitoring`", "- Greenhouse: `Source: NASA Veggie`", ""]
    save("SOURCES.md", "\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("NASA_API_KEY", "DEMO_KEY"))
    ap.add_argument("--only", default="donki,diviner,meo,veggie")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    want = set(a.only.split(","))
    if "donki" in want:
        fetch_donki(a.key)
    if "diviner" in want:
        fetch_diviner()
    if "meo" in want:
        fetch_meo()
    if "veggie" in want:
        fetch_veggie()
    if want >= {"donki", "diviner", "meo", "veggie"}:
        write_sources()
    for n in NOTES:
        print("%-28s %s" % (n[0], n[3][:110]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

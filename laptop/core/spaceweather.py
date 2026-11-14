"""Real solar flares from NASA DONKI (Space Weather Database Of Notifications, Knowledge, Information).

The pot on the weather station (A1) scrubs through the flares of the last SPACE_WEATHER_DAYS days, oldest on
the left, newest on the right, with a "quiet Sun" stop at the far left. The chosen flare's class sets how far the
station's temperature swings over one orbit (sunlight and Earth's shadow): C1 about 3 C, M1 about 6 C,
X1 about 9 C, X10 and above 12 C. The laptop sends that as Y,swing to the station.

Data: https://api.nasa.gov/DONKI/FLR (free key from api.nasa.gov; DEMO_KEY allows only a few calls an hour).
The last good answer is cached in laptop/data/donki_flr.json, so the game also works offline.
"""
import datetime
import json
import math
import os
import threading
import urllib.request

import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "data", "donki_flr.json")
URL = "https://api.nasa.gov/DONKI/FLR?startDate={start}&endDate={end}&api_key={key}"
CLASS_FLUX = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}    # GOES X-ray peak flux, W/m2
QUIET = {"time": "", "cls": "quiet Sun", "swing": 0.0}


def flux(cls):
    """'M2.4' -> 2.4e-5 W/m2, or None."""
    try:
        return CLASS_FLUX[cls[0].upper()] * float(cls[1:] or 1)
    except (KeyError, ValueError, IndexError, TypeError):
        return None


def swing_for(cls):
    """Orbit temperature swing in C for a flare class: 3 C per decade of X-ray flux above C1, 1 to 12 C."""
    f = flux(cls)
    if f is None:
        return 0.0
    return round(max(1.0, min(12.0, 3.0 + 3.0 * math.log10(f / 1e-6))), 1)


def parse(raw):
    """DONKI FLR JSON -> [{'time', 'cls', 'swing'}] sorted oldest first, quiet Sun first."""
    out = []
    for e in raw if isinstance(raw, list) else []:
        cls, t = e.get("classType"), e.get("peakTime") or e.get("beginTime")
        if flux(cls) is not None and t:
            out.append({"time": t[:16].replace("T", " "), "cls": cls, "swing": swing_for(cls)})
    out.sort(key=lambda e: e["time"])
    return [QUIET] + out


class SpaceWeather:
    def __init__(self, cache=CACHE):
        self.cache = cache
        self.lock = threading.Lock()
        self.events = [QUIET]
        self.source = "no NASA data yet"
        self._load_cache()

    def _load_cache(self):
        try:
            with open(self.cache, encoding="utf-8") as f:
                saved = json.load(f)
            self._set(parse(saved["flares"]), "cached NASA DONKI %s" % saved.get("fetched", "?"))
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _set(self, events, source):
        with self.lock:
            self.events, self.source = events, source

    def refresh(self, wait=False):
        """Fetch the last SPACE_WEATHER_DAYS days in a background thread (never blocks the game)."""
        th = threading.Thread(target=self._fetch, daemon=True, name="donki")
        th.start()
        if wait:
            th.join()

    def _fetch(self):
        end = datetime.date.today()
        start = end - datetime.timedelta(days=int(C.SPACE_WEATHER_DAYS))
        url = URL.format(start=start, end=end, key=C.NASA_API_KEY or "DEMO_KEY")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "T-Minus_6"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = json.loads(r.read().decode("utf-8") or "[]")
        except Exception as e:      # noqa: BLE001 - offline, rate limited (HTTP 429), bad key: keep the cache
            with self.lock:
                self.source = "%s (fetch failed: %s)" % (self.source, e)
            return
        self._set(parse(raw), "NASA DONKI %s to %s" % (start, end))
        try:
            os.makedirs(os.path.dirname(self.cache), exist_ok=True)
            with open(self.cache, "w", encoding="utf-8") as f:
                json.dump({"fetched": str(end), "flares": raw}, f)
        except OSError:
            pass

    def loaded(self):
        with self.lock:
            return len(self.events) > 1

    def pick(self, pot):
        """Pot 0-1023 -> the flare under the knob (quiet Sun at 0)."""
        with self.lock:
            ev = self.events
        i = int(round(max(0, min(1023, pot)) / 1023.0 * (len(ev) - 1)))
        return ev[i]

    def label(self, e):
        return e["cls"] if not e["time"] else "%s flare %s" % (e["cls"], e["time"][:10])

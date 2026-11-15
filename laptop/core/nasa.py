"""NASA data, read from data/nasa/ on this computer. Never touches the network: run tools/fetch_nasa_data.py once to fill the folder.
Every loader returns an object whose `ok` says whether real data was found; a feature without data stays on its built-in
timer and shows no NASA label."""
import csv
import datetime
import json
import os

import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "data", "nasa"))


def _json(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Diviner:
    """LRO Diviner bolometric temperature (C) against local lunar time (hours 0..24) for one site."""
    SOURCE = "NASA Diviner (replay)"

    def __init__(self, site=None):
        self.ok, self.t_min, self.t_max, self.table = False, -170.0, 115.0, []
        pts = []
        fname = "diviner_%s.csv" % (site or C.DIVINER_SITE)
        self.fetched = FETCHED.get(fname)
        try:
            with open(os.path.join(DATA, fname), encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r["tbol_C"] != "":
                        pts.append((float(r["local_time_h"]), float(r["tbol_C"])))
        except (OSError, ValueError, KeyError):
            pass
        if len(pts) >= 24:
            self.ok, self.table = True, sorted(pts)
            self.t_min, self.t_max = min(t for _, t in pts), max(t for _, t in pts)

    def at(self, hour):
        """Interpolated temperature at a local lunar time (wraps around midnight). Gaps in the table are bridged."""
        hour %= 24.0
        if not self.ok:                       # built-in curve, never labelled as NASA data
            import math
            return -27.5 + 142.5 * max(-1.0, math.sin((hour - 6.0) / 12.0 * math.pi)) if 6 <= hour <= 18 else -170.0
        tb = self.table
        if hour <= tb[0][0]:
            (h0, t0), (h1, t1) = (tb[-1][0] - 24.0, tb[-1][1]), tb[0]
        elif hour >= tb[-1][0]:
            (h0, t0), (h1, t1) = tb[-1], (tb[0][0] + 24.0, tb[0][1])
        else:
            lo = 0
            while tb[lo + 1][0] < hour:
                lo += 1
            (h0, t0), (h1, t1) = tb[lo], tb[lo + 1]
        return t0 + (t1 - t0) * (hour - h0) / ((h1 - h0) or 1.0)


def _date(text):
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _sources_fetched():
    """File name -> 'Fetched' date, read from data/nasa/SOURCES.md: how old the data the game runs on is."""
    out, name = {}, None
    try:
        with open(os.path.join(DATA, "SOURCES.md"), encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("## "):
                    name = s[3:].strip()
                elif s.startswith("- Fetched:") and name:
                    d = _date(s[len("- Fetched:"):].strip())
                    if d:
                        out[name] = str(d)
    except OSError:
        pass
    return out


FETCHED = _sources_fetched()


class Storms:
    """Real DONKI events in date order: solar flares (class C/M/X) and SEP events."""
    SOURCE = "NASA DONKI"

    def __init__(self):
        self.events = []
        self.fetched = FETCHED.get("donki_flr.json") or FETCHED.get("donki_sep.json")
        flr = _json("donki_flr.json")
        for e in (flr or {}).get("events", []):
            cls = str(e.get("classType") or "")
            d = _date(e.get("peakTime") or e.get("beginTime"))
            if cls[:1].upper() in "CMX" and d:
                dur = {"C": C.STORM_DUR_C, "M": C.STORM_DUR_M, "X": C.STORM_DUR_X}[cls[0].upper()]
                self.events.append({"label": "%s flare" % cls, "date": str(d), "dur": dur})
        sep = _json("donki_sep.json")
        for e in (sep or {}).get("events", []):
            d = _date(e.get("eventTime"))
            if d:
                self.events.append({"label": "SEP event", "date": str(d), "dur": C.STORM_DUR_SEP})
        self.events.sort(key=lambda e: e["date"])
        self.ok = bool(self.events)


class Impacts:
    """The MEO list of lunar impact flashes, in date order, and the game-time gap before each shot."""
    SOURCE = "NASA lunar impact monitoring"

    def __init__(self):
        raw = (_json("meo_impacts.json") or {}).get("impacts", [])
        self.fetched = FETCHED.get("meo_impacts.json")
        self.events = sorted((e for e in raw if _date(e.get("date"))), key=lambda e: _date(e["date"]))
        self.ok = len(self.events) >= 5

    def gap_s(self, i):
        """Game seconds between flash i-1 and flash i: the real gap in days, scaled and clamped."""
        a, b = _date(self.events[(i - 1) % len(self.events)]["date"]), _date(self.events[i % len(self.events)]["date"])
        days = abs((b - a).days) if a and b else 0
        return max(C.STRIKE_MIN_GAP_S, min(C.STRIKE_MAX_GAP_S, C.STRIKE_MIN_GAP_S + days * C.STRIKE_S_PER_DAY))


class Veggie:
    """NASA Veggie facts: crop, days to harvest, power. Scaled to game numbers for the Greenhouse action."""
    SOURCE = "NASA Veggie"

    def __init__(self):
        d = _json("veggie_facts.json")
        self.fetched = FETCHED.get("veggie_facts.json")
        self.ok = bool(d and d.get("days_to_harvest") and d.get("power_watts"))
        self.crop = (d or {}).get("crop", "")
        self.days = (d or {}).get("days_to_harvest", 0)
        self.watts = (d or {}).get("power_watts", 0)
        self.delay_s = self.days * C.GAME_SECONDS_PER_DAY if self.ok else C.GREENHOUSE_DELAY_S
        self.power = round(self.watts / C.WATTS_PER_POWER_POINT) if self.ok else C.GREENHOUSE_POWER

    def fact(self):
        return "%s: %d days to harvest, about %d W" % (self.crop.replace("'", ""), self.days, self.watts) if self.ok else ""


class Nasa:
    def __init__(self):
        self.diviner, self.storms, self.impacts, self.veggie = Diviner(), Storms(), Impacts(), Veggie()

    def used(self):
        """The datasets that really drive the game this run, with how old the data is (for the debrief)."""
        def tag(f):
            return " (data fetched %s)" % f if f else ""
        out = []
        if self.storms.ok:
            out.append("NASA DONKI: solar flares and SEP events (radiation storms)%s" % tag(self.storms.fetched))
        if self.diviner.ok:
            out.append("NASA LRO Diviner: lunar surface temperatures, replayed%s" % tag(self.diviner.fetched))
        if self.impacts.ok:
            out.append("NASA lunar impact monitoring: impact flashes (asteroid strikes)%s" % tag(self.impacts.fetched))
        if self.veggie.ok:
            out.append("NASA Veggie: ISS plant growth (greenhouse)%s" % tag(self.veggie.fetched))
        return out

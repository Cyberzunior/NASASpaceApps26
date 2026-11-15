"""Frame budget governor.

The game always asks for the best picture it can afford. Every frame is timed (the CPU part, without the
vertical-sync wait) and a rolling 75th percentile decides whether the cheap knobs below are stepped down
or up. That keeps a strong laptop at full bloom with every pebble, and a weak one at 60 fps without
dropping the resolution or touching the game logic.

Manual override: QUALITY in config.local.json ("auto", "low", "balanced", "high"), or the Settings screen.
"""
import config as C

TIERS = ("low", "balanced", "high")

# bloom_every: refresh the bloom this often (frames). rocks / pebbles / stars: draw-distance or density
# multiplier. parts / wparts / tracks: hard caps. postfx: highest post-processing level this tier allows.
KNOBS = {
    "low":      {"bloom_every": 8, "rocks": 0.55, "pebbles": 0.55, "stars": 0.55, "parts": 380, "wparts": 220,
                 "tracks": 70, "postfx": 1},
    "balanced": {"bloom_every": 5, "rocks": 0.80, "pebbles": 0.80, "stars": 0.80, "parts": 650, "wparts": 340,
                 "tracks": 110, "postfx": 2},
    "high":     {"bloom_every": 4, "rocks": 1.00, "pebbles": 1.00, "stars": 1.00, "parts": 900, "wparts": 460,
                 "tracks": 140, "postfx": 2},
}

WINDOW = 90               # frames in the rolling sample
DOWN_MS = 15.2            # p75 above this: step down (a 60 Hz display allows 16.7)
UP_MS = 9.4               # p75 below this: step up if it stays there
HOLD_DOWN_S = 1.0
HOLD_UP_S = 3.0


class Perf:
    def __init__(self, mode=None, fps_cap=None):
        self.cap_ms = 1000.0 / float(fps_cap or C.FPS_CAP)
        self.mode = (mode or C.QUALITY or "auto").lower()
        if self.mode not in TIERS:
            self.mode = "auto"
        self.tier = "high" if self.mode == "auto" else self.mode
        self.k = KNOBS[self.tier]
        self.samples = []
        self.since_change = 0.0
        self.avg = self.cap_ms
        self.p75 = self.cap_ms
        self.changes = 0
        self.down_ms = min(DOWN_MS, self.cap_ms * 0.91)
        self.up_ms = min(UP_MS, self.cap_ms * 0.56)

    @property
    def auto(self):
        return self.mode == "auto"

    def note(self, ms, dt):
        """One frame of CPU time (ms), plus the frame's dt: called once per frame by the app."""
        self.samples.append(ms)
        if len(self.samples) > WINDOW:
            del self.samples[:len(self.samples) - WINDOW]
        n = len(self.samples)
        self.avg += (ms - self.avg) / min(n, 20)
        if not self.auto or n < 30:
            return
        s = sorted(self.samples)
        self.p75 = s[int(n * 0.75)]
        self.since_change += dt
        i = TIERS.index(self.tier)
        if self.p75 > self.down_ms and i > 0 and self.since_change >= HOLD_DOWN_S:
            self._set(TIERS[i - 1])
        elif self.p75 < self.up_ms and i < len(TIERS) - 1 and self.since_change >= HOLD_UP_S:
            self._set(TIERS[i + 1])

    def _set(self, tier):
        if tier == self.tier:
            return
        self.tier = tier
        self.k = KNOBS[tier]
        self.since_change = 0.0
        self.changes += 1
        self.samples.clear()

    def cycle(self):
        """The manual override: auto -> low -> balanced -> high -> auto."""
        order = ("auto",) + TIERS
        self.mode = order[(order.index(self.mode) + 1) % len(order)]
        self.tier = "high" if self.mode == "auto" else self.mode
        self.k = KNOBS[self.tier]
        self.samples.clear()
        self.since_change = 0.0
        return self.mode

    def reset(self):
        self.samples.clear()
        self.since_change = 0.0
        self.p75 = self.cap_ms

    def label(self):
        return self.mode.upper() if not self.auto or not self.changes else "%s/%s" % (self.mode.upper(), self.tier)


PERF = Perf()

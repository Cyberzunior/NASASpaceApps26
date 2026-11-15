"""Temperature: the NASA LRO Diviner table replayed on a sped-up lunar day clock. There is no sensor: the value is
never a live reading. One full day and night takes DAY_CLOCK_S seconds. Solar recharge needs daylight (local time 6..18)."""
import config as C

NORMAL, COLD, HOT = 0, 1, 2
NAMES = ("NORMAL", "COLD", "HOT")


class Thermal:
    def __init__(self, diviner):
        self.dv = diviner
        self.reset()

    def reset(self):
        self.clock_s = 0.0
        self.state = NORMAL
        self.lunar_c = self.dv.at(C.DAY_START_H)

    # ---- clock
    def local_hour(self):
        return (C.DAY_START_H + self.clock_s / C.DAY_CLOCK_S * 24.0) % 24.0

    def daylight(self):
        return 6.0 <= self.local_hour() < 18.0

    # ---- once a frame
    def update(self, dt):
        self.clock_s += dt
        self.lunar_c = self.dv.at(self.local_hour())
        span = (self.dv.t_max - self.dv.t_min) or 1.0
        f = (self.lunar_c - self.dv.t_min) / span
        h = C.THERMAL_HYST
        if self.state == NORMAL:
            self.state = HOT if f > C.THERMAL_HOT_FRAC else COLD if f < C.THERMAL_COLD_FRAC else NORMAL
        elif self.state == HOT and f < C.THERMAL_HOT_FRAC - h:
            self.state = NORMAL
        elif self.state == COLD and f > C.THERMAL_COLD_FRAC + h:
            self.state = NORMAL
        return self.state

    def label(self):
        """HUD text, for example 'Lunar surface 118 C'."""
        return "Lunar surface %.0f C" % self.lunar_c

    def source(self):
        """The credit line, only when the table really is NASA data."""
        return ("Source: %s" % self.dv.SOURCE) if self.dv.ok else ""

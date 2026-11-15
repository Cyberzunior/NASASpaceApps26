"""Temperature: the DHT11 reading mapped onto the LRO Diviner range, or a simulation from the Diviner table.
The lunar day clock runs one full day and night in DAY_CLOCK_S seconds. Solar recharge needs daylight (local time 6..18)."""
import config as C
from core.clock import now

NORMAL, COLD, HOT = 0, 1, 2
NAMES = ("NORMAL", "COLD", "HOT")


class Thermal:
    def __init__(self, diviner):
        self.dv = diviner
        self.reset()

    def reset(self):
        self.clock_s = 0.0
        self.state = NORMAL
        self.sensor_c = None           # last valid DHT11 reading
        self.t_valid = -999.0
        self.source = "SIM"            # "SENSOR" or "SIM"
        self.lunar_c = self.dv.at(C.DAY_START_H)
        self.hud_up = False

    # ---- clock
    def local_hour(self):
        return (C.DAY_START_H + self.clock_s / C.DAY_CLOCK_S * 24.0) % 24.0

    def daylight(self):
        return 6.0 <= self.local_hour() < 18.0

    # ---- inputs
    def on_reading(self, temp, hum, t):
        """A W line from the HUD panel. hum < 0 means the board is repeating our own V value: not a real reading."""
        if hum >= 0 and 0.0 <= temp <= 50.0:
            self.sensor_c, self.t_valid = temp, t

    def sensor_live(self, t):
        return self.hud_up and self.sensor_c is not None and t - self.t_valid < C.SENSOR_TIMEOUT_S

    # ---- once a frame
    def update(self, dt, t, hud_up):
        self.clock_s += dt
        self.hud_up = hud_up
        if self.sensor_live(t):
            self.source, self.lunar_c = "SENSOR", self.dv.from_sensor(self.sensor_c)
        else:
            self.source, self.lunar_c = "SIM", self.dv.at(self.local_hour())
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

    def virtual_sensor_c(self):
        """What to send to a connected HUD panel whose DHT11 is dead (V,tempC): the sensor-scale value of the simulation."""
        return self.dv.to_sensor(self.lunar_c)

    def label(self):
        """HUD text: 'Sensor 34 C = lunar surface 118 C' or 'SIM (NASA Diviner)  lunar surface 118 C'."""
        if self.source == "SENSOR":
            return "Sensor %.0f C = lunar surface %.0f C" % (self.sensor_c, self.lunar_c)
        return ("SIM (NASA Diviner)" if self.dv.ok else "SIM") + "  lunar surface %.0f C" % self.lunar_c

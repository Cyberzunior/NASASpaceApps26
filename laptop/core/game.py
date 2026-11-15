"""The rules of a run, with no drawing and no hardware code: four meters, base integrity (hearts), lunar samples,
asteroid strikes warned by the tower, NASA radiation storms and a thermal state from the LRO Diviner table (replayed, no sensor).
Talks to the devices through three small link objects and reads the mixed command from the shared state.
Runs headless in the tests."""
import math
import random

import config as C
from core import nasa as nasa_mod
from core import thermal as th
from core.model import angdiff, bearing_to, start_pose, step_pose
from core.tower_aim import TowerAim

METERS = ("power", "oxygen", "food", "shield")
LABELS = {"power": "Power", "oxygen": "Oxygen", "food": "Food", "shield": "Shield"}
KINDS = ("ice", "regolith", "mineral")
WHY = {
    "power": "Power runs the heaters, pumps and drives, and a lunar night lasts two weeks, so a base lives or dies by its power budget.",
    "oxygen": "A crew has only minutes without breathable air, so a lunar base needs scrubbers and a steady supply such as mined ice.",
    "food": "Packaged food runs out and resupply trips are slow and costly, so a lunar base has to grow part of its own food.",
    "shield": "With no atmosphere or magnetic field, radiation storms and meteoroids hit the base directly, so shielding is life support.",
}


class NullLink:
    """Stands in for a device link in tests and when a link is not built."""
    connected = False
    front_stop = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: False

    def one_way_s(self):
        return 0.0


class Game:
    def __init__(self, state, robot=None, tower=None, hud=None, log=None, nasa=None):
        self.state = state
        self.robot, self.tower, self.hud = robot or NullLink(), tower or NullLink(), hud or NullLink()
        self.log = log or (lambda msg: None)
        self.nasa = nasa or nasa_mod.Nasa()
        self.thermal = th.Thermal(self.nasa.diviner)
        self.aim = TowerAim(self.tower, self.log)      # yaw 0, scan, then follow the rover (and mark asteroid spots)
        self.fx, self.toasts = [], []             # drained by the renderer / HUD
        self.practice = False
        self.intro_on = False
        self.reset()

    # ---- lifecycle
    def reset(self, practice=False, intro=False):
        """Back to the start with LIVES hearts and full meters. Unlatches the rover, re-arms the tower, resets the HUD panel."""
        self.practice = practice
        self.craft = start_pose()
        self.m = {"power": C.START_POWER, "oxygen": C.START_OXYGEN, "food": C.START_FOOD, "shield": C.START_SHIELD}
        self.hearts = C.LIVES
        self.t = 0.0
        self.over, self.over_t = False, 0.0
        self.score = 0
        self.samples = {k: 0 for k in KINDS}
        self.strikes = 0
        self.near_misses = 0
        self.first_fail = None
        self.speed_ms = 0.0
        self.sample = None
        self.sample_bad_t = 0.0
        self.rest_until = -1.0
        self.greenhouse = []                      # (t_due, food)
        self.fact = ("", -1.0)                    # NASA Veggie line and when it stops showing
        self.storm = None
        self.storm_i = 0
        self.next_storm_t = random.uniform(C.STORM_GAP_MIN_S, C.STORM_GAP_MAX_S)
        self.strike = None
        self.strike_i = random.randrange(len(self.nasa.impacts.events)) if self.nasa.impacts.ok else 0
        self.next_strike_t = C.STRIKE_FIRST_S
        self._acc = {"oxygen": 0.0, "food": 0.0, "power": 0.0}
        self._starve = self._night = self._stormheart = 0.0
        self.fx.clear()
        self.thermal.reset()
        self.intro_on = bool(intro and not C.SKIP_INTRO)
        self.intro_t = 0.0
        with self.state.lock:
            self.state.ap_on = False
            self.state.ap_cmd = (0.0, 0.0)
            self.state.turn_scale = 1.0
            self.state.hold_commands = self.intro_on
        self.robot.latch(False)
        self.tower.set_armed(True)
        self.hud.reset()
        self.hud.set_lives(self.hearts)
        self.hud.set_samples(0)
        self._send_meters()
        if self.intro_on:
            self.hud.text("OUTPOST ONLINE", "")
            self.aim.stop()                                     # beam up until the run really starts
        else:
            self.aim.start()
        self.spawn_sample()
        self.log("run reset%s" % (" (intro)" if self.intro_on else ""))

    def skip_intro(self):
        if self.intro_on:
            self._end_intro()

    def _end_intro(self):
        self.intro_on = False
        with self.state.lock:
            self.state.hold_commands = False
        self.hud.clear_text()
        self.hud.chirp()
        self.aim.start()
        self.fx.append(("intro_end", 0, 0, ""))

    # ---- inputs
    def toggle_autopilot(self):
        with self.state.lock:
            self.state.ap_on = not self.state.ap_on
            on = self.state.ap_on
        self.log("auto-pilot %s" % ("on" if on else "off"))
        return on

    def fire_test_asteroid(self):
        """The test shot (joystick button, X key): one asteroid sequence now, shown without a date."""
        if not self.over and not self.intro_on and self.strike is None:
            return self._request_strike(test=True)
        return False

    def can_act(self):
        return not self.over and not self.intro_on and self.m["power"] > 0 and self.t >= self.rest_until

    def action(self, n):
        """Keys 1..4. Each is a trade. Returns a short message for the toast."""
        if self.over or self.intro_on:
            return ""
        if self.m["power"] <= 0:
            return "POWER OFF: actions locked"
        if self.t < self.rest_until:
            return ""
        m = self.m
        if n == 1:
            if m["power"] < C.SCRUBBER_POWER:
                return "Not enough power"
            m["power"] -= C.SCRUBBER_POWER
            m["oxygen"] = min(100.0, m["oxygen"] + C.SCRUBBER_OXYGEN)
            self.fx.append(("action", 0, 0, "scrubber"))
            return "Scrubber: +%d oxygen" % C.SCRUBBER_OXYGEN
        if n == 2:
            cost = self.nasa.veggie.power
            if m["power"] < cost:
                return "Not enough power"
            m["power"] -= cost
            m["oxygen"] = max(0.0, m["oxygen"] - C.GREENHOUSE_OXYGEN)
            self.greenhouse.append((self.t + self.nasa.veggie.delay_s, C.GREENHOUSE_FOOD))
            if self.nasa.veggie.ok:
                self.fact = (self.nasa.veggie.fact(), self.t + 8.0)
            self.fx.append(("action", 0, 0, "greenhouse"))
            return "Greenhouse planted: food in %.0f s" % self.nasa.veggie.delay_s
        if n == 3:
            if m["power"] < C.SHIELD_BOOST_POWER:
                return "Not enough power"
            m["power"] -= C.SHIELD_BOOST_POWER
            m["shield"] = min(100.0, m["shield"] + C.SHIELD_BOOST_GAIN)
            self.fx.append(("action", 0, 0, "shield"))
            return "Shield boost: +%d shield" % C.SHIELD_BOOST_GAIN
        if n == 4:
            self.rest_until = self.t + C.REST_S
            m["oxygen"] = min(100.0, m["oxygen"] + C.REST_OXYGEN)
            m["food"] = min(100.0, m["food"] + C.REST_FOOD)
            self.fx.append(("action", 0, 0, "rest"))
            return "Crew resting for %.0f s" % C.REST_S
        return ""

    def _warn(self):
        self.fx.append(("asteroid_warn", 0, 0, ""))
        self.hud.text("ASTEROID", "INCOMING!")                  # the same warning on the HUD panel

    t_wall = 0.0

    # ---- helpers
    def spawn_sample(self):
        """One sample at a time, never behind the rover: bearing uniform in +-SAMPLE_CONE_DEG from the heading right now."""
        c = self.craft
        bearing = random.uniform(-C.SAMPLE_CONE_DEG, C.SAMPLE_CONE_DEG)
        dist = random.uniform(C.SAMPLE_MIN_M, C.SAMPLE_MAX_M)
        a = math.radians(c.theta + bearing)
        self.sample = {"x": c.x + dist * math.cos(a), "y": c.y + dist * math.sin(a), "kind": random.choice(KINDS), "age": 0.0}
        self.sample_bad_t = 0.0

    def sample_bearing(self):
        s = self.sample
        return bearing_to(self.craft, s["x"], s["y"]) if s else 0.0

    def sample_distance(self):
        s = self.sample
        return math.hypot(s["x"] - self.craft.x, s["y"] - self.craft.y) if s else 0.0

    def _collect(self):
        s = self.sample
        k = s["kind"]
        self.samples[k] += 1
        self.score += C.SAMPLE_SCORE
        if k == "ice":
            self.m["oxygen"] = min(100.0, self.m["oxygen"] + C.SAMPLE_ICE_OXYGEN)
        elif k == "regolith":
            self.m["shield"] = min(100.0, self.m["shield"] + C.SAMPLE_REGOLITH_SHIELD)
        else:
            self.m["power"] = min(100.0, self.m["power"] + C.SAMPLE_MINERAL_POWER)
        self.hud.pickup()
        self.hud.set_samples(sum(self.samples.values()))
        self.fx.append(("pickup", s["x"], s["y"], k))
        self.log("sample collected: %s" % k)
        self.spawn_sample()

    def _lose_heart(self, why):
        if self.over:
            return
        self.hearts -= 1
        self.fx.append(("heart", 0, 0, why))
        self.hud.set_lives(self.hearts)
        self.log("heart lost (%s), %d left" % (why, self.hearts))
        if self.hearts <= 0:
            self.hearts = 0
            self.over, self.over_t = True, self.t
            self.robot.latch(True)
            self.tower.set_armed(False)
            self.hud.game_over()
            self.fx.append(("gameover", 0, 0, self.first_fail or ""))
            self.log("GAME OVER at T+%.0f s (first failure: %s)" % (self.t, self.first_fail))

    def _impact_point(self, bearing=0.0):
        """The marked spot: on the ground STRIKE_LEAD_M from the rover, at this bearing off its heading (the tower's yaw)."""
        c = self.craft
        a = math.radians(c.theta + bearing)
        return c.x + math.cos(a) * C.STRIKE_LEAD_M, c.y + math.sin(a) * C.STRIKE_LEAD_M

    def _request_strike(self, test=False):
        """Mark the spot (the tower's laser sits on it for the countdown), warn, and resolve when the countdown ends."""
        date = None
        imp = self.nasa.impacts
        if imp.ok and not test:
            date = imp.events[self.strike_i % len(imp.events)]["date"]
        elif test:
            date = imp.test_event["date"]                                    # the database entry for the test shot
        bearing = 0 if test else int(round(random.uniform(-C.ASTEROID_CONE_DEG, C.ASTEROID_CONE_DEG)))   # never behind the rover
        ix, iy = self._impact_point(bearing)
        self.strike = {"phase": "warn", "left": C.STRIKE_WARN_S, "mode": "own", "date": date, "x": ix, "y": iy, "vmax": 0.0, "test": test,
                       "bearing": bearing}
        self._warn()
        return True

    def impact_distance(self):
        """Metres from the rover to the marked spot, or None when no impact is warned."""
        st = self.strike
        if not st or "x" not in st:
            return None
        return math.hypot(st["x"] - self.craft.x, st["y"] - self.craft.y)

    def _resolve_strike(self, hit=None):
        """hit True / False forces the result. None: with the tower connected (the spot is on the floor) a hit means the rover is inside
        STRIKE_HIT_M of the marked spot; without it, a hit unless the rover drove faster than STRIKE_DODGE_SPEED of full speed."""
        st = self.strike or {}
        if hit is None:
            if self.tower.connected:
                hit = (self.impact_distance() or 0.0) <= C.STRIKE_HIT_M
            else:
                hit = st.get("vmax", 0.0) <= C.STRIKE_DODGE_SPEED
        self.strike = None
        self.hud.clear_text()
        if not st.get("test"):                                  # a scheduled strike: move on to the next real impact flash
            imp = self.nasa.impacts
            self.strike_i += 1
            gap = imp.gap_s(self.strike_i) if imp.ok else random.uniform(C.STRIKE_MIN_GAP_S, C.STRIKE_MAX_GAP_S)
            self.next_strike_t = self.t + gap
        if not hit:
            self.near_misses += 1
            self.score += C.STRIKE_DODGE_SCORE
            self.fx.append(("asteroid_miss", st.get("x", self.craft.x), st.get("y", self.craft.y), ""))
            self.toasts.append(("DODGED  +%d" % C.STRIKE_DODGE_SCORE, "ok"))
            self.log("asteroid dodged")
            return
        self.strikes += 1
        m = self.m
        if m["shield"] > 0:
            m["shield"] = max(0.0, m["shield"] - C.STRIKE_SHIELD)
        else:
            self._lose_heart("strike")
            k = random.choice(METERS)
            m[k] = max(0.0, m[k] - C.STRIKE_METER_DROP)
        self.fx.append(("hit", self.craft.x, self.craft.y, ""))
        self.log("asteroid hit")

    # ---- one frame
    def step(self, dt, wall=None):
        """Advance the run by dt seconds."""
        self.t_wall = self.t if wall is None else wall
        st = self.state
        if self.over:
            return
        if self.intro_on:                                       # the cutscene: nothing drains, nothing drives
            self.intro_t += dt
            st.drive_enabled = False
            if self.intro_t >= C.INTRO_S:
                self._end_intro()
            return
        m = self.m
        resting = self.t < self.rest_until
        powered = m["power"] > 0

        # movement: the same speed and turn the rover is sent
        speed, turn = st.cmd[0], st.cmd[1]
        st.drive_enabled = powered and not resting
        if st.drive_enabled:
            step_pose(self.craft, speed, turn, dt)
        self.speed_ms = speed * C.V_MAX * C.METERS_PER_CM if st.drive_enabled else 0.0
        driving = st.drive_enabled and abs(speed) > 0.05

        # thermal state and the day clock
        self.thermal.update(dt)
        self.hud.set_zone(self.thermal.state)
        self.hud.set_temp(self.thermal.lunar_c)                 # the link sends V,tempC once a second while connected
        thermal_x = 2.0 if self.thermal.state != th.NORMAL else 1.0

        # meters
        m["oxygen"] = max(0.0, m["oxygen"] - dt / C.OXYGEN_DRAIN_S)
        m["food"] = max(0.0, m["food"] - dt / C.FOOD_DRAIN_S)
        if not driving and self.thermal.daylight():
            m["power"] = min(100.0, m["power"] + dt / C.POWER_RECHARGE_S)
        else:
            m["power"] = max(0.0, m["power"] - dt * thermal_x / (C.POWER_DRAIN_DRIVE_S if driving else C.POWER_DRAIN_REST_S))
        for due, food in [g for g in self.greenhouse if g[0] <= self.t]:
            self.greenhouse.remove((due, food))
            m["food"] = min(100.0, m["food"] + food)
            self.fx.append(("harvest", 0, 0, ""))
            self.toasts.append(("Greenhouse harvest: +%d food" % food, "ok"))

        # samples
        if self.sample:
            self.sample["age"] += dt
            if self.sample_distance() < C.SAMPLE_PICKUP_M:
                self._collect()
            elif abs(self.sample_bearing()) > C.SAMPLE_BEHIND_DEG:
                self.sample_bad_t += dt
                if self.sample_bad_t >= C.SAMPLE_BEHIND_S:
                    self.spawn_sample()
            else:
                self.sample_bad_t = 0.0

        # radiation storms (NASA DONKI events, one every 30 to 45 s)
        if self.storm is None and self.t >= self.next_storm_t:
            ev = self.nasa.storms.events[self.storm_i % len(self.nasa.storms.events)] if self.nasa.storms.ok else None
            self.storm_i += 1
            self.storm = {"label": ev["label"] if ev else "RADIATION STORM", "date": ev["date"] if ev else None,
                          "left": ev["dur"] if ev else C.STORM_DUR_DEFAULT, "nasa": bool(ev)}
            self.fx.append(("storm", 0, 0, self.storm["label"]))
            self.log("radiation storm: %s" % self.storm)
        if self.storm:
            m["shield"] = max(0.0, m["shield"] - dt * C.STORM_SHIELD_DRAIN_S)
            if m["shield"] <= 0:
                self._stormheart += dt
                if self._stormheart >= C.STORM_HEART_S:
                    self._stormheart = 0.0
                    self._lose_heart("storm")
            self.storm["left"] -= dt
            if self.storm["left"] <= 0:
                self.storm = None
                self._stormheart = 0.0
                self.next_storm_t = self.t + random.uniform(C.STORM_GAP_MIN_S, C.STORM_GAP_MAX_S)

        # asteroid strikes
        if self.strike is None and self.t >= self.next_strike_t and not self.practice:
            self._request_strike()
        s = self.strike
        if s:
            s["left"] -= dt
            if s["phase"] == "warn":
                s["vmax"] = max(s["vmax"], abs(speed) if st.drive_enabled else 0.0)
            if s["left"] <= 0:
                self._resolve_strike()
        s = self.strike
        self.aim.update(dt, self.craft, (s["x"], s["y"]) if s and s["phase"] == "warn" else None)

        # first meter to fail, and the hearts it costs
        for k in METERS:
            if m[k] <= 0 and self.first_fail is None:
                self.first_fail = k
                self.log("first failure: %s" % k)
        if m["oxygen"] <= 0 or m["food"] <= 0:
            self._starve += dt
            if self._starve >= C.HEART_LOSS_S:
                self._starve = 0.0
                self._lose_heart("life support")
        else:
            self._starve = 0.0
        if m["power"] <= 0 and not self.thermal.daylight():     # no power at night: no heat, nothing recharges
            self._night += dt
            if self._night >= C.HEART_LOSS_S:
                self._night = 0.0
                self._lose_heart("no power at night")
        else:
            self._night = 0.0

        # auto-pilot: steer toward the sample
        if st.ap_on and self.sample:
            st.ap_cmd = (0.7, max(-1.0, min(1.0, self.sample_bearing() / 40.0)))

        self._send_meters()
        self.t += dt

    def _send_meters(self):
        self.hud.set_meters(*[self.m[k] for k in METERS])

    def idle(self, dt, wall):
        """Menus, pause, hardware check: nothing moves."""
        self.t_wall = wall

    def results(self):
        ff = self.first_fail or ""
        return {"time": self.t, "score": self.score, "samples": dict(self.samples), "strikes": self.strikes, "near_misses": self.near_misses,
                "first_fail": ff, "first_fail_label": LABELS.get(ff, "none"), "why": WHY.get(ff, ""),
                "nasa": self.nasa.used()}

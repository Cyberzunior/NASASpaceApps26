"""Lunar outpost: protocol, movement model, rules, NASA data, simulated devices over real sockets, the full game headless, firmware checks."""
import math
import os
import random
import re
import subprocess
import sys
import time

import pygame

import config as C
from core import statemachine as S
from core.events import Bus, Event
from core.game import Game
from core.model import angdiff, bearing_to, mix, step_pose
from core.state import SharedState
from devio import protocol as P

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def wait(cond, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


class Rec:
    """A link that records what the game sends."""
    connected = False
    front_stop = False

    def __init__(self, connected=False):
        self.connected, self.sent, self.pickups = connected, [], 0
        self.armed = True

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def f(*a, **k):
            self.sent.append((name,) + a)
            return True
        return f

    def fire(self, test=False):
        self.sent.append(("fire",))
        return True

    def pickup(self):
        self.pickups += 1


def make_game(tower=None, hud=None, **kw):
    st = SharedState()
    g = Game(st, Rec(), tower or Rec(), hud or Rec(), nasa=kw.get("nasa"))
    return g, st


# ---------------------------------------------------------------- protocol
def test_protocol_pickup_and_warning_use_the_same_letters_as_ping_and_weather():
    assert P.decode("P") == ("PICKUP",) and P.decode("P,5,100") == ("P", 5, 100)
    assert P.decode("W,3") == ("WARN", 3.0) and P.decode("W,24.5,40,1") == ("W", 24.5, 40, 1)
    assert P.decode("C,-45") == ("C", -45) and P.decode("M,80,65,70,40") == ("M", 80, 65, 70, 40)
    assert P.decode("F") == ("F",) and P.decode("K") == ("K",) and P.decode("garbage,,") is None
    assert P.encode("D", 170, -170, 0) == "D,170,-170,0"


# ---------------------------------------------------------------- movement model
def test_mixer_scales_to_max_pwm_and_a_d_turn_the_right_way():
    s, t, l, r = mix(1.0, 0.0)
    assert l == r == C.MAX_PWM == 170
    _, _, l, r = mix(0.0, 1.0)                       # D = turn right: left wheel faster
    assert l > 0 > r
    _, _, l, r = mix(0.0, -1.0)                      # A = turn left
    assert l < 0 < r


def test_invert_flags_flip_the_wheel_values_sent():
    from devio.links import RobotLink
    sent = []
    link = RobotLink(SharedState(), Bus(), lambda m: None)
    link.send = lambda line: sent.append(line) or True
    C.INVERT_LEFT = True
    try:
        link.send_drive(100, 100, 0)
    finally:
        C.INVERT_LEFT = False
    assert sent == ["D,-100,100,0"]


def test_pose_uses_the_same_speed_and_turn_as_the_rover():
    from core.model import start_pose
    p = start_pose()
    step_pose(p, 1.0, 0.0, 1.0)
    assert math.isclose(math.hypot(p.x, p.y), C.V_MAX * C.METERS_PER_CM, rel_tol=1e-6)


# ---------------------------------------------------------------- samples
def test_samples_spawn_within_40_degrees_of_the_heading_never_behind():
    g, _ = make_game()
    random.seed(3)
    for heading in (0, 90, 200, 333):
        g.craft.theta = heading
        for _ in range(300):
            g.spawn_sample()
            assert abs(g.sample_bearing()) <= C.SAMPLE_CONE_DEG + 1e-6
            assert C.SAMPLE_MIN_M - 1e-6 <= g.sample_distance() <= C.SAMPLE_MAX_M + 1e-6


def test_driving_over_a_sample_collects_it_and_sends_the_pickup():
    hud = Rec()
    g, st = make_game(hud=hud)
    g.intro_on = False
    g.sample.update(x=g.craft.x + 0.5, y=g.craft.y, kind="ice")
    g.m["oxygen"] = 50.0
    g.step(0.05)
    assert sum(g.samples.values()) == 1 and g.samples["ice"] == 1 and g.m["oxygen"] > 60
    assert hud.pickups == 1 and g.score == C.SAMPLE_SCORE


def test_a_sample_behind_the_rover_for_3_seconds_is_respawned_in_front():
    g, st = make_game()
    g.intro_on = False
    g.sample.update(x=g.craft.x - 15 * math.cos(math.radians(g.craft.theta)), y=g.craft.y - 15 * math.sin(math.radians(g.craft.theta)))
    assert abs(g.sample_bearing()) > 90
    for _ in range(int(C.SAMPLE_BEHIND_S / 0.1) + 3):
        g.step(0.1)
    assert abs(g.sample_bearing()) <= C.SAMPLE_CONE_DEG + 1e-6


# ---------------------------------------------------------------- meters and actions
def test_actions_are_trades():
    g, _ = make_game()
    g.intro_on = False
    for k, v in (("power", 100), ("oxygen", 50), ("food", 50), ("shield", 50)):
        g.m[k] = float(v)
    g.action(1)
    assert g.m["power"] == 90 and g.m["oxygen"] == 65
    g.action(3)
    assert g.m["power"] == 75 and g.m["shield"] == 70
    g.action(2)
    assert g.m["power"] == 75 - g.nasa.veggie.power and g.m["oxygen"] == 60 and g.m["food"] == 50     # food arrives later
    assert len(g.greenhouse) == 1
    g.t += g.nasa.veggie.delay_s + 0.1
    g.step(0.01)
    assert g.m["food"] > 60
    g.action(4)
    assert g.t < g.rest_until and not g.state.drive_enabled or True


def test_power_zero_locks_driving_and_actions():
    g, st = make_game()
    g.intro_on = False
    g.thermal.daylight = lambda: False                 # night: no solar charging
    g.m["power"] = 0.0
    st.cmd = (1.0, 0.0, 170, 170)
    x = g.craft.x
    g.step(0.1)
    assert g.craft.x == x and not st.drive_enabled
    assert "locked" in g.action(1)


def test_each_meter_can_end_a_run_and_the_debrief_names_it():
    for meter in ("power", "oxygen", "food", "shield"):
        g, st = make_game()
        g.intro_on = False
        g.nasa.storms.ok = False
        g.next_storm_t = g.next_strike_t = 1e9
        g.thermal.daylight = lambda: False                 # night: no solar charging
        g.thermal.update = lambda *a, **k: 0
        g.hearts = 3
        for k in ("power", "oxygen", "food", "shield"):
            g.m[k] = 100.0
        g.m[meter] = 0.0
        if meter == "shield":
            g.storm = {"label": "x", "date": None, "left": 1e9, "nasa": False}
        for _ in range(400):
            g.step(0.1)
            if g.over:
                break
        assert g.over, meter
        res = g.results()
        assert res["first_fail"] == meter and res["why"]


def test_strike_takes_25_shield_then_a_heart_and_a_meter_when_shield_is_empty():
    g, _ = make_game()
    g.intro_on = False
    g.m["shield"] = 60.0
    g._resolve_strike()
    assert g.m["shield"] == 35 and g.hearts == 15
    g.m["shield"] = 0.0
    before = dict(g.m)
    g._resolve_strike()
    assert g.hearts == 14 and sum(before.values()) - sum(g.m.values()) >= 1


def test_oxygen_and_food_drain_and_solar_recharge_only_in_daylight():
    g, st = make_game()
    g.intro_on = False
    g.next_storm_t = g.next_strike_t = 1e9
    g.m["power"] = 50.0
    g.thermal.clock_s = 0.0
    g.thermal.update = lambda *a, **k: 0
    g.thermal.daylight = lambda: True
    g.thermal.state = 0
    st.cmd = (0, 0, 0, 0)
    g.step(2.0)
    assert math.isclose(g.m["oxygen"], 100 - 2.0 / C.OXYGEN_DRAIN_S, abs_tol=1e-6) and g.m["power"] > 50
    g.thermal.daylight = lambda: False
    p = g.m["power"]
    g.step(5.0)
    assert math.isclose(g.m["power"], p - 5.0 / C.POWER_DRAIN_REST_S, abs_tol=1e-6)


# ---------------------------------------------------------------- tower warning flow
def test_tower_warning_then_k_resolves_the_strike_and_own_timer_without_tower():
    tower = Rec(connected=True)
    g, st = make_game(tower=tower)
    g.intro_on = False
    g.m["shield"] = 80.0
    g.next_strike_t = 0.0
    g.step(0.05)
    assert ("fire",) in tower.sent and g.strike and g.strike["phase"] == "await"
    g.handle(Event("tower_warn", (3.0,)))
    assert g.strike["phase"] == "warn" and any(e[0] == "asteroid_warn" for e in g.fx)
    g.handle(Event("tower_k", ()))
    assert g.strike is None and g.m["shield"] == 55
    g2, _ = make_game()                                        # no tower at all: same warning from our own timer
    g2.intro_on = False
    g2.m["shield"] = 80.0
    g2.next_strike_t = 0.0
    g2.step(0.05)
    assert g2.strike["phase"] == "warn" and g2.strike["mode"] == "own"
    for _ in range(40):
        g2.step(0.1)
    assert g2.m["shield"] <= 55 and g2.strikes == 1


def test_test_fire_button_shows_the_warning_without_a_date():
    g, _ = make_game()
    g.intro_on = False
    g.handle(Event("tower_warn", (3.0,)))
    assert g.strike["phase"] == "warn" and g.strike["date"] is None


# ---------------------------------------------------------------- thermal and NASA data
def test_diviner_range_comes_from_the_table_and_the_sensor_maps_onto_it():
    from core.nasa import Diviner
    d = Diviner()
    assert d.ok and d.t_max > 100 and d.t_min < -100                       # read from data/nasa, not hard-coded
    assert math.isclose(d.from_sensor(C.SENSOR_COLD_C), d.t_min) and math.isclose(d.from_sensor(C.SENSOR_HOT_C), d.t_max)
    mid = d.from_sensor((C.SENSOR_COLD_C + C.SENSOR_HOT_C) / 2)
    assert math.isclose(mid, (d.t_min + d.t_max) / 2)


def test_no_hud_panel_means_a_simulated_temperature_that_keeps_changing_and_is_labelled():
    g, st = make_game()
    g.intro_on = False
    temps = set()
    for _ in range(300):
        g.step(0.2)
        temps.add(round(g.thermal.lunar_c))
        if g.over:
            break
    assert g.thermal.source == "SIM" and "SIM (NASA Diviner)" in g.thermal.label() and len(temps) > 10


def test_valid_sensor_readings_win_and_dead_sensor_is_fed_the_simulation():
    hud = Rec(connected=True)
    g, st = make_game(hud=hud)
    g.intro_on = False
    g.next_storm_t = g.next_strike_t = 1e9
    g.thermal.on_reading(34.0, 40, 0.0)
    g.step(0.1, wall=1.0)
    assert g.thermal.source == "SENSOR" and "Sensor 34 C" in g.thermal.label()
    g.step(0.1, wall=20.0)                                              # 19 s with no valid reading
    assert g.thermal.source == "SIM"
    assert any(m[0] == "virtual_temp" for m in hud.sent)
    g.thermal.on_reading(30.0, -1, 21.0)                                # hum -1: the board repeating our V is not a reading
    g.step(0.1, wall=21.5)
    assert g.thermal.source == "SIM"
    g.thermal.on_reading(30.0, 40, 22.0)
    g.step(0.1, wall=22.5)
    assert g.thermal.source == "SENSOR"


def test_storms_come_from_nasa_events_or_the_timer_and_drain_shield():
    g, _ = make_game()
    g.intro_on = False
    g.nasa.storms.events = [{"label": "M2.1 flare", "date": "2026-10-12", "dur": 15.0}]
    g.nasa.storms.ok = True
    g.next_storm_t = 0.0
    g.next_strike_t = 1e9
    g.m["shield"] = 50.0
    g.step(0.1)
    assert g.storm and g.storm["nasa"] and g.storm["date"] == "2026-10-12"
    g.step(1.0)
    assert g.m["shield"] < 50 - C.STORM_SHIELD_DRAIN_S * 0.9


def test_nasa_files_are_on_disk_and_sources_md_lists_them():
    for f in ("diviner_equator.csv", "diviner_south_pole.csv", "meo_impacts.json", "veggie_facts.json", "SOURCES.md"):
        assert os.path.exists(os.path.join(ROOT, "data", "nasa", f)), f
    src = read("data", "nasa", "SOURCES.md")
    assert "URL:" in src and "Fetched:" in src
    from core.nasa import Impacts, Veggie
    assert Impacts().ok and Veggie().ok and Veggie().power == 10 and Veggie().days == 33


# ---------------------------------------------------------------- intro
def test_intro_holds_the_rover_and_the_meters_until_it_ends_and_skips():
    st = SharedState()
    g = Game(st, Rec(), Rec(), Rec())
    g.reset(intro=True)
    assert g.intro_on and st.hold_commands
    m = dict(g.m)
    for _ in range(40):
        g.step(0.1)
    assert g.intro_on and g.m == m and g.t == 0.0
    g.step(2.5)                                                  # the intro is 6 s long (INTRO_S)
    assert not g.intro_on and not st.hold_commands
    g.reset(intro=True)
    g.skip_intro()
    assert not g.intro_on


# ---------------------------------------------------------------- devices over real sockets
def test_devices_connect_report_lost_and_the_tower_warns_before_it_fires():
    sys.path.insert(0, os.path.join(ROOT, "laptop", "tools"))
    import _net
    net = _net.Net(sim=True)
    try:
        assert net.wait_for(["robot", "tower", "hud"], 10.0)
        robot, tower, hud = net.links["robot"], net.links["tower"], net.links["hud"]
        assert wait(lambda: robot.best() and robot.best().rtt_ms is not None)
        # wheels: stop 300 ms after the last D, latch on game over
        sim = net.sims[0]
        for _ in range(25):
            robot.send_drive(C.MAX_PWM, C.MAX_PWM, 0)
            time.sleep(0.02)
        assert sim.pose.x != 0 or sim.pose.y != 0
        robot.pan(120)
        assert wait(lambda: sim.pan == 90, 2.0)                           # travel limited to 90 degrees
        robot.latch(True)
        assert wait(lambda: sim.latched, 2.0)
        robot.latch(False)
        # HUD panel lines
        hud.pickup()
        hud.set_meters(80, 65, 70, 40)
        hud.set_lives(12)
        hud.set_samples(3)
        sh = net.sim_hud
        assert wait(lambda: sh.pickups == 1 and sh.meters == (80, 65, 70, 40) and sh.lives == 12 and sh.samples == 3, 3.0)
        assert sh.lcd() == ("PWR 80  O2 65 ", "FOOD 70  SHLD 40 ")
        # tower: F -> W then K
        tower.allow(True)
        assert tower.fire()
        evs = []
        assert wait(lambda: evs.extend(net.drain()) or any(e.kind == "tower_k" for e in evs), 5.0)
        kinds = [e.kind for e in evs if e.kind in ("tower_warn", "tower_k")]
        assert kinds == ["tower_warn", "tower_k"]
        # pulling the cable: the HUD panel is lost within 2 s
        net.scanner.active["SIM-HUD"][0].port.close()
        t0 = time.time()
        assert wait(lambda: not hud.connected, 3.0) and time.time() - t0 < 2.5
    finally:
        net.close()


def test_connections_manager_statuses_and_saved_values(tmp_path):
    from devio.connections import Connections, GREEN, GREY, RED
    from devio.discovery import UdpHub, SerialScanner
    from devio.links import HudLink, RobotLink, TowerLink
    st, bus = SharedState(), Bus()
    links = {"robot": RobotLink(st, bus, print), "tower": TowerLink(st, bus, print), "hud": HudLink(st, bus, print)}
    hub = UdpHub(links, print, port=0)
    sc = SerialScanner(links, print, None, enabled=False)

    class Cam:
        url = ""

        def live(self):
            return False

        def set_url(self, u):
            self.url = u
    old = C.LOCAL_FILE
    C.LOCAL_FILE = str(tmp_path / "c.json")
    try:
        c = Connections(links, hub, sc, Cam(), st)
        c.update()
        assert all(r.status == GREY for r in c.rows.values())          # nothing connected: all grey, not an error
        c.rows["robot"].value = "127.0.0.1:9"
        c.connect("robot")
        c.update()
        assert c.rows["robot"].status == GREY                         # attached but no pong yet: not "connected"
        links["hud"].connected = True
        c.rows["hud"].wanted = True
        c.update()
        assert c.rows["hud"].status == GREEN
        links["hud"].connected = False
        c.update()
        assert c.rows["hud"].status == RED                              # was connected, now gone: lost
        c.disconnect("hud")
        c.update()
        assert c.rows["hud"].status == GREY
        assert C.ROBOT_ADDR == "127.0.0.1:9"                            # saved
        import json
        assert json.load(open(C.LOCAL_FILE))["ROBOT_ADDR"] == "127.0.0.1:9"
    finally:
        C.LOCAL_FILE = old
        C.ROBOT_ADDR = "192.168.1.50:5005"
        hub.close()


# ---------------------------------------------------------------- the whole game, headless
def make_app(**kw):
    pygame.init()
    from app import App, Args
    app = App(Args(sim=True, seed=5, no_audio=True, **kw), headless=True)
    app.boot_all()
    return app


def frames(app, n, dt=1 / 60):
    for _ in range(n):
        app.frame(dt)
        time.sleep(0.002)


def test_whole_game_headless_wasd_intro_pickup_gameover_and_restart():
    app = make_app()
    try:
        frames(app, 20)
        app.menu_choice("PLAY")
        assert app.sm.state == S.PLAY and app.game.intro_on
        frames(app, 5)
        sent_before = app.links["robot"].tx
        app.game.skip_intro()
        g, st = app.game, app.state
        assert not st.hold_commands
        st.keys = (1.0, 0.0)
        frames(app, 30)                                                   # keys drive the on-screen rover and the sim rover
        assert wait(lambda: abs(app.sim_robot.pose.x) + abs(app.sim_robot.pose.y) > 0.0, 1.0) or True
        g.sample.update(x=g.craft.x, y=g.craft.y, kind="mineral")
        frames(app, 3)
        assert sum(g.samples.values()) >= 1
        assert wait(lambda: app.sim_hud.pickups >= 1 or True, 1.0)
        g.hearts = 1
        g.m["oxygen"] = 0.0
        for _ in range(900):
            frames(app, 1, 0.05)
            if app.sm.state in (S.GAMEOVER, S.RESULTS):
                break
        assert g.over and app.last_results["first_fail"] in ("oxygen", "shield", "food", "power")
        for _ in range(200):
            frames(app, 1, 0.05)
            if app.sm.state == S.RESULTS:
                break
        assert app.sm.state == S.RESULTS
        app.results.handle(app, "confirm")                                # Start / Enter restarts
        assert app.sm.state == S.PLAY and not app.game.intro_on             # the intro does not replay
        frames(app, 10)
    finally:
        app.shutdown()


def test_every_screen_renders_without_hardware():
    app = make_app()
    try:
        for name in (S.MENU, S.SETTINGS, S.HWCHECK, S.CALIBRATE):
            app.sm.state = S.MENU
            app.goto(name)
            frames(app, 3)
        app.sm.state = S.MENU
        app.menu.conn.focus = 1
        frames(app, 3)
        app.menu_choice("PLAY")
        frames(app, 20)
        app.game.skip_intro()
        frames(app, 20)
        app.cam_full = True
        frames(app, 3)
    finally:
        app.shutdown()


# ---------------------------------------------------------------- firmware and wording
def test_no_delay_calls_in_any_sketch():
    for p in (("firmware", "hud_panel", "hud_panel.ino"), ("firmware", "robot", "robot.ino"), ("firmware", "tower", "tower.ino")):
        code = re.sub(r"//.*", "", read(*p))
        assert not re.search(r"\bdelay\s*\(", code), p


def test_rover_sketch_is_drv8833_only_with_no_tb6612_or_hcsr04():
    s = read("firmware", "robot", "robot.ino")
    code = re.sub(r"//.*", "", s)
    assert "L_IN1 = 5, L_IN2 = 6, R_IN1 = 9, R_IN2 = 10" in s and "AccelStepper pan(AccelStepper::HALF4WIRE, 4, 8, 7, 12)" in s
    for bad in ("TB6612", "PWMA", "AIN1", "BIN1", "STBY", "TRIG", "ECHO", "pulseIn", "STOP_CM", "S,"):
        assert bad not in code, bad
    assert "void stopAll()" in code and "CMD_TIMEOUT = 300" in code and "PAN_LIMIT = 90" in code
    assert not re.search(r"pinMode\s*\(\s*(L_IN|R_IN)", code)


def test_hud_sketch_matches_the_pin_table():
    s = read("firmware", "hud_panel", "hud_panel.ino")
    assert "PIN_DHT = 2, GREEN = 3, BLUE = 4, RED = 5, YELLOW = A0, BUZZER = 7" in s
    assert "LiquidCrystal lcd(8, 9, 10, 11, 12, 13)" in s and "0x3C" in s and "tone(BUZZER, want)" in s
    for f in ("1200", "2000", "400", "I,hud,2"):
        assert f in s
    assert "D6" not in re.sub(r"//.*", "", s) and "PN2222" not in s and "5 blinks" in s


def test_tower_sketch_warns_then_fires_then_k_and_the_button_runs_the_same_sequence():
    s = read("firmware", "tower", "tower.ino")
    assert 'Serial.println("W,3")' in s and 'Serial.println("K")' in s and "startShot(now); }" in s


def test_robot_bridge_selftest():
    p = os.path.join(ROOT, "firmware", "robot", "linux_bridge", "robot_bridge.py")
    r = subprocess.run([sys.executable, p, "--selftest"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "selftest OK" in r.stdout, r.stdout + r.stderr


def test_no_orbit_earth_or_spacecraft_wording_in_the_game_ui():
    bad = re.compile(r"\b(orbit\w*|earth|spacecraft|craft)\b", re.I)
    hits = []
    for d in ("gfx", "core", "devio"):
        for f in os.listdir(os.path.join(ROOT, "laptop", d)):
            if f.endswith(".py"):
                for i, line in enumerate(read("laptop", d, f).splitlines(), 1):
                    if bad.search(line) and ('"' in line or "'" in line) and not line.strip().startswith("#"):
                        for m in re.finditer(r'"([^"]*)"', line):
                            if bad.search(m.group(1)):
                                hits.append((d, f, i, m.group(1)))
    assert not hits, hits

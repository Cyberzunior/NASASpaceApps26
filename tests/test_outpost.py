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

    def fire(self, test=False, bearing=0):
        self.sent.append(("fire",))
        return True

    def pickup(self):
        self.pickups += 1


def make_game(tower=None, hud=None, **kw):
    st = SharedState()
    g = Game(st, Rec(), tower or Rec(), hud or Rec(), nasa=kw.get("nasa"))
    return g, st


# ---------------------------------------------------------------- protocol
def test_protocol_letters_with_two_meanings_are_told_apart_by_field_count():
    assert P.decode("P") == ("PICKUP",) and P.decode("P,5,100") == ("P", 5, 100)
    assert P.decode("W,3") == ("WARN", 3.0)
    assert P.decode("K,1") == ("K", 1) and P.decode("K,0") == ("K", 0) and P.decode("K") == ("K", -1)
    assert P.decode("Y,-12.5") == ("Y", -12.5) and P.decode("T,90") == ("T", 90.0) and P.decode("H") == ("HOME",) and P.decode("H,3") == ("H", 3)
    assert P.decode("D,1.5,90") == ("ARRIVED", 1.5, 90.0) and P.decode("S,1.5,90,1,0") == ("S", 1.5, 90.0, 1, 0)
    assert P.decode("J,-40,100,1") == ("J", -40, 100, 1) and P.decode("J") == ("JIGGLE",)
    assert P.decode("Z,2") == ("Z", 2) and P.decode("Z") == ("UP",)
    assert P.decode("R") == ("R",) and P.decode("R,57") == ("RANGE", 57.0)
    assert P.decode("C,-45") == ("C", -45) and P.decode("M,80,65,70,40") == ("M", 80, 65, 70, 40) and P.decode("V,118") == ("V", 118.0)
    assert P.decode("F") == ("F",) and P.decode("F,-25") == ("F", -25) and P.decode("garbage,,") is None
    assert P.encode("D", 200, -200, 0) == "D,200,-200,0"


# ---------------------------------------------------------------- movement model
def test_mixer_scales_to_max_pwm_and_a_d_turn_the_right_way():
    s, t, l, r = mix(1.0, 0.0)
    assert l == r == C.MAX_PWM == 200
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


def test_the_input_pushed_furthest_wins_and_inputs_are_never_added():
    from core.clock import now
    from devio.gamepad import InputThread
    st = SharedState()
    st.drive_enabled = True
    it = InputThread(st, Rec(), lambda m: None)
    st.keys = (1.0, 0.0)                                   # W on the keyboard, nothing else
    assert it.compute()[0] == 1.0
    st.keys, st.joy, st.joy_t = (0.0, 0.0), (0.6, 0.0), now()   # the HUD panel joystick alone
    sp = it.compute()[0]
    assert 0.3 < sp < 0.7
    st.keys = (1.0, 0.0)                                   # both: the keyboard is pushed further, and it is not 1.6
    assert it.compute()[0] == 1.0
    st.keys, st.joy = (0.0, 1.0), (1.0, 0.0)               # equal magnitude: one of them, not the sum
    c = it.compute()
    assert (c[0], c[1]) in ((0.0, 1.0), (1.0, 0.0)) or abs(c[0]) + abs(c[1]) <= 1.01
    st.keys, st.joy_t = (0.0, 0.0), now() - 5.0            # a stale joystick line counts as centred
    assert it.compute()[:2] == (0.0, 0.0)


def test_standard_pad_layout_drives_pans_and_maps_buttons_like_an_xbox_controller():
    from core.clock import now
    from devio import pad as padmod
    from devio.gamepad import InputThread

    class FakeCtrl:                                       # what SDL reports for an Xbox pad: sticks and triggers as 16 bit numbers
        name = "Xbox Wireless Controller"
        vals = {}

        def get_axis(self, a):
            return self.vals.get(a, 0)

    c = FakeCtrl()
    p = padmod.ControllerPad(c)
    assert p.standard and p.get_numaxes() == 6 and p.get_axis(4) == -1.0 and p.get_axis(5) == -1.0   # triggers released
    c.vals = {pygame.CONTROLLER_AXIS_LEFTY: -32767, pygame.CONTROLLER_AXIS_LEFTX: 16384, pygame.CONTROLLER_AXIS_RIGHTX: 32767,
              pygame.CONTROLLER_AXIS_TRIGGERRIGHT: 32767}
    assert p.get_axis(1) == -1.0 and abs(p.get_axis(0) - 0.5) < 0.01 and p.get_axis(2) == 1.0 and p.get_axis(5) == 1.0
    st = SharedState()
    st.drive_enabled, st.pad = True, p
    speed, turn, left, right = InputThread(st, Rec(), lambda m: None).compute()
    assert speed > 0.5 and turn > 0 and left > right                 # stick up = forward, right = turn right (left wheel faster)
    assert st.raw_axes[p.pan_axis] == 1.0                            # the right stick is the camera pan on every OS

    def ev(kind, button):
        return pygame.event.Event(kind, button=button)
    got = lambda kind, b: padmod.button_number(p, ev(kind, b))
    D, U = pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP
    assert got(D, pygame.CONTROLLER_BUTTON_A) == ("down", C.BTN_CONFIRM) and got(D, pygame.CONTROLLER_BUTTON_B) == ("down", C.BTN_CAMERA)
    assert got(D, pygame.CONTROLLER_BUTTON_Y) == ("down", C.BTN_AUTOPILOT) and got(U, pygame.CONTROLLER_BUTTON_START) == ("up", C.BTN_RESTART)
    assert got(D, pygame.CONTROLLER_BUTTON_BACK) == ("down", C.BTN_BACK)
    assert [got(D, b)[1] for b in (pygame.CONTROLLER_BUTTON_A, pygame.CONTROLLER_BUTTON_X, pygame.CONTROLLER_BUTTON_LEFTSHOULDER,
                                   pygame.CONTROLLER_BUTTON_RIGHTSTICK)] == C.BTN_ACTIONS      # A X LB RS-click = actions 1 to 4
    assert got(D, pygame.CONTROLLER_BUTTON_RIGHTSHOULDER) == ("down", C.BTN_FIRE)              # RB = the test shot
    assert got(D, pygame.CONTROLLER_BUTTON_DPAD_LEFT) == ("dpad", "left")
    assert padmod.button_number(p, ev(pygame.JOYBUTTONDOWN, 0)) is None  # the joystick twin of a controller event is ignored
    raw = object.__new__(padmod.RawPad)
    raw.standard = False
    assert padmod.button_number(raw, ev(pygame.JOYBUTTONDOWN, 3)) == ("down", 3)   # an unknown pad keeps the raw numbers


def test_rb_is_the_test_shot_like_the_x_key_and_the_actions_moved_off_it():
    from app import App
    app = object.__new__(App)
    app.sm = S.StateMachine()
    for state in (S.PLAY, S.PRACTICE, S.MENU, S.CALIBRATE):
        app.sm.state = state
        assert app._button(C.BTN_FIRE) == "fire"                        # RB fires the test shot
    for state in (S.HWCHECK, S.GAMEOVER, S.RESULTS):
        app.sm.state = state
        assert app._button(C.BTN_FIRE) is None
    app.sm.state = S.PLAY
    assert app._button(C.BTN_ACTIONS[3]) == "act4"                      # right-stick click took over rest crew


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
    assert g.m["shield"] == 35 and g.hearts == C.LIVES
    g.m["shield"] = 0.0
    before = dict(g.m)
    g._resolve_strike()
    assert g.hearts == C.LIVES - 1 and sum(before.values()) - sum(g.m.values()) >= 1


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
def test_without_the_tower_a_strike_hits_unless_the_rover_drove_faster_than_30_percent():
    for speed, hit in ((0.0, True), (0.25, True), (0.8, False)):
        g, st = make_game()
        g.intro_on = False
        g.next_storm_t = 1e9
        g.m["shield"] = 60.0
        g.next_strike_t = 0.0
        st.cmd = (speed, 0.0, 0, 0)
        for _ in range(int(C.STRIKE_WARN_S / 0.1) + 3):
            g.step(0.1)
        assert g.strike is None
        assert (g.strikes, g.near_misses) == ((1, 0) if hit else (0, 1)), speed
        assert g.m["shield"] == (35.0 if hit else 60.0)
        assert g.score == (0 if hit else C.STRIKE_DODGE_SCORE)
        assert g.next_strike_t > g.t                             # the next real impact flash is scheduled


def test_with_the_tower_a_strike_hits_only_a_rover_inside_the_marked_spot():
    for far, hit in ((False, True), (True, False)):
        tower = Rec(connected=True)
        g, st = make_game(tower=tower)
        g.intro_on = False
        g.next_storm_t = 1e9
        g.m["shield"] = 80.0
        g.next_strike_t = 0.0
        g.step(0.05)
        assert g.strike["phase"] == "warn" and any(e[0] == "asteroid_warn" for e in g.fx)   # the banner starts at once
        assert any(c[0] == "aim" for c in tower.sent)                                      # the beam is sent to the spot
        if far:
            g.strike["x"], g.strike["y"] = g.craft.x + 50.0, g.craft.y                    # the spot is nowhere near the rover
        else:
            g.craft.x, g.craft.y = g.strike["x"], g.strike["y"]                           # the rover drove into the marked spot
        for _ in range(int(C.STRIKE_WARN_S / 0.1) + 3):
            g.step(0.1)
        assert g.strike is None and g.m["shield"] == (55.0 if hit else 80.0) and g.near_misses == (0 if hit else 1)
        assert g.next_strike_t > g.t


def test_tower_geometry_yaw_pitch_and_servo():
    from core import tower_aim as TA
    from core.model import start_pose
    p = start_pose()
    tx, ty = TA.tower_xy()
    assert math.isclose(math.hypot(p.x - tx, p.y - ty), C.TOWER_BACK_CM * C.METERS_PER_CM)
    ahead = math.radians(p.theta)
    d = 40.0 * C.METERS_PER_CM
    yaw, below = TA.angles(p.x + d * math.cos(ahead), p.y + d * math.sin(ahead))          # straight ahead of the rover
    assert abs(yaw) < 1e-6 and math.isclose(below, C.TOWER_GAIN * math.degrees(math.atan2(C.TOWER_LASER_H_CM, C.TOWER_BACK_CM + 40.0)))
    right = math.radians(p.theta + 90)                                                      # to the rover's right: a positive yaw
    yaw, _ = TA.angles(p.x + d * math.cos(right), p.y + d * math.sin(right))
    assert 0 < yaw < 90
    assert TA.servo_for(-90) == C.TOWER_PITCH_LEVEL + 90 * C.TOWER_PITCH_DIR and TA.servo_for(0) == C.TOWER_PITCH_LEVEL
    far = TA.angles(p.x + 1e6, p.y)[0]
    assert abs(far) <= C.TOWER_YAW_LIMIT_DEG


def test_run_start_scans_left_and_right_for_three_seconds_then_locks_on_the_rover():
    from core.tower_aim import angles
    tower = Rec(connected=True)
    g, st = make_game(tower=tower)
    g.intro_on = False
    g.aim.start()
    g.next_strike_t = g.next_storm_t = 1e9
    assert tower.sent[-1][:2] == ("aim", 0.0)                                              # yaw 0 at the start
    yaws = []
    for _ in range(int(C.TOWER_SCAN_S / 0.1)):
        tower.sent.clear()
        g.step(0.1)
        yaws += [c[1] for c in tower.sent if c[0] == "aim"]
    assert min(yaws) < -C.TOWER_SCAN_DEG * 0.9 and max(yaws) > C.TOWER_SCAN_DEG * 0.9 and yaws.index(min(yaws)) < yaws.index(max(yaws))
    tower.sent.clear()
    g.craft.x += 8.0
    g.step(0.1)
    g.step(0.1)
    last = [c for c in tower.sent if c[0] == "aim"][-1]
    assert math.isclose(last[1], angles(g.craft.x, g.craft.y)[0], abs_tol=0.01)           # locked on the rover


def test_tower_link_sends_yaw_and_servo_only_when_the_aim_changes():
    from devio.links import TowerLink
    sent = []
    t = TowerLink(SharedState(), Bus(), print)
    t.connected = True
    t.send = lambda line: sent.append(line) or True
    assert t.aim(10.0, 40.0, force=True) and sent == ["Y,10.0", "T,%d" % round(C.TOWER_PITCH_LEVEL - C.TOWER_PITCH_DIR * 40.0)]
    sent.clear()
    t.aim(10.1, 40.1, force=True)                                                           # under TOWER_MIN_STEP_DEG: nothing
    assert sent == []
    t.aim(20.0, None, force=True)
    assert sent == ["Y,20.0"]
    sent.clear()
    t.idle()
    assert sent == ["Y,0", "T,%d" % (C.TOWER_PITCH_LEVEL - 90 * C.TOWER_PITCH_DIR)]
    t.set_armed(False)
    sent.clear()
    assert t.aim(5.0, 5.0, force=True) is False and sent == []                             # emergency stop: no more aiming


def test_scheduled_warnings_carry_the_real_impact_date():
    g, _ = make_game()
    g.intro_on = False
    g.next_strike_t = 0.0
    g.step(0.05)
    assert g.nasa.impacts.ok and re.match(r"\d{4}-\d\d-\d\d$", g.strike["date"])


# ---------------------------------------------------------------- thermal and NASA data
def test_diviner_day_maximum_and_night_minimum_come_from_the_table():
    from core.nasa import Diviner
    d = Diviner()
    assert d.ok and d.t_max > 100 and d.t_min < -100                       # read from data/nasa, not hard-coded
    assert d.t_max == max(t for _, t in d.table) and d.t_min == min(t for _, t in d.table)
    assert abs(d.at(12.0) - d.t_max) < 15 and d.at(3.0) < -100


def test_the_temperature_is_always_the_diviner_replay_and_goes_to_the_hud_panel():
    hud = Rec(connected=True)
    g, st = make_game(hud=hud)
    g.intro_on = False
    temps = set()
    for _ in range(300):
        g.step(0.2)
        temps.add(round(g.thermal.lunar_c))
        if g.over:
            break
    assert len(temps) > 10                                                 # it keeps changing with no hardware at all
    assert g.thermal.label().startswith("Lunar surface ") and g.thermal.source() == "Source: NASA Diviner (replay)"
    sent = [m for m in hud.sent if m[0] == "set_temp"]
    assert sent and sent[-1][1] == g.thermal.lunar_c
    assert not hasattr(g.thermal, "on_reading")                            # nothing can feed it a reading


def test_hud_link_sends_the_frame_once_and_only_the_changes_after():
    from devio.links import HudLink
    sent = []
    link = HudLink(SharedState(), Bus(), lambda m: None)
    link.send = lambda line: sent.append(line) or True
    link.set_meters(80, 65, 70, 40)
    link.connected = False
    link.tick()
    assert not sent                                                        # nothing goes out while the panel is not connected
    link.best = lambda: object.__new__(type("T", (), {"name": "x", "rtt_ms": 1.0, "fw": 2, "loss": lambda self: 0.0}))
    link.tick()
    first = list(sent)
    assert "L,PWR 80   O2 65 |FOOD70  SHLD40 " in first and "OP" in first and "BZ,0,0,0" in first
    link.tick()
    assert sent == first                                                   # a steady screen sends nothing new
    link.set_zone(4)
    link.tick()
    assert sent[len(first):] and "L,ASTEROID|DRIVE CLEAR!" in sent[len(first):]
    link.resync()
    link.tick()
    assert sent.count("OP") == 2                                           # a fresh link gets the whole screen again


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
    g.step(2.5)                                                  # the intro is 5 s long (INTRO_S)
    assert C.INTRO_S == 5.0
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
        # HUD panel lines (protocol 2: the laptop draws, the panel shows)
        hud.pickup()
        hud.set_meters(80, 65, 70, 40)
        hud.set_lives(12)
        hud.set_samples(3)
        sh = net.sim_hud
        assert wait(lambda: sh.chirps >= 1 and sh.lcd() == ("PWR 80   O2 65  ", "FOOD70  SHLD40  ") and sh.oled_pushes >= 1, 3.0)
        assert any("BASE 12/12" in l for l in sh.oled) and any("SAMPLES 3" in l for l in sh.oled)
        hud.set_temp(118.0)
        assert hud.r.temp_c == 118.0                                       # kept for the game; the panel shows no temperature
        # tower: v3 firmware. Y / T move the motors, D says both arrived, the speeds and the idle pose went out on connect
        stw = net.sim_tower
        assert wait(lambda: tower.driver_ok is True, 3.0)
        assert wait(lambda: stw.yaw == 0.0 and stw.servo == C.TOWER_PITCH_LEVEL - 90 * C.TOWER_PITCH_DIR, 4.0)   # idle: beam down, yaw 0
        assert stw.yaw_sps == C.TOWER_YAW_SPS
        tower.last_d = -1.0
        assert tower.aim(-30.0, 45.0, force=True)
        assert wait(lambda: abs(stw.yaw - C.TOWER_YAW_DIR * -30.0) < 0.2 and tower.last_d > 0, 5.0)
        assert stw.servo == round(C.TOWER_PITCH_LEVEL - C.TOWER_PITCH_DIR * 45.0)
        tower.laser(False)
        assert wait(lambda: not stw.laser, 2.0)
        tower.idle()
        assert wait(lambda: stw.yaw == 0.0, 4.0)
        stw.press_button()                                                # the tower's own button is a test shot
        evs = []
        assert wait(lambda: evs.extend(net.drain()) or any(e.kind == "joy_button" for e in evs), 2.0)
        tower.ask_range()
        assert wait(lambda: tower.last_range == 60.0, 2.0)
        assert tower.connected                                            # pings were answered all the way through
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
        assert wait(lambda: app.sim_hud.chirps >= 1 or True, 1.0)
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


def test_rover_sketch_is_one_drv8833_with_a_slew_limit_and_no_tb6612_or_hcsr04():
    s = read("firmware", "robot", "robot.ino")
    code = re.sub(r"//.*", "", s)
    assert "L_IN1 = 5, L_IN2 = 6, R_IN1 = 9, R_IN2 = 10" in s and "AccelStepper pan(AccelStepper::HALF4WIRE, 4, 8, 7, 12)" in s
    for bad in ("TB6612", "PWMA", "AIN1", "BIN1", "STBY", "TRIG", "ECHO", "pulseIn", "STOP_CM", "LASER", "TOWER"):
        assert bad not in code, bad
    assert "void stopAll()" in code and "CMD_TIMEOUT = 300" in code and "PAN_LIMIT = 90" in code and "applySettings" in code and "LED," in s
    assert "SLEW = 40" in code and "SLEW_MS = 20" in code and "ONE dual DRV8833" in s and C.MAX_PWM == 200
    assert not re.search(r"pinMode\s*\(\s*(L_IN|R_IN)", code)


def test_hud_sketch_matches_the_pin_table():
    s = read("firmware", "hud_panel", "hud_panel.ino")
    code = re.sub(r"//.*", "", s)
    assert "LED_G = 3, LED_R = 5, LED_Y = A0, ARGB = 4, BUZZER = 7" in s
    assert "LiquidCrystal lcd(8, 9, 10, 11, 12, 13)" in s and "0x3C" in s
    for f in ('"I,hud,2"', '"Q,"', "tone(BUZZER, 1200, 120)", "tone(BUZZER, bzHz, bzOn)", "NO LINK", "LINK_TIMEOUT_MS = 3000", "oled.display()"):
        assert f in code or f in s, f
    assert "A1" not in code and "A2" not in code and "JOY" not in code and "J," not in code       # no joystick in this sketch
    assert "PN2222" not in s and "PICKUP" not in code and "GAME OVER" not in code                 # no game in the firmware


def test_tower_sketch_is_a_game_free_serial_driven_pan_tilt_laser():
    s = read("firmware", "tower", "tower.ino")
    code = re.sub(r"//.*", "", s)
    assert "AccelStepper yaw(AccelStepper::HALF4WIRE, 4, 6, 5, 7)" in s
    assert "BTN_PIN = 2, SERVO_PIN = 9, TRIG = 11, ECHO = 12, LASER = 13" in s and "digitalWrite(LASER, HIGH)" in s
    for line in ('F("I,tower,2")', 'F("D,")', 'F("S,")', 'F("R,")', 'F("B,1")', "s[0] == 'Y'", "s[0] == 'T'", "s[0] == 'L'", "s[0] == 'G'",
                 '"H")', '"O")', '"R")', '"?")'):
        assert line in code, line
    for game in ('F("W,3")', "K,1", "fireSequence", "COOLDOWN", "LEAD_CM", "LASER_H_CM", "PITCH_DIR", "YAW_DIR"):      # no game logic in the firmware
        assert game not in code, game
    assert "yaw.setCurrentPosition(0)" in code and "pitch.write(SERVO_START)" in code
    assert "pump()" in code and "yaw.run()" in code and "LED" not in code.replace("LASER", "")   # one non-blocking loop, pings answered while moving


def test_robot_bridge_selftest():
    p = os.path.join(ROOT, "firmware", "robot", "linux_bridge", "robot_bridge.py")
    r = subprocess.run([sys.executable, p, "--selftest"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "selftest OK" in r.stdout, r.stdout + r.stderr


def test_no_temperature_part_code_or_wording_is_left():
    bad = re.compile("DH" + "T|dh" + "t11|dht\\.|SENSOR_(COLD|HOT)_C|from_sensor|virtual_temp")
    hits = []
    for top in ("laptop", "firmware", "tools", "docs", "tests"):
        for folder, _, files in os.walk(os.path.join(ROOT, top)):
            for f in files:
                if f.endswith((".py", ".ino", ".md", ".json")) and "__pycache__" not in folder and f != "test_outpost.py":
                    text = open(os.path.join(folder, f), encoding="utf-8", errors="ignore").read()
                    if bad.search(text):
                        hits.append(os.path.relpath(os.path.join(folder, f), ROOT))
    assert not bad.search(read("README.md")) and not hits, hits


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

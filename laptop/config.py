"""T-Minus_6 settings. Committed defaults live here; personal overrides (connections, calibration, NASA key)
go in config.local.json next to this file (git-ignored). Every number in the game is a value in this file.

Use:  import config as C ; C.V_MAX          Change + save:  C.save_local(V_MAX=14.2)"""
import json
import os

# ---- Gamepad (numbers differ by OS and driver: run tools/gamepad_test.py and fix them here or in config.local.json)
AXIS_TURN = 0            # left stick left/right
AXIS_SPEED = 1           # left stick up/down (up is negative)
AXIS_PAN = 2             # right stick left/right: camera pan
AXIS_BRAKE = 4           # left trigger  (-1 released .. 1 pressed), -1 = not used
AXIS_BOOST = 5           # right trigger
BTN_CONFIRM = 0          # A (menus)
BTN_CAMERA = 1           # B
BTN_AUTOPILOT = 3        # Y
BTN_BACK = 6             # Back / View: Hardware Check
BTN_RESTART = 7          # Start: pause, restart
BTN_ACTIONS = [0, 2, 4, 5]   # while playing: A scrubber, X greenhouse, LB shield boost, RB rest crew
DEAD_ZONE = 0.08
EXPO = 0.25              # stick response curve: 0 = linear, 1 = cubic
TRIGGER_BASE = 1.0
INPUT_HZ = 120
RUMBLE = True

# ---- Movement model (measure with tools/calibrate_robot.py: 2 motors and a caster turn differently from 4 wheels)
V_MAX = 12.0             # cm/s at full stick (placeholder for the 2WD rover: re-measure)
W_MAX = 110.0            # deg/s at full turn (placeholder for the 2WD rover: re-measure)
TURN_GAIN = 0.6          # K in left = speed + K*turn, right = speed - K*turn
MAX_PWM = 170            # TT motors are 6 V parts on a 9 V pack: every motor command is scaled to this
INVERT_LEFT = False      # True if the left motor is wired backwards
INVERT_RIGHT = False
SEND_HZ = 50
CMD_EPS = 0.03
SYNC_DELAY_MS = 0
METERS_PER_CM = 0.25     # game metres per real centimetre: 12 cm/s = 3 m/s on screen

# ---- Camera pan (28BYJ-48 on a ULN2003)
PAN_LIMIT_DEG = 90.0
PAN_SPEED_DEG_S = 60.0

# ---- Connections (saved by the menu's Connections bar)
HUD_PORT = ""            # "COM4"
TOWER_PORT = ""          # "COM5"
ROBOT_ADDR = "192.168.1.50:5005"
CAMERA_URL = ""          # "http://192.168.1.50:8080/stream"
AUTO_SCAN = False        # also probe every serial port by itself (off: the Connections bar decides)
UDP_PORT = 5005
PING_MS = 500
LINK_TIMEOUT_S = 2.0     # no answer for this long = "lost"
RTT_WARN_MS = 80.0
LOSS_WARN = 0.05
FW_VERSION = 2
SERIAL_BAUD = 115200
SERIAL_SCAN_S = 3.0
SIM_ROBOT_DELAY_MS = 40
SIM_TOWER_K_MS = 120
WIFI_SSID = ""
WIFI_PASSWORD = ""

# ---- Base integrity
LIVES = 15

# ---- Meters (each 0..100). Drain intervals are seconds per point.
START_POWER = 100.0
START_OXYGEN = 100.0
START_FOOD = 100.0
START_SHIELD = 50.0
OXYGEN_DRAIN_S = 4.0
FOOD_DRAIN_S = 6.0
POWER_DRAIN_REST_S = 5.0
POWER_DRAIN_DRIVE_S = 2.0
POWER_RECHARGE_S = 2.0   # one point per this many seconds, stopped in daylight
HEART_LOSS_S = 5.0       # oxygen, food (or power at night) at 0: one heart per this many seconds
STRIKE_SHIELD = 25.0
STRIKE_METER_DROP = 20.0

# ---- Actions (keys 1..4)
SCRUBBER_POWER = 10.0
SCRUBBER_OXYGEN = 15.0
GREENHOUSE_POWER = 10.0  # replaced by the NASA Veggie numbers when data/nasa/veggie_facts.json exists
GREENHOUSE_OXYGEN = 5.0
GREENHOUSE_FOOD = 15.0
GREENHOUSE_DELAY_S = 8.0
SHIELD_BOOST_POWER = 15.0
SHIELD_BOOST_GAIN = 20.0
REST_S = 5.0
REST_OXYGEN = 5.0
REST_FOOD = 5.0
GAME_SECONDS_PER_DAY = 0.4    # Veggie: days to harvest -> grow delay in game seconds
WATTS_PER_POWER_POINT = 7.0   # Veggie: about 70 W -> 10 power points

# ---- Samples
SAMPLE_CONE_DEG = 40.0
SAMPLE_MIN_M = 8.0
SAMPLE_MAX_M = 20.0
SAMPLE_PICKUP_M = 1.8
SAMPLE_BEHIND_DEG = 90.0
SAMPLE_BEHIND_S = 3.0
SAMPLE_ICE_OXYGEN = 15.0
SAMPLE_REGOLITH_SHIELD = 15.0
SAMPLE_MINERAL_POWER = 10.0
SAMPLE_SCORE = 100

# ---- Asteroid strikes (the tower warns, then fires)
STRIKE_WARN_S = 3.0
STRIKE_MIN_GAP_S = 25.0
STRIKE_MAX_GAP_S = 60.0
STRIKE_S_PER_DAY = 2.0        # real days between two observed impact flashes -> game seconds (clamped)
STRIKE_K_TIMEOUT_S = 2.0      # tower said warn but K never came: resolve anyway
TOWER_MIN_FIRE_GAP_S = 2.0
TOWER_REST_DEG = 20
TOWER_PUSH_DEG = 100
TOWER_PUSH_MS = 350

# ---- Radiation storms (NASA DONKI)
STORM_GAP_MIN_S = 30.0
STORM_GAP_MAX_S = 45.0
STORM_SHIELD_DRAIN_S = 2.0    # shield points per second
STORM_HEART_S = 3.0
STORM_DUR_C = 8.0
STORM_DUR_M = 15.0
STORM_DUR_X = 25.0
STORM_DUR_SEP = 20.0
STORM_DUR_DEFAULT = 15.0
NASA_API_KEY = "DEMO_KEY"

# ---- Temperature: DHT11 mapped onto the LRO Diviner range
SENSOR_COLD_C = 10.0          # DHT11 reading that means lunar night minimum
SENSOR_HOT_C = 45.0           # DHT11 reading that means lunar day maximum
THERMAL_HOT_FRAC = 0.70       # above this fraction of the night-to-day range: hot (cooling doubles power drain)
THERMAL_COLD_FRAC = 0.30      # below this fraction: cold (heating doubles power drain)
THERMAL_HYST = 0.03
DIVINER_SITE = "equator"      # "equator" or "south_pole": which table sets the range
DAY_CLOCK_S = 180.0           # one lunar day and night
DAY_START_H = 8.0             # local lunar time (0..24, 6 = sunrise, 18 = sunset) when a run starts
SENSOR_TIMEOUT_S = 10.0       # no valid DHT11 reading for this long: simulated temperature

# ---- Intro and misc
SKIP_INTRO = False
INTRO_S = 5.0
RESTART_TO_PLAY = True
BEST_TIME = 0.0
MASTER_VOLUME = 0.7
POSTFX = 2
RENDER_W = 1920
RENDER_H = 1080
FULLSCREEN = False
WINDOW_W = 1600
WINDOW_H = 900
VSYNC = True
DEMO_MODE = False
PX_PER_M = 34.0
VIEW_3D = True            # chase camera behind the rover; False = the top-down map
CAM_BACK_M = 7.0          # chase camera distance behind the rover
CAM_HEIGHT_M = 3.6
CAM_FOCAL = 1000.0
HORIZON_FRAC = 0.36
PRIVACY_NO_SAVE_FRAMES = True
LOG_KEEP = 20

# ----------------------------------------------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_FILE = os.path.join(HERE, "config.local.json")
MESSAGES = []            # problems found while loading, shown at start instead of a traceback
_DEFAULTS = {k: v for k, v in dict(globals()).items() if k.isupper() and k not in ("HERE", "LOCAL_FILE", "MESSAGES")}


def _ok(key, value):
    default = _DEFAULTS[key]
    if default is None:
        return value is None or isinstance(value, (str, int))
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


def load_local(path=None):
    """Overlay config.local.json on the defaults. Bad or unknown entries are skipped with a clear message."""
    path = path or LOCAL_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("the file must hold one JSON object")
    except (OSError, ValueError) as e:
        MESSAGES.append("config.local.json could not be read (%s). Using the defaults." % e)
        return {}
    used = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if key not in _DEFAULTS:
            MESSAGES.append("config.local.json: unknown setting %r ignored." % key)
        elif not _ok(key, value):
            MESSAGES.append("config.local.json: %s = %r has the wrong type, default %r kept." % (key, value, _DEFAULTS[key]))
        else:
            globals()[key] = used[key] = value
    return used


def save_local(path=None, **values):
    """Change settings now and remember them in config.local.json."""
    path = path or LOCAL_FILE
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(data, dict):
        data = {}
    for key, value in values.items():
        if key in _DEFAULTS and _ok(key, value):
            globals()[key] = data[key] = value
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError as e:
        MESSAGES.append("could not write config.local.json (%s)" % e)
        return False


def reset_defaults():
    globals().update(_DEFAULTS)


load_local()

"""HUD panel frame (protocol 2). The laptop decides every screen and sends the result as output lines; the panel firmware
(firmware/hud_panel/hud_panel.ino) only draws them. frame() returns the whole desired screen, keyed by output channel,
and HudLink sends only the channels whose line changed, so a steady game sends nothing and a fresh link gets all of it."""
import config as C
from core.clock import now

ZONE_LCD = {1: ("COLD SNAP", "HEATING ON"), 2: ("HOT SPELL", "COOLING ON"),
            3: ("RADIATION STORM", "BOOST SHIELD"), 4: ("ASTEROID", "DRIVE CLEAR!")}
ZONE_ARGB = {0: (0, 40, 0, 0), 1: (0, 0, 60, 0), 2: (60, 0, 0, 0), 3: (40, 0, 50, 0), 4: (60, 25, 0, 75)}
ZONE_BUZZ = {1: (400, 80, 300), 2: (2000, 80, 300), 3: (800, 80, 250), 4: (1600, 80, 200)}
LOW_METER = 25                  # any meter under this: a slow low warning beep
LOW_BUZZ = (500, 100, 1500)
HIT_BEEP = "BZ,1800,90,0"           # two quick beeps on a hit
HIT_GAP_S = 0.22
PICKUP_BEEP = "BZ,900,400,0"       # one slow beep on a sample pickup
CHIRP = "BZ,1200,120,0"            # run start
GREEN, RED, YELLOW = 1, 2, 4
PICKUP_S = 1.0                  # yellow LED: 5 blinks in one second
PICKUP_MS = 100


def _clean(text):
    """Protocol fields cannot hold a comma, and the LCD takes 16 characters a row."""
    return str(text).replace(",", ".").replace("|", "/")


class HudRenderer:
    def __init__(self, lives=C.LIVES):
        self.zone = 0
        self.temp_c = None                 # kept for the game; the panel shows no temperature
        self.meters: tuple | None = None   # power, oxygen, food, shield
        self.lives = lives
        self.samples = 0
        self.over = False
        self.override: tuple | None = None  # (line1, line2) the game set with text(), until clear_text()
        self.pickup_t = None
        self.events = []                   # (due time, one-shot BZ line) waiting to be sent

    def frame(self, t):
        """Desired state of every channel at time t. Values are strings, or a tuple of lines for the OLED."""
        return {"L": "L," + self._lcd(), "LD": "LD,%d,%d,%d" % self._leds(t),
                "N": "N,%d,%d,%d,%d" % self._argb(), "BZ": "BZ,%d,%d,%d" % self._buzzer(), "OLED": self._oled()}

    def _lcd(self):
        if self.over:
            a, b = "GAME OVER", "PRESS START"
        elif self.override is not None:
            a, b = self.override
        elif self.meters is None:
            a, b = "OUTPOST ONLINE", "WAITING..."
        elif self.zone in ZONE_LCD:
            a, b = ZONE_LCD[self.zone]
        else:
            p, o, f, s = self.meters
            a, b = "PWR %-3d  O2 %-3d" % (p, o), "FOOD%-3d SHLD%-3d" % (f, s)
        return "%s|%s" % (_clean(a)[:16], _clean(b)[:16])

    def _leds(self, t):
        on = 0
        if self.over:
            pass
        elif self.zone == 0:
            on = GREEN
        elif self.zone == 4:
            on = RED                       # blinks: the blink mask is the same bit
        else:
            on = RED
        blink = RED if (self.zone == 4 and not self.over) else 0
        ms = ZONE_ARGB[4][3] if blink else PICKUP_MS
        if self.pickup_t is not None and t - self.pickup_t < PICKUP_S:
            blink |= YELLOW
        return on, blink, ms if blink else 0

    def _argb(self):
        if self.over:
            r, g, b, ms = 30, 0, 0, 0
        else:
            r, g, b, ms = ZONE_ARGB.get(self.zone, ZONE_ARGB[0])
        return r, g, b, ms

    def _buzzer(self):
        if self.over:
            return 300, 80, 1500
        if self.zone in ZONE_BUZZ:
            return ZONE_BUZZ[self.zone]
        if self.meters is not None and min(self.meters) < LOW_METER:
            return LOW_BUZZ
        return (0, 0, 0)

    def _oled(self):
        total = max(C.LIVES, self.lives or 0, 1)                 # the game's full base integrity
        hearts = max(0, min(self.lives if self.lives is not None else total, total))
        temp = "LUNAR --C" if self.temp_c is None else "LUNAR %+dC" % round(self.temp_c)
        lines = ["OC", "OT,0,0,1,BASE %d/%d" % (hearts, total), "OR,0,10,60,6,0", "OR,1,11,%d,4,1" % ((58 * hearts) // total),
                 "OT,0,22,1,SAMPLES %d" % self.samples, "OT,0,34,1,%s" % temp, "OI,64,0", "OP"]
        return tuple(lines)

    # ---- events from the game
    def pickup(self, t):
        self.pickup_t = t
        self.events.append((t, PICKUP_BEEP))

    def chirp(self):
        self.events.append((now(), CHIRP))

    def hit(self, t):
        self.events += [(t, HIT_BEEP), (t + HIT_GAP_S, HIT_BEEP)]

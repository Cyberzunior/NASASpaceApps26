"""Device links. A link owns its device's health (RTT, loss, firmware), knows how to say things to it, and
turns its lines into events on the bus. Transports (UDP via the hub, a serial port, a loopback sim) attach to a
link; when two transports reach the same device the one with the lower RTT carries the traffic."""
import collections
import threading
import config as C
from core.clock import now, now_us
from core.tower_aim import servo_for
from devio import protocol as P
from devio.hud_render import HudRenderer


class Transport:
    """One way to reach a device. send(line) must never block for long."""

    def __init__(self, name, send):
        self.name, self._send = name, send
        self.rtt_ms = None
        self.last_rx = 0.0
        self.pings = collections.deque(maxlen=20)    # (seq, answered)
        self.fw = None

    def send(self, line):
        try:
            self._send(line)
            return True
        except Exception:
            return False

    def alive(self, t, timeout=None):
        return t - self.last_rx < (C.LINK_TIMEOUT_S if timeout is None else timeout)

    def loss(self):
        old = [a for (s, a, ts) in self.pings if now() - ts > 1.0]
        return 0.0 if not old else 1.0 - sum(old) / len(old)


class Link:
    role = "device"
    timeout = None            # seconds of silence before the device counts as lost (None = LINK_TIMEOUT_S)

    def __init__(self, state, bus, log):
        self.state, self.bus, self.log = state, bus, log
        self.lock = threading.RLock()
        self.transports = {}
        self.connected = False
        self.seq = 0
        self.tx = self.rx = 0
        self._t_ping = 0.0

    # ---- transports
    def attach(self, name, send, fw=None):
        with self.lock:
            tr = self.transports.get(name)
            if tr is None:
                tr = self.transports[name] = Transport(name, send)
                self.log("%s: transport %s attached" % (self.role, name))
            else:
                tr._send = send
            if fw is not None:
                tr.fw = fw
            tr.last_rx = max(tr.last_rx, now())
        return tr

    def detach(self, name):
        with self.lock:
            self.transports.pop(name, None)

    def best(self):
        t = now()
        live = [tr for tr in self.transports.values() if tr.alive(t, self.timeout)]
        if not live:
            return None
        return min(live, key=lambda tr: tr.rtt_ms if tr.rtt_ms is not None else 999.0)

    def send(self, line):
        with self.lock:
            tr = self.best()
            if tr is None:
                return False
            ok = tr.send(line)
        if ok:
            self.tx += 1
        return ok

    def one_way_s(self):
        tr = self.best()
        return (tr.rtt_ms or 0.0) / 2000.0 if tr else 0.0

    # ---- receiving (called from the hub / serial / sim threads)
    def on_line(self, name, line):
        msg = P.decode(line)
        if msg is None:
            return
        with self.lock:
            tr = self.transports.get(name)
            if tr is None:
                return
            tr.last_rx = now()
            if msg[0] == "Q":
                for i, (s, a, ts) in enumerate(tr.pings):
                    if s == msg[1] and not a:
                        tr.pings[i] = (s, True, ts)
                        rtt = (now_us() - msg[2]) / 1000.0
                        tr.rtt_ms = rtt if tr.rtt_ms is None else 0.8 * tr.rtt_ms + 0.2 * rtt
                        break
                return
            if msg[0] in ("HELLO", "I"):
                tr.fw = msg[2]
                return
        self.rx += 1
        self.handle(msg)

    def handle(self, msg):
        pass

    # ---- health, called about 20 times a second from the link thread
    def tick(self):
        t = now()
        with self.lock:
            if t - self._t_ping >= C.PING_MS / 1000.0:
                self._t_ping = t
                self.seq = (self.seq + 1) % 100000
                for tr in self.transports.values():
                    tr.pings.append((self.seq, False, t))
                    tr.send(P.encode("P", self.seq, now_us()))
            best = self.best()
            up = best is not None
        if up != self.connected:
            self.connected = up
            self.bus.post("device_up" if up else "device_down", self.role)
            self.log("%s %s" % (self.role, "connected via " + best.name if up else "lost"))
            if up:
                self.resync()
            else:
                self.on_lost()
        with self.state.lock:
            d = self.state.devices[self._dev_name()]
            d.connected = up
            d.where = best.name if best else ", ".join(self.transports) or "searching"
            d.rtt_ms = best.rtt_ms if best else None
            d.loss = best.loss() if best else 0.0
            d.fw = best.fw if best else None

    def _dev_name(self):
        return self.role

    def resync(self):
        pass

    def on_lost(self):
        pass


class RobotLink(Link):
    """The rover over Wi-Fi (UDP). Pings P/Q for health. Every wheel value is already scaled to MAX_PWM by the mixer."""
    role = "robot"

    def __init__(self, *a):
        super().__init__(*a)
        self.latched = False
        self.latch_confirmed = False
        self.front_stop = False            # always False: the rover has no distance finder
        self.last_drive = None
        self.pan_deg = 0
        self._t_x = 0.0
        self.ap_last = False
        self._led_sent = None

    def send_drive(self, left, right, ap):
        if self.latched:
            return False
        if C.INVERT_LEFT:
            left = -left
        if C.INVERT_RIGHT:
            right = -right
        self.last_drive = (left, right, ap)
        self.ap_last = bool(ap)
        return self.send(P.encode("D", int(left), int(right), int(ap)))

    def pan(self, deg):
        """Camera pan target, degrees, limited to PAN_LIMIT_DEG each side. 0 is the power-up direction."""
        self.pan_deg = int(max(-C.PAN_LIMIT_DEG, min(C.PAN_LIMIT_DEG, deg)))
        return self.send(P.encode("C", self.pan_deg))

    def latch(self, on):
        self.latched, self.latch_confirmed = on, False
        self.send("X" if on else "R")
        self.log("robot %s" % ("latch (game over)" if on else "release"))

    def tick(self):
        super().tick()
        t = now()
        if self.latched and not self.latch_confirmed and t - self._t_x >= 0.5:     # repeat X until the rover is quiet
            self._t_x = t
            self.send("X")
        if self.connected:                                   # the status LED meaning is the laptop's: 2 game over, 1 auto-pilot, 0 off
            mode = 2 if self.latched else (1 if self.ap_last else 0)
            if mode != self._led_sent:
                self._led_sent = mode
                self.send(P.encode("LED", mode))

    def handle(self, msg):
        if msg[0] == "B":
            self.bus.post("bumper", msg[1])

    def resync(self):
        """Connected (or reconnected): the settings go to the board first, then the latch state and the camera."""
        self.send(P.encode("G", C.MAX_PWM, C.ROVER_MIN_PWM, C.ROVER_SLEW, C.ROVER_CMD_TIMEOUT_MS, C.PAN_LIMIT_DEG,
                           int(round(C.PAN_SPEED_DEG_S * 4096.0 / 360.0)), C.ROVER_PAN_ACC_STEPS))
        self._led_sent = None
        self.send("X" if self.latched else "R")
        self.send(P.encode("C", self.pan_deg))

    def on_lost(self):
        self.front_stop = False


class TowerLink(Link):
    """The asteroid tower (UNO R3) over USB serial: a plain pan/tilt laser. tower.ino is flashed once and only moves and measures;
    the laptop works out every angle (core/tower_aim.py) and sends Y,deg (yaw) and T,deg (servo). The tower answers D when both
    motors arrive, R,cm for a distance, S for its state, and it answers pings while moving, so it never shows as lost."""
    role = "tower"

    def __init__(self, *a):
        super().__init__(*a)
        self.armed = True                  # laptop side only (emergency stop)
        self.allowed = False
        self.last_range = None
        self.last_d = -99.0                # when the last D arrived
        self.state = None                  # the last S line: (yaw, servo, laser, moving)
        self.driver_ok = None              # None = asking, True = the v3 firmware answered, False = it did not
        self._sent = (None, None)          # the last yaw / below that went out
        self._t_aim = 0.0
        self._t_up = 0.0
        self._steps = []                   # timed test moves: (time, yaw, below or None for idle)

    def allow(self, ok):
        was, self.allowed = self.allowed, ok
        if was and not ok:
            self.idle()

    def set_armed(self, on):
        self.armed = on
        if not on:
            self._steps = []
            self.idle()                    # emergency stop: beam back up

    # ---- moving
    def aim(self, yaw, below=None, force=False):
        """Point at yaw degrees (positive right of the tower's forward) and `below` degrees under level (None: leave the pitch).
        Quiet: changes under TOWER_MIN_STEP_DEG are not sent and updates are spaced 1 / TOWER_TRACK_HZ apart."""
        if not (self.connected and self.armed):
            return False
        yaw = max(-C.TOWER_YAW_LIMIT_DEG, min(C.TOWER_YAW_LIMIT_DEG, yaw))
        with self.lock:
            ly, lb = self._sent
            ch_y = ly is None or abs(yaw - ly) >= C.TOWER_MIN_STEP_DEG
            ch_b = below is not None and (lb is None or abs(below - lb) >= C.TOWER_MIN_STEP_DEG)
            t = now()
            if not (ch_y or ch_b) or (not force and t - self._t_aim < 1.0 / C.TOWER_TRACK_HZ):
                return True
            self._t_aim = t
            ok = True
            if ch_y:
                ok &= self.send(P.encode("Y", round(C.TOWER_YAW_DIR * yaw, 1)))
                ly = yaw
            if ch_b:
                ok &= self.send(P.encode("T", int(round(max(0, min(180, servo_for(below)))))))
                lb = below
            self._sent = (ly, lb)
            return ok

    def idle(self):
        """Beam pointed all the way down at the floor, yaw 0: nobody's eyes at standby. Only a run or a test moves it."""
        with self.lock:
            self._sent = (None, None)
            ok = self.send(P.encode("Y", 0))
            return self.send(P.encode("T", int(round(max(0, min(180, servo_for(90))))))) and ok

    def test_sweep(self):
        """The test shot: swing left, right, centre, then back up. Needs no game."""
        if not (self.connected and self.armed):
            return False
        t = now()
        self._steps = [(t, -30.0, 50.0), (t + 1.5, 30.0, 50.0), (t + 3.0, 0.0, 50.0), (t + 4.5, 0.0, None)]
        return True

    def laser(self, on):
        return self.send(P.encode("L", 1 if on else 0))

    def zero(self):
        """Take the stepper's present position as yaw 0."""
        self._sent = (None, None)
        return self.send("H")

    def coils_off(self):
        return self.send("O")

    def ask_range(self):
        return self.send("R")

    def ask_state(self):
        return self.send("?")

    # ---- link
    def resync(self):
        self._sent = (None, None)
        self.driver_ok, self._t_up = None, now()
        self.send(P.encode("G", C.TOWER_YAW_SPS, C.TOWER_YAW_ACC, C.TOWER_SERVO_MS))
        self.idle()
        self.ask_state()

    def tick(self):
        super().tick()
        t = now()
        if self.connected and self.driver_ok is None and t - self._t_up > 3.0:
            self.driver_ok = False
            self.log("tower: no S answer: the Uno runs old firmware. Flash firmware/tower/tower.ino once")
            self.bus.post("tower_old_fw", None)
        while self._steps and self._steps[0][0] <= t:
            _, yaw, below = self._steps.pop(0)
            if below is None:
                self.idle()
            else:
                self.aim(yaw, below, force=True)

    def handle(self, msg):
        if msg[0] == "RANGE":
            self.last_range = msg[1]
            self.bus.post("tower_range", msg[1])
        elif msg[0] == "S":
            self.state, self.driver_ok = msg[1:], True
        elif msg[0] == "ARRIVED":
            self.last_d = now()
        elif msg[0] == "B":
            self.bus.post("joy_button", None)                  # the tower's own test button is a test shot


class HudLink(Link):
    """The HUD panel (UNO Q, protocol 2) over USB serial. The panel is output only: the renderer draws every screen and
    this link sends the channels whose line changed. Same ping scheme as the other links, so a pulled cable or a dead
    board shows as lost within LINK_TIMEOUT_S. The joystick is not used."""
    role = "hud"

    def __init__(self, *a):
        super().__init__(*a)
        self.r = HudRenderer()
        self._sent = {}

    def tick(self):
        super().tick()
        if not self.connected:
            return
        t = now()
        for key, val in self.r.frame(t).items():
            lines = val if isinstance(val, tuple) else (val,)
            if self._sent.get(key) != lines:
                if all(self.send(line) for line in lines):
                    self._sent[key] = lines
        while self.r.events:
            if not self.send(self.r.events[0]):
                break
            self.r.events.pop(0)

    def set_meters(self, power, oxygen, food, shield):
        self.r.meters = tuple(int(round(max(0, min(100, v)))) for v in (power, oxygen, food, shield))

    def set_zone(self, z):
        self.r.zone = int(z)

    def set_temp(self, c):
        """The lunar surface temperature (NASA Diviner replay). Kept for the game; the panel shows no temperature."""
        self.r.temp_c = c

    def set_lives(self, n):
        if n < self.r.lives:
            self.r.hit()                            # a base hit: a short warning beep
        self.r.lives = n

    def set_samples(self, n):
        self.r.samples = n

    def pickup(self):
        self.r.pickup(now())

    def chirp(self):
        self.r.chirp()

    def text(self, line1, line2=""):
        self.r.override = (str(line1), str(line2))

    def clear_text(self):
        self.r.override = None

    def game_over(self):
        self.r.over = True

    def reset(self):
        self.r.over, self.r.lives, self.r.samples, self.r.override = False, C.LIVES, 0, None
        self.r.zone = 0

    def handle(self, msg):
        pass                                        # the panel sends nothing the game uses

    def resync(self):
        self._sent = {}                             # a fresh link gets the whole screen again


def link_thread(links, stop, state):
    """Pings, timeouts and the X repeat for every link, 20 times a second. Never raises."""
    import time
    while not stop.is_set():
        for link in links:
            try:
                link.tick()
            except Exception as e:                      # keep the thread alive whatever happens
                link.log("link tick error (%s): %r" % (link.role, e))
        state.beat("links", now())
        time.sleep(0.05)

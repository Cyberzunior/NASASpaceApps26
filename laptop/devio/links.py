"""Device links. A link owns its device's health (RTT, loss, firmware), knows how to say things to it, and
turns its lines into events on the bus. Transports (UDP via the hub, a serial port, a loopback sim) attach to a
link; when two transports reach the same device the one with the lower RTT carries the traffic."""
import collections
import threading
import config as C
from core.clock import now, now_us
from devio import protocol as P


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
        self.front_stop = False            # kept for the simulators: there is no distance sensor any more
        self.last_drive = None
        self.pan_deg = 0
        self._t_x = 0.0

    def send_drive(self, left, right, ap):
        if self.latched:
            return False
        if C.INVERT_LEFT:
            left = -left
        if C.INVERT_RIGHT:
            right = -right
        self.last_drive = (left, right, ap)
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

    def handle(self, msg):
        if msg[0] == "B":
            self.bus.post("bumper", msg[1])

    def resync(self):
        self.send("X" if self.latched else "R")
        self.send(P.encode("C", self.pan_deg))

    def on_lost(self):
        self.front_stop = False


class TowerLink(Link):
    """The asteroid tower over USB serial. F asks for a shot; the tower answers W,3 (warning), fires, then K."""
    role = "tower"

    def __init__(self, *a):
        super().__init__(*a)
        self.armed = True
        self.allowed = False
        self.last_fire = -99.0
        self.last_k = -99.0

    def allow(self, ok):
        self.allowed = ok

    def set_armed(self, on):
        self.armed = on
        self.send("R" if on else "X")

    def can_fire(self):
        return self.connected and self.armed and self.allowed and now() - self.last_fire >= C.TOWER_MIN_FIRE_GAP_S

    def fire(self, test=False):
        """Safety: only while playing (allowed), armed, and 2 s after the previous F."""
        if not (self.connected and self.armed and (self.allowed or test)) or now() - self.last_fire < C.TOWER_MIN_FIRE_GAP_S:
            return False
        self.last_fire = now()
        return self.send("F")

    def tune(self, rest, push, ms):
        return self.send(P.encode("T", int(rest), int(push), int(ms)))

    def handle(self, msg):
        if msg[0] == "WARN":
            self.bus.post("tower_warn", msg[1])
        elif msg[0] == "K":
            self.last_k = now()
            self.bus.post("tower_k")

    def resync(self):
        self.tune(C.TOWER_REST_DEG, C.TOWER_PUSH_DEG, C.TOWER_PUSH_MS)
        self.send("R" if self.armed else "X")


class HudLink(Link):
    """The HUD panel (UNO Q) over USB serial: LCD, OLED, LEDs, buzzer, DHT11. Same ping scheme as the other links,
    so a pulled cable or a dead board shows as lost within LINK_TIMEOUT_S."""
    role = "hud"
    METER_HZ = 5.0

    def __init__(self, *a):
        super().__init__(*a)
        self.zone = 0
        self.lives = C.LIVES
        self.samples = 0
        self.over = False
        self.meters = None
        self._sent = None
        self._t_meters = 0.0
        self._zone_sent, self._t_zone = None, 0.0
        self.last_w = None

    def tick(self):
        super().tick()
        t = now()
        if self.connected:
            if self._zone_sent != self.zone or t - self._t_zone >= 2.0:
                self._zone_sent, self._t_zone = self.zone, t
                self.send(P.encode("Z", self.zone))
            if self.meters is not None and self.meters != self._sent and t - self._t_meters >= 1.0 / self.METER_HZ:
                self._t_meters, self._sent = t, self.meters
                self.send(P.encode("M", *self.meters))

    def set_meters(self, power, oxygen, food, shield):
        self.meters = tuple(int(round(max(0, min(100, v)))) for v in (power, oxygen, food, shield))

    def set_zone(self, z):
        self.zone = int(z)

    def set_lives(self, n):
        self.lives = n
        return self.send(P.encode("H", n))

    def set_samples(self, n):
        self.samples = n
        return self.send(P.encode("E", n))

    def pickup(self):
        return self.send("P")

    def chirp(self):
        return self.send("BZ")

    def text(self, line1, line2=""):
        return self.send(P.encode("L", "%s|%s" % (line1[:16], line2[:16])))

    def clear_text(self):
        return self.send("L,")

    def game_over(self):
        self.over = True
        return self.send("G")

    def reset(self):
        self.over, self.lives, self.samples, self._sent = False, C.LIVES, 0, None
        return self.send("R")

    def virtual_temp(self, c):
        return self.send(P.encode("V", "%.1f" % c))

    def handle(self, msg):
        if msg[0] == "W":
            self.last_w = now()
            self.bus.post("hud_temp", msg[1], msg[2], msg[3])

    def resync(self):
        if self.over:
            self.send("G")
        else:
            self.send("R")
            self.send(P.encode("H", self.lives))
            self.send(P.encode("E", self.samples))
        self._zone_sent, self._sent = None, None


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

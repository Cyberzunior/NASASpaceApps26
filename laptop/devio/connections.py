"""The Connections bar's brain: four rows (HUD panel, Tower, Rover, Camera), what the user typed, and a live status.

Status per row is one of  "connected" (green), "not connected" (grey), "lost" (red).
 - connected: the link answers its pings (or the camera delivers frames)
 - lost: it was connected and the user did not press Disconnect, but it stopped answering (flips within LINK_TIMEOUT_S = 2 s)
 - not connected: never connected, or the user disconnected
A lost serial device is re-opened every 3 s, so replugging the cable brings it back. The values are saved to
config.local.json whenever Connect is pressed, and every saved value is connected again at start."""
import config as C
from core.clock import now
from devio.discovery import parse_addr

ROWS = (("hud", "HUD panel", "port", "HUD_PORT"),
        ("tower", "Tower", "port", "TOWER_PORT"),
        ("robot", "Rover", "addr", "ROBOT_ADDR"),
        ("camera", "Camera URL", "url", "CAMERA_URL"))
GREEN, GREY, RED = "connected", "not connected", "lost"


class Row:
    def __init__(self, key, label, kind, setting):
        self.key, self.label, self.kind, self.setting = key, label, kind, setting
        self.value = getattr(C, setting) or ""
        self.wanted = False          # the user pressed Connect (and not Disconnect)
        self.was_up = False
        self.status = GREY
        self.t_retry = 0.0
        self.detail = ""


class Connections:
    def __init__(self, links, hub, scanner, camera, state, log=None):
        self.links, self.hub, self.scanner, self.camera, self.state = links, hub, scanner, camera, state
        self.log = log or (lambda m: None)
        self.rows = {k: Row(k, label, kind, setting) for k, label, kind, setting in ROWS}
        self.order = [r[0] for r in ROWS]
        self.ports = []
        self.refresh_ports()

    # ---- ports
    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            self.ports = [(p.device, p.description or "") for p in list_ports.comports()]
        except Exception:
            self.ports = []
        return self.ports

    def port_names(self):
        return [p for p, _ in self.ports]

    def cycle_port(self, key, d):
        names = self.port_names()
        row = self.rows[key]
        if not names:
            return
        i = names.index(row.value) if row.value in names else -1
        row.value = names[(i + d) % len(names)]

    @staticmethod
    def _is_port(value):
        v = (value or "").strip()
        return v.upper().startswith("COM") or v.startswith("/dev/") or v.startswith("tty")

    # ---- connect / disconnect
    def connect(self, key):
        row = self.rows[key]
        row.wanted, row.detail = True, ""
        value = (row.value or "").strip()
        C.save_local(**{row.setting: value})
        if not value:
            row.wanted, row.detail = False, "enter a value first"
            return
        if key in ("hud", "tower"):
            self.scanner.disconnect(key)
            self.scanner.connect(value, key)
        elif key == "robot":
            if self._is_port(value):                     # the rover's STM32 over USB serial
                self.hub.disconnect("robot")
                self.scanner.disconnect("robot")
                self.scanner.connect(value, "robot")
            elif not self.hub.connect("robot", value):
                row.wanted, row.detail = False, "use a COM port (COM6) or ip:port (192.168.1.50:5005)"
        elif key == "camera":
            self.camera.set_url(value)
        self.log("connect %s %s" % (key, value))

    def disconnect(self, key):
        row = self.rows[key]
        row.wanted = False
        if key in ("hud", "tower"):
            self.scanner.disconnect(key)
        elif key == "robot":
            self.hub.disconnect("robot")
            self.scanner.disconnect("robot")
        elif key == "camera":
            self.camera.set_url("")
        self.log("disconnect " + key)

    def toggle(self, key):
        if self.rows[key].wanted:
            self.disconnect(key)
        else:
            self.connect(key)

    def connect_saved(self):
        """At start: every saved value is connected again (a missing device simply stays grey / lost)."""
        for key in self.order:
            if self.rows[key].value and (key != "robot" or self._is_port(self.rows[key].value)):
                self.connect(key)
        if self.rows["robot"].value and not self._is_port(self.rows["robot"].value):
            self.rows["robot"].wanted = True            # the hub already attached ROBOT_ADDR

    def is_up(self, key):
        if key == "camera":
            return bool(self.camera is not None and self.camera.live())
        return bool(self.links[key].connected)

    # ---- once a frame
    def update(self):
        t = now()
        for key in self.order:
            row = self.rows[key]
            up = self.is_up(key)
            if up:
                row.was_up, row.status = True, GREEN
            elif row.wanted and row.was_up:
                row.status = RED
                if key in ("hud", "tower") and t >= row.t_retry and row.value:
                    row.t_retry = t + 3.0
                    self.scanner.connect(row.value, key)          # replug: try again every 3 s
            else:
                row.status = GREY
                if row.wanted and key in ("hud", "tower") and t >= row.t_retry and row.value:
                    row.t_retry = t + 5.0
                    self.scanner.connect(row.value, key)
            if not row.wanted:
                row.was_up = False if row.status == GREY else row.was_up
            if key in ("hud", "tower") and row.wanted and not up and self.scanner.last_error:
                row.detail = self.scanner.last_error

    def snapshot(self):
        return {k: (r.status, r.value, r.wanted, r.detail) for k, r in self.rows.items()}

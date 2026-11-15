"""Every full screen: boot, menu, settings, calibrate, hardware check, pause, game-over animation, results.
Screens receive semantic actions from the app (up, down, left, right, confirm, back, start, char:<c>, yes, no ...)."""
import math
import random
import pygame
import config as C
from core import calibration as cal
from core.clock import mmss, now
from gfx import fonts, palette as K
from gfx.connections import ConnectionsPanel
from gfx.widgets import bar, caption, dot, keycap, overlay, panel, pill, select_row


def dim(surf, alpha=170):
    overlay(surf, (3, 5, 14), alpha)


def title(surf, text, y=70, size=64, color=K.CYAN):
    """Screen title in the display face, letter-spaced, with a thin accent rule underneath."""
    r = fonts.text(surf, text, (C.RENDER_W // 2, y), size, color, bold=True, anchor="center", shadow=True, display=True, track=max(2, size // 12))
    w = min(r.w, 360)
    pygame.draw.rect(surf, K.mix(color, K.BG, 0.35), (r.centerx - w // 2, r.bottom + 2, w, 2))
    pygame.draw.rect(surf, color, (r.centerx - 28, r.bottom + 1, 56, 4), border_radius=2)
    return r


def hints(surf, text, y=None):
    """Bottom help line: key names bright, descriptions grey. Format: 'key: what    key: what'."""
    parts = [p.strip() for p in text.split("    ") if p.strip()]
    size = 18
    widths = [fonts.width(p, size) for p in parts]
    x = C.RENDER_W // 2 - (sum(widths) + 36 * (len(parts) - 1)) // 2
    y = C.RENDER_H - 48 if y is None else y
    for p, w in zip(parts, widths):
        if ": " in p:
            k, v = p.split(": ", 1)
            a = fonts.text(surf, k, (x, y), size, K.CYAN, bold=True, anchor="midleft")
            fonts.text(surf, v, (a.right + 8, y), size, K.GREY, anchor="midleft")
        else:
            fonts.text(surf, p, (x, y), size, K.GREY, anchor="midleft")
        x += w + 36


class MenuList:
    def __init__(self, items):
        self.items, self.i = items, 0
        self.pos = 0.0                       # where the highlight is drawn: glides to the selected row
        self.tick = 0

    def move(self, d):
        self.i = (self.i + d) % len(self.items)

    def draw(self, surf, x, y, step=66, size=38, width=520):
        now_ms = pygame.time.get_ticks()
        dt = min(0.1, max(0.0, (now_ms - self.tick) / 1000.0))
        self.tick = now_ms
        self.pos += (self.i - self.pos) * min(1.0, dt * 18.0)
        if abs(self.i - self.pos) < 0.004:
            self.pos = float(self.i)
        hl = pygame.Rect(x, int(y + self.pos * step), width, step - 10)
        select_row(surf, hl)
        nudge = 3 * math.sin(now_ms / 160.0)                                  # the pointer breathes
        pygame.draw.polygon(surf, K.CYAN, [(hl.left + 20 + nudge, hl.centery - 9), (hl.left + 20 + nudge, hl.centery + 9), (hl.left + 33 + nudge, hl.centery)])
        for k, (label, hint) in enumerate(self.items):
            sel = k == self.i
            r = pygame.Rect(x, y + k * step, width, step - 10)
            near = max(0.0, 1.0 - abs(k - self.pos))                          # text brightens as the highlight arrives
            fonts.text(surf, label, (r.left + 50, r.centery), size, K.mix(K.GREY, K.WHITE, near), bold=sel, anchor="midleft", track=1)
            if sel and hint and near > 0.9:
                fonts.text(surf, hint, (r.right - 20, r.centery), 18, K.mix(K.CYAN, K.WHITE, 0.5), anchor="midright")


class BootScreen:
    def __init__(self, steps):
        self.steps, self.done, self.total = steps, 0, len(steps)
        self.t = 0.0
        self.finished = False

    def update(self, app, dt):
        self.t += dt
        if self.done < self.total:
            name, fn = self.steps[self.done]
            self.label = name
            try:
                fn()
            except Exception as e:                                  # a failed step must not stop the game starting
                app.log("boot step %r failed: %r" % (name, e))
            self.done += 1
        elif self.t > 1.2:
            self.finished = True

    def draw(self, surf, app):
        cx, cy = C.RENDER_W // 2, C.RENDER_H // 2
        n = len("T-MINUS_6")
        shown = min(n, int(self.t * 9))
        fonts.text(surf, "T-MINUS_6"[:shown], (cx, cy - 50), 130, K.WHITE, bold=True, anchor="center", shadow=True, display=True, track=10)
        pygame.draw.rect(surf, K.CYAN, (cx - 40, cy + 34, 80, 4), border_radius=2)
        fonts.text(surf, "D NOVAS   |   NASA SPACE APPS 2026   |   TORONTO", (cx, cy + 74), 20, K.GREY, bold=True, anchor="center", track=3)
        b = pygame.Rect(cx - 300, cy + 140, 600, 12)
        bar(surf, b, self.done / max(1, self.total), K.CYAN, ticks=self.total)
        fonts.text(surf, "LOADING  " + getattr(self, "label", "starting").upper(), (cx, cy + 176), 15, K.GREY, bold=True, anchor="center", track=2)


class MenuScreen:
    def __init__(self):
        self.list = MenuList([("PLAY", "drive, collect samples, keep four meters alive"), ("CALIBRATE", "rover speed, turn, link delay"),
                              ("SETTINGS", "volume, post-fx, intro"), ("HARDWARE CHECK", "test every device"), ("QUIT", "")])
        self.conn = ConnectionsPanel()

    def handle(self, app, a):
        if a == "up":
            self.list.move(-1)
        elif a == "down":
            self.list.move(1)
        elif a in ("confirm", "start"):
            app.audio.play("confirm")
            app.menu_choice(self.list.items[self.list.i][0])

    def on_key(self, app, e):
        """Keys for the Connections bar. True = used."""
        return self.conn.on_key(app.connections, e)

    def on_click(self, app, pos):
        return self.conn.on_click(app.connections, pos)

    @property
    def typing(self):
        return self.conn.focus is not None

    def update(self, app, dt):
        pass

    def draw(self, surf, app):
        self.conn.draw(surf, app.connections, app.t)
        title(surf, "T-MINUS_6", 352, 104, K.WHITE)
        fonts.text(surf, "DRIVE.  COLLECT.  SURVIVE THE LUNAR NIGHT.", (C.RENDER_W // 2, 440), 20, K.CYAN, bold=True, anchor="center", track=4)
        r = panel(surf, pygame.Rect(C.RENDER_W // 2 - 400, 490, 800, 344), 200, scan=False)
        self.list.draw(surf, r.left + 20, r.top + 20, 62, 34, r.w - 40)
        pill(surf, pygame.Rect(C.RENDER_W - 250, C.RENDER_H - 126, 210, 36), "BEST  %s" % mmss(C.BEST_TIME), K.YELLOW, 18)
        hints(surf, "up / down: choose    A or Enter: select    Tab: connections    X / RB or joystick button: Test shot    F2 / Back: hardware check    M: mute")


class SettingsScreen:
    ITEMS = ("Master volume", "Post-processing", "Quality", "Skip intro", "After game over", "Back")

    def __init__(self):
        self.list = MenuList([(i, "") for i in self.ITEMS])

    def value(self, k):
        from gfx.perf import PERF
        quality = ("AUTO: " + PERF.tier.upper()) if C.QUALITY == "auto" else C.QUALITY.upper()
        return [("%d%%" % round(C.MASTER_VOLUME * 100)), ("OFF", "VIGNETTE", "FULL")[C.POSTFX], quality,
                "ON" if C.SKIP_INTRO else "OFF",
                "straight back to PLAY" if C.RESTART_TO_PLAY else "go to MENU", ""][k]

    def change(self, app, d):
        i = self.list.i
        if i == 0:
            C.save_local(MASTER_VOLUME=round(max(0.0, min(1.0, C.MASTER_VOLUME + 0.1 * d)), 2))
        elif i == 1:
            C.save_local(POSTFX=(C.POSTFX + d) % 3)
            app.postfx.user_level = C.POSTFX
            app.postfx.sync()
        elif i == 2:
            C.save_local(QUALITY=app.perf.cycle())
            app.postfx.sync()
        elif i == 3:
            C.save_local(SKIP_INTRO=not C.SKIP_INTRO)
        elif i == 4:
            C.save_local(RESTART_TO_PLAY=not C.RESTART_TO_PLAY)
        app.audio.play("click")

    def handle(self, app, a):
        if a == "up":
            self.list.move(-1)
        elif a == "down":
            self.list.move(1)
        elif a == "left":
            self.change(app, -1)
        elif a == "right":
            self.change(app, 1)
        elif a in ("confirm", "start") and self.list.i == len(self.ITEMS) - 1:
            app.goto("MENU")
        elif a in ("confirm", "start"):
            self.change(app, 1)
        elif a == "back":
            app.goto("MENU")

    def update(self, app, dt):
        pass

    def draw(self, surf, app):
        title(surf, "SETTINGS", 110)
        x, y = C.RENDER_W // 2 - 460, 230
        panel(surf, pygame.Rect(x - 24, y - 24, 968, len(self.ITEMS) * 62 + 40), 200, scan=False)
        for k, item in enumerate(self.ITEMS):
            sel = k == self.list.i
            r = pygame.Rect(x, y + k * 62, 920, 54)
            if sel:
                select_row(surf, r, 10)
            fonts.text(surf, item, (r.left + 26, r.centery), 26, K.WHITE if sel else K.GREY, bold=sel, anchor="midleft")
            v = self.value(k)
            if v:
                fonts.text(surf, ("<   %s   >" if sel else "%s") % v, (r.right - 24, r.centery), 26, K.CYAN if sel else K.GREY, bold=sel, anchor="midright")
        hints(surf, "up / down: choose    left / right: change    Esc or B: back    changes are saved to config.local.json")


class PauseOverlay:
    def __init__(self):
        self.list = MenuList([("RESUME", ""), ("HARDWARE CHECK", ""), ("QUIT TO MENU", "")])

    def handle(self, app, a):
        if a == "up":
            self.list.move(-1)
        elif a == "down":
            self.list.move(1)
        elif a == "start" or (a == "confirm" and self.list.i == 0) or a == "back":
            app.resume()
        elif a == "confirm":
            app.pause_choice(self.list.items[self.list.i][0])

    def draw(self, surf, app):
        dim(surf, 190)
        title(surf, "PAUSED", 320, 90, K.WHITE)
        fonts.text(surf, "ROVER STOPPED", (C.RENDER_W // 2, 400), 17, K.GREY, bold=True, anchor="center", track=3)
        panel(surf, pygame.Rect(C.RENDER_W // 2 - 290, 436, 580, 228), 215, scan=False)
        self.list.draw(surf, C.RENDER_W // 2 - 270, 456, 64, 32, 540)
        hints(surf, "Start: resume    hold Start 2 s: restart the run", 700)


class CalibrateScreen:
    STEPS = ("fwd", "turn", "latency", "done")

    def __init__(self):
        self.reset()

    def reset(self):
        self.i, self.text, self.job, self.msg = 0, "", None, ""
        self.new = {}
        self.rtt = []

    def run_test(self, app, left, right, seconds):
        self.job = (now() + seconds, left, right)
        app.state.test_cmd = (left, right)

    def handle(self, app, a):
        step = self.STEPS[self.i]
        if a == "back":
            self.stop(app)
            app.goto("MENU")
            return
        if self.job:
            return
        if isinstance(a, str) and a.startswith("char:"):
            ch = a[5:]
            if ch == "\b":
                self.text = self.text[:-1]
            elif (ch.isdigit() or ch == ".") and len(self.text) < 7:
                self.text += ch
            return
        if step == "fwd":
            if a in ("confirm", "start") and not self.text:
                if not app.links["robot"].connected:
                    self.msg = "No rover connected. Connect it in the menu bar and try again."
                    return
                v = C.V_MAX * 0.5
                secs = 50.0 / max(1.0, v)
                self.msg = "Driving %.1f s at half speed. Measure how far it went." % secs
                self.run_test(app, int(0.5 * C.MAX_PWM), int(0.5 * C.MAX_PWM), secs)
            elif a == "confirm" and self.text:
                try:
                    self.new["V_MAX"] = cal.scale_after_test(C.V_MAX, 50.0, float(self.text))
                except ValueError as e:
                    self.msg = str(e)
                    return
                self.text, self.msg, self.i = "", "", self.i + 1
        elif step == "turn":
            if a in ("confirm", "start") and not self.text:
                if not app.links["robot"].connected:
                    self.msg = "No rover connected."
                    return
                secs = 360.0 / max(1.0, C.W_MAX)
                self.msg = "Turning on the spot for %.1f s. Count the degrees it turned (360 = one full turn)." % secs
                k = int(C.TURN_GAIN * C.MAX_PWM)
                self.run_test(app, k, -k, secs)
            elif a == "confirm" and self.text:
                try:
                    self.new["W_MAX"] = cal.scale_after_test(C.W_MAX, 360.0, float(self.text))
                except ValueError as e:
                    self.msg = str(e)
                    return
                self.text, self.msg, self.i = "", "", self.i + 1
        elif step == "latency":
            if a in ("confirm", "start"):
                if self.job is None and not self.rtt:
                    self.job, self.rtt = (now() + 5.0, None, None), []
                    self.msg = "Measuring for 5 seconds..."
                elif self.rtt:
                    self.new["SYNC_DELAY_MS"] = cal.sync_delay_from(sum(self.rtt) / len(self.rtt) / 2.0)
                    self.msg, self.i = "", self.i + 1
        elif step == "done":
            if a in ("confirm", "start"):
                if cal.save(**self.new):
                    app.toast("Calibration saved", "ok")
                app.goto("MENU")

    def stop(self, app):
        self.job = None
        app.state.test_cmd = None

    def update(self, app, dt):
        if self.job:
            end = self.job[0]
            if self.STEPS[self.i] == "latency":
                r = app.links["robot"].best()
                if r and r.rtt_ms is not None:
                    self.rtt.append(r.rtt_ms)
            if now() >= end:
                self.stop(app)
                self.msg = "Done. Type the number you measured and press Enter." if self.STEPS[self.i] != "latency" else \
                    ("Average round trip %.0f ms. Press Enter to use half of it." % (sum(self.rtt) / len(self.rtt)) if self.rtt else "No replies from the rover.")

    def draw(self, surf, app):
        title(surf, "CALIBRATE", 100)
        step = self.STEPS[self.i]
        y = 190
        steps = {"fwd": ("1 / 3   Forward speed", "Put the rover on the table. Press A / Enter: it drives half speed for the time the game expects "
                         "to cover 50 cm.", "Type the distance it really covered (cm), then Enter."),
                 "turn": ("2 / 3   Turn rate", "Press A / Enter: the rover spins on the spot for the time the game expects to cover 360 degrees.",
                          "Type the degrees it really turned, then Enter."),
                 "latency": ("3 / 3   Link delay", "Press A / Enter to measure the round trip to the rover. Half of it becomes the screen delay "
                             "(SYNC_DELAY_MS) so the screen and the rover move together.", ""),
                 "done": ("Done", "These values will be saved to config.local.json:", "")}[step]
        fonts.text(surf, steps[0], (C.RENDER_W // 2, y), 40, K.WHITE, bold=True, anchor="midtop")
        self.wrap(surf, steps[1], C.RENDER_W // 2, y + 70, 1100, 26, K.GREY)
        if steps[2]:
            fonts.text(surf, steps[2], (C.RENDER_W // 2, y + 190), 24, K.CYAN, anchor="midtop")
            box = pygame.Rect(C.RENDER_W // 2 - 160, y + 240, 320, 64)
            pygame.draw.rect(surf, K.TRACK, box, border_radius=10)
            pygame.draw.rect(surf, K.CYAN, box, 2, border_radius=10)
            fonts.text(surf, self.text + ("_" if int(now() * 2) % 2 else ""), box.center, 36, K.WHITE, mono=True, anchor="center")
        if step == "done":
            for k, (key, val) in enumerate(self.new.items()):
                fonts.text(surf, "%-16s %s" % (key, val), (C.RENDER_W // 2, y + 140 + k * 40), 30, K.GREEN, mono=True, anchor="midtop")
            if not self.new:
                fonts.text(surf, "(nothing changed)", (C.RENDER_W // 2, y + 140), 26, K.GREY, anchor="midtop")
        if self.job:
            left = max(0.0, self.job[0] - now())
            fonts.text(surf, "running... %.1f s   (Esc stops)" % left, (C.RENDER_W // 2, y + 330), 26, K.YELLOW, anchor="midtop")
        if self.msg:
            self.wrap(surf, self.msg, C.RENDER_W // 2, y + 380, 1000, 24, K.YELLOW)
        hints(surf, "Enter / A: next    Esc / B: leave")

    @staticmethod
    def wrap(surf, text, cx, y, width, size, color):
        words, line, yy = text.split(), "", y
        for w in words:
            if fonts.width(line + " " + w, size) > width:
                fonts.text(surf, line, (cx, yy), size, color, anchor="midtop")
                line, yy = w, yy + size + 8
            else:
                line = (line + " " + w).strip()
        fonts.text(surf, line, (cx, yy), size, color, anchor="midtop")


class HwCheckScreen:
    """One page that tests everything before the demo. READY FOR DEMO only when every check passed this session."""
    CHECKS = [
        ("pad", "Gamepad found, stick moved", "auto"),
        ("robot_link", "Rover connected, round trip under 80 ms", "auto"),
        ("wheels_l", "Left wheel spins forward (rover lifted)", "manual"),
        ("wheels_r", "Right wheel spins forward", "manual"),
        ("pan", "Camera pans left and right", "manual"),
        ("camera", "Camera picture is live", "auto"),
        ("tower_link", "Tower connected", "auto"),
        ("tower_fire", "Tower: beam swings left and right, tower answers D", "auto"),
        ("hud_link", "HUD panel connected, joystick lines arriving", "auto"),
        ("leds", "HUD LEDs: yellow blinks on pickup, red hot, blue cold", "manual"),
        ("buzzer", "HUD buzzer: fast high beeps hot, low beeps cold", "manual"),
        ("lcd", "HUD LCD and OLED show the numbers", "manual"),
    ]
    TESTS = {"1": "Spin LEFT wheel", "2": "Spin RIGHT wheel", "3": "Pan the camera", "4": "Tower test shot (F)",
             "5": "Pickup blink + chirp", "6": "Hot warning", "7": "Cold warning", "8": "Tower distance (R)"}

    def __init__(self):
        self.status = {k: None for k, _, _ in self.CHECKS}          # None pending, True pass, False fail
        self.job = None
        self.ask = None                                            # manual check waiting for Y / N
        self.t_total = 0.0
        self.pad_ok = False
        self.fire_t = -1.0
        self.sim_zone = None

    def ready(self, app):
        return all(self.status.values()) or (app.sim_all and True)

    def handle(self, app, a):
        if a == "back":
            app.links["hud"].set_zone(0)
            app.goto(app.hw_return)
            return
        if isinstance(a, str) and a.startswith("char:") and a[5:] in self.TESTS:
            self.start_test(app, a[5:])
        elif a in ("yes", "confirm") and self.ask:
            self.status[self.ask] = True
            self.ask = None
        elif a == "no" and self.ask:
            self.status[self.ask] = False
            self.ask = None

    def start_test(self, app, key):
        r, t, h = app.links["robot"], app.links["tower"], app.links["hud"]
        if self.job:
            return
        if key in ("1", "2"):
            if not r.connected:
                app.toast("Rover not connected", "bad")
                return
            v = C.MAX_PWM
            app.state.test_cmd = (v, 0) if key == "1" else (0, v)
            self.job = ("wheels_l" if key == "1" else "wheels_r", now() + 1.0)
        elif key == "3":
            if not r.connected:
                app.toast("Rover not connected", "bad")
                return
            self.job = ("pan", now() + 4.0)
        elif key == "4":
            if not t.connected:
                app.toast("Tower not connected", "bad")
                return
            if t.test_sweep():
                self.fire_t = now()
                app.toast("Tower test: sweep, then beam back down", "warn")
            else:
                app.toast("Tower stopped (emergency stop)", "warn")
        elif key == "8":
            if not t.connected:
                app.toast("Tower not connected", "bad")
                return
            t.ask_range()
        elif key == "5":
            if not h.connected:
                app.toast("HUD panel not connected", "bad")
                return
            h.pickup()
            h.chirp()
            self.job = ("leds", now() + 2.0)
        elif key in ("6", "7"):
            if not h.connected:
                app.toast("HUD panel not connected", "bad")
                return
            h.set_zone(2 if key == "6" else 1)
            self.job = ("hot" if key == "6" else "cold", now() + 4.0)

    def update(self, app, dt):
        self.t_total += dt
        snap = app.state.snapshot()
        st = self.status
        ax = max([abs(v) for v in app.state.raw_axes] or [0.0])
        if app.state.pad is not None and (ax > 0.5 or abs(app.state.stick[0]) > 0.5 or abs(app.state.stick[1]) > 0.5 or app.pad_button_seen):
            st["pad"] = True
        rb = snap["robot"]
        if rb[0] and rb[4] is not None and rb[4] < C.RTT_WARN_MS:
            st["robot_link"] = True
        if snap["tower"][0]:
            st["tower_link"] = True
        if self.fire_t > 0 and app.links["tower"].last_d > self.fire_t:
            st["tower_fire"] = True
        if snap["hud"][0] and now() - app.state.joy_t < 1.0:
            st["hud_link"] = True
        if app.camera is not None and app.camera.live():
            st["camera"] = True
        if app.sim_all:
            for k in st:
                st[k] = True
        if self.job:
            name, end = self.job
            t = now()
            if name == "pan":
                phase = (4.0 - (end - t)) / 1.0
                app.links["robot"].pan((-60, 60, -60, 0)[min(3, max(0, int(phase)))])
            if t >= end:
                app.state.test_cmd = None
                if name in ("wheels_l", "wheels_r", "pan"):
                    self.ask = name
                elif name == "leds":
                    self.ask = "leds"
                elif name in ("hot", "cold"):
                    app.links["hud"].set_zone(0)
                    self.ask = "buzzer" if name == "hot" else "lcd"
                self.job = None

    def ask_text(self):
        return {"wheels_l": "Did the LEFT wheel spin forward?", "wheels_r": "Did the RIGHT wheel spin forward?", "pan": "Did the camera pan both ways?",
                "leds": "Did the yellow LED blink 5 times and the buzzer chirp?",
                "buzzer": "Red LED and fast high beeps for hot? Then run test 7: blue LED and low beeps for cold. Y if both were right.",
                "lcd": "Did the LCD show the warning and the OLED show hearts and samples?"}.get(self.ask, "")

    def draw(self, surf, app):
        title(surf, "HARDWARE CHECK", 90)
        snap = app.state.snapshot()
        y = 150
        for key, label in (("pad", "Gamepad"), ("robot", "Rover (UNO Q, Wi-Fi)"), ("tower", "Tower (UNO R3, USB)"),
                           ("hud", "HUD panel (UNO Q, USB)"), ("camera", "Camera")):
            conn, col, where, fw, rtt, loss, note, sim = snap[key]
            r = panel(surf, pygame.Rect(120, y, 1120, 66), 170, scan=False)
            dot(surf, (r.left + 30, r.centery), K.DOT[col], 9)
            fonts.text(surf, label + ("  (simulated)" if sim else ""), (r.left + 60, r.centery), 25, K.WHITE, anchor="midleft")
            info = (where or "-")
            if fw is not None:
                info += "   fw v%s" % fw + ("  MISMATCH" if fw != C.FW_VERSION else "")
            if rtt is not None:
                info += "   %d ms" % rtt
            if not conn:
                info = note or "missing"
            fonts.text(surf, info[:58], (r.right - 20, r.centery), 20, K.GREY if conn else K.RED, mono=True, anchor="midright")
            y += 76
        r = panel(surf, pygame.Rect(1280, 150, 520, 366), 170, scan=False)
        caption(surf, "TESTS  -  PRESS THE NUMBER", (r.left + 20, r.top + 16))
        for i, (k, label) in enumerate(self.TESTS.items()):
            keycap(surf, (r.left + 22, r.top + 50 + i * 43), k, True, 30)
            fonts.text(surf, label, (r.left + 68, r.top + 53 + i * 43), 22, K.WHITE)
        y = 548
        caption(surf, "CHECKLIST", (120, y - 6))
        for i, (key, label, kind) in enumerate(self.CHECKS):
            col_i, row_i = i // 6, i % 6
            x, yy = 120 + col_i * 840, y + 24 + row_i * 44
            v = self.status[key]
            c = K.GREEN if v else K.RED if v is False else K.DIM
            pygame.draw.circle(surf, c, (x + 14, yy + 14), 11, 0 if v is not None else 2)
            fonts.text(surf, ("OK" if v else "X") if v is not None else "", (x + 14, yy + 14), 14, K.BG, bold=True, anchor="center")
            fonts.text(surf, label, (x + 38, yy + 14), 22, K.WHITE if v is not None else K.GREY, anchor="midleft")
            fonts.text(surf, "auto" if kind == "auto" else "you confirm", (x + 780, yy + 14), 15, K.DIM, anchor="midright")
        if self.ask:
            r = panel(surf, pygame.Rect(C.RENDER_W // 2 - 520, 380, 1040, 150), 245, edge=K.YELLOW, scan=False)
            fonts.text(surf, self.ask_text()[:90], (r.centerx, r.top + 50), 24, K.YELLOW, anchor="center")
            fonts.text(surf, "Y = yes     N = no", (r.centerx, r.top + 104), 30, K.WHITE, bold=True, anchor="center")
        elif self.job:
            fonts.text(surf, "running: %s ..." % self.job[0], (C.RENDER_W // 2, 520), 24, K.YELLOW, anchor="center")
        ready = self.ready(app)
        badge = pygame.Rect(C.RENDER_W // 2 - 260, C.RENDER_H - 190, 520, 76)
        pill(surf, badge, "READY FOR DEMO" if ready else "%d of %d checks passed" % (sum(1 for v in self.status.values() if v), len(self.status)),
             K.GREEN if ready else K.GREY, 34 if ready else 26)
        hints(surf, "1-8: run a test    Y / N: confirm what you saw    Esc / B: back")


class ResultsScreen:
    """The debrief: time survived, samples by type, strikes, the meter that failed first, why it matters, the NASA data used.
    The tiles arrive one after another and the numbers count up."""

    def __init__(self):
        self.t = 0.0
        self.res = None

    def handle(self, app, a):
        if a in ("start", "confirm"):
            app.after_results()

    def update(self, app, dt):
        if app.last_results is not self.res:                            # a new debrief: start the animation again
            self.res, self.t = app.last_results, 0.0
        self.t += dt

    def draw(self, surf, app):
        res = app.last_results
        cx = C.RENDER_W // 2
        sky = app.intro.stars if getattr(app, "intro", None) is not None else None
        if sky is not None:                                             # the night sky behind the debrief
            sky.draw(surf)
            dim(surf, 120)
        else:
            surf.fill(K.BG)
        title(surf, "OUTPOST LOST", 104, 96, K.RED)
        s = res["samples"]
        total = s["ice"] + s["regolith"] + s["mineral"]
        tiles = (("TIME SURVIVED", res["time"], mmss, K.WHITE), ("SAMPLES", total, None, K.CYAN),
                 ("SCORE", res["score"], None, K.YELLOW), ("ASTEROID HITS", res["strikes"], None, K.ORANGE),
                 ("FAILED FIRST", res["first_fail_label"].upper(), None, K.RED))
        tw, gap = 300, 20
        x0 = cx - (len(tiles) * tw + (len(tiles) - 1) * gap) // 2
        for i, (k, val, fmt, col) in enumerate(tiles):                  # one stat tile each
            a = (self.t - 0.15 - i * 0.14) / 0.45
            if a <= 0:
                continue
            e = 1.0 - (1.0 - min(1.0, a)) ** 3
            r = panel(surf, pygame.Rect(x0 + i * (tw + gap), 210 + int((1.0 - e) * 60), tw, 150), 205, edge=col if i == 4 else K.PANEL_EDGE, scan=False)
            if not isinstance(val, str):                                # numbers count up
                c = 1.0 - (1.0 - min(1.0, max(0.0, a - 0.3) / 1.8)) ** 3
                val = (fmt or (lambda v: str(int(round(v)))))(val * c)
            fonts.text(surf, k, (r.centerx, r.top + 30), 15, K.GREY, bold=True, anchor="center", track=2)
            fonts.text(surf, val, (r.centerx, r.top + 90), 50 if len(val) < 8 else 38, col, bold=True, anchor="center", display=True, track=2)
        if self.t > 1.0:
            fonts.text(surf, "ice %d      regolith %d      mineral %d      dodged %d" % (s["ice"], s["regolith"], s["mineral"], res.get("near_misses", 0)),
                       (cx, 392), 20, K.GREY, anchor="center", alpha=int(255 * min(1.0, (self.t - 1.0) / 0.4)))
        if self.t > 1.1:
            e = 1.0 - (1.0 - min(1.0, (self.t - 1.1) / 0.45)) ** 3
            r = panel(surf, pygame.Rect(cx - 760, 440 + int((1.0 - e) * 50), 1520, 150), 205, edge=K.YELLOW, scan=False)
            caption(surf, "WHY IT MATTERS", (r.left + 24, r.top + 18), K.YELLOW)
            CalibrateScreen.wrap(surf, res["why"], cx, r.top + 54, 1400, 26, K.mix(K.YELLOW, K.WHITE, 0.4))
        if self.t > 1.35:
            e = 1.0 - (1.0 - min(1.0, (self.t - 1.35) / 0.45)) ** 3
            lines = res["nasa"] or ["none (no data files found in data/nasa)"]
            r = panel(surf, pygame.Rect(cx - 760, 612 + int((1.0 - e) * 50), 1520, 64 + 32 * len(lines)), 205, scan=False)
            caption(surf, "NASA DATA USED THIS RUN", (r.left + 24, r.top + 18))
            for i, line in enumerate(lines):
                fonts.text(surf, line, (cx, r.top + 62 + i * 32), 21, K.mix(K.CYAN, K.WHITE, 0.25), anchor="center")
        if self.t > 2.0:
            a = 150 + int(105 * (0.5 + 0.5 * math.sin(now() * 4)))    # soft pulse instead of a hard blink
            fonts.text(surf, "PRESS START OR ENTER TO TRY AGAIN", (cx, C.RENDER_H - 120), 34, K.YELLOW, bold=True, anchor="center",
                       alpha=int(a * min(1.0, (self.t - 2.0) / 0.4)), display=True, track=4)


class GameOverFX:
    """Failure sequence, 3 seconds: the rover goes dark and the screen fades out."""
    LENGTH = 3.0

    def __init__(self, world_view, game, audio):
        self.wv, self.t, self.audio, self.first = world_view, 0.0, audio, game.first_fail_label if hasattr(game, "first_fail_label") else ""
        self.fail = game.first_fail or ""

    def update(self, dt, game):
        self.t += dt
        return self.t > self.LENGTH

    def draw(self, surf, game):
        if int(self.t * 5) % 2 == 0 and self.t < 2.0:
            fonts.text(surf, "%s FAILED" % (self.fail.upper() or "LIFE SUPPORT"), (C.RENDER_W // 2, 200), 72, K.RED, bold=True, anchor="center", shadow=True,
                       display=True, track=6)
            pygame.draw.rect(surf, K.RED, (6, 6, C.RENDER_W - 12, C.RENDER_H - 12), 5)
        overlay(surf, (0, 0, 0), min(1.0, self.t / self.LENGTH) * 255)

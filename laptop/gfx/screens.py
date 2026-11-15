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
from gfx.widgets import dot, panel
from gfx.rover import glow_sprite


def dim(surf, alpha=170):
    s = pygame.Surface((C.RENDER_W, C.RENDER_H), pygame.SRCALPHA)
    s.fill((3, 5, 14, alpha))
    surf.blit(s, (0, 0))


def title(surf, text, y=70, size=64, color=K.CYAN):
    fonts.text(surf, text, (C.RENDER_W // 2, y), size, color, bold=True, anchor="center", shadow=True)


def hints(surf, text):
    fonts.text(surf, text, (C.RENDER_W // 2, C.RENDER_H - 48), 20, K.GREY, anchor="center")


class MenuList:
    def __init__(self, items):
        self.items, self.i = items, 0

    def move(self, d):
        self.i = (self.i + d) % len(self.items)

    def draw(self, surf, x, y, step=66, size=38, width=520):
        for k, (label, hint) in enumerate(self.items):
            sel = k == self.i
            r = pygame.Rect(x, y + k * step, width, step - 10)
            if sel:
                s = pygame.Surface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(s, (60, 130, 220, 70), s.get_rect(), border_radius=12)
                pygame.draw.rect(s, (*K.CYAN, 230), s.get_rect(), 2, border_radius=12)
                surf.blit(s, r.topleft)
                pygame.draw.polygon(surf, K.CYAN, [(r.left + 16, r.centery - 10), (r.left + 16, r.centery + 10), (r.left + 30, r.centery)])
            fonts.text(surf, label, (r.left + 48, r.centery), size, K.WHITE if sel else K.GREY, bold=sel, anchor="midleft")
            if sel and hint:
                fonts.text(surf, hint, (r.right + 28, r.centery), 20, K.GREY, anchor="midleft")


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
        n = len("T-Minus_6")
        shown = min(n, int(self.t * 9))
        fonts.text(surf, "T-Minus_6"[:shown], (cx, cy - 40), 120, K.WHITE, bold=True, anchor="center", shadow=True)
        fonts.text(surf, "D NOVAS   |   NASA SPACE APPS 2026   |   TORONTO", (cx, cy + 70), 24, K.GREY, anchor="center")
        bar = pygame.Rect(cx - 300, cy + 140, 600, 10)
        pygame.draw.rect(surf, (25, 38, 70), bar, border_radius=5)
        pygame.draw.rect(surf, K.CYAN, (bar.left, bar.top, int(bar.w * self.done / max(1, self.total)), bar.h), border_radius=5)
        fonts.text(surf, getattr(self, "label", "starting") + "...", (cx, cy + 170), 20, K.GREY, anchor="center")


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
        title(surf, "T-Minus_6", 335, 80, K.WHITE)
        fonts.text(surf, "DRIVE. COLLECT. SURVIVE THE LUNAR NIGHT.", (C.RENDER_W // 2, 400), 24, K.CYAN, anchor="center")
        panel(surf, pygame.Rect(C.RENDER_W // 2 - 490, 440, 980, 360), 190, scan=False)
        self.list.draw(surf, C.RENDER_W // 2 - 440, 455, 62, 36)
        fonts.text(surf, "BEST  %s" % mmss(C.BEST_TIME), (C.RENDER_W - 40, C.RENDER_H - 110), 22, K.GREY, anchor="topright")
        hints(surf, "up / down: choose    A or Enter: select    Tab: connections    F2 / Back: hardware check    F11: fullscreen    M: mute")


class SettingsScreen:
    ITEMS = ("Master volume", "Post-processing", "Skip intro", "After game over", "Back")

    def __init__(self):
        self.list = MenuList([(i, "") for i in self.ITEMS])

    def value(self, k):
        return [("%d%%" % round(C.MASTER_VOLUME * 100)), ("OFF", "VIGNETTE", "FULL")[C.POSTFX], "ON" if C.SKIP_INTRO else "OFF",
                "straight back to PLAY" if C.RESTART_TO_PLAY else "go to MENU", ""][k]

    def change(self, app, d):
        i = self.list.i
        if i == 0:
            C.save_local(MASTER_VOLUME=round(max(0.0, min(1.0, C.MASTER_VOLUME + 0.1 * d)), 2))
        elif i == 1:
            C.save_local(POSTFX=(C.POSTFX + d) % 3)
            app.postfx.level = C.POSTFX
        elif i == 2:
            C.save_local(SKIP_INTRO=not C.SKIP_INTRO)
        elif i == 3:
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
        x, y = C.RENDER_W // 2 - 460, 220
        for k, item in enumerate(self.ITEMS):
            sel = k == self.list.i
            r = pygame.Rect(x, y + k * 62, 920, 54)
            if sel:
                s = pygame.Surface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(s, (60, 130, 220, 70), s.get_rect(), border_radius=10)
                pygame.draw.rect(s, (*K.CYAN, 230), s.get_rect(), 2, border_radius=10)
                surf.blit(s, r.topleft)
            fonts.text(surf, item, (r.left + 24, r.centery), 28, K.WHITE if sel else K.GREY, anchor="midleft")
            v = self.value(k)
            if v:
                fonts.text(surf, ("<  %s  >" if sel else "%s") % v, (r.right - 24, r.centery), 28, K.CYAN if sel else K.GREY, anchor="midright")
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
        title(surf, "PAUSED", 330, 90, K.WHITE)
        fonts.text(surf, "rover stopped", (C.RENDER_W // 2, 395), 22, K.GREY, anchor="center")
        self.list.draw(surf, C.RENDER_W // 2 - 260, 450, 64, 34, 520)
        hints(surf, "Start: resume    hold Start 2 s: restart the run")


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
            pygame.draw.rect(surf, (20, 32, 60), box, border_radius=10)
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
        ("tower_fire", "Tower warned, fired and answered K", "auto"),
        ("hud_link", "HUD panel connected, temperature readings arriving", "auto"),
        ("leds", "HUD LEDs: yellow blinks on pickup, red hot, blue cold", "manual"),
        ("buzzer", "HUD buzzer: fast high beeps hot, low beeps cold", "manual"),
        ("lcd", "HUD LCD and OLED show the numbers", "manual"),
    ]
    TESTS = {"1": "Spin LEFT wheel", "2": "Spin RIGHT wheel", "3": "Pan the camera", "4": "Fire tower once",
             "5": "Pickup blink + chirp", "6": "Hot warning", "7": "Cold warning"}

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
            t.allow(True)
            if t.fire(test=True):
                self.fire_t = now()
                app.toast("Fired: warning first, then one ball", "warn")
            else:
                app.toast("Tower disarmed or fired within 2 s", "warn")
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
        if self.fire_t > 0 and app.links["tower"].last_k > self.fire_t:
            st["tower_fire"] = True
        if snap["hud"][0] and app.links["hud"].last_w is not None:
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
        for key, label in (("pad", "Gamepad"), ("robot", "Rover (UNO Q, Wi-Fi)"), ("tower", "Tower (UNO Q, USB)"),
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
        fonts.text(surf, "TESTS (press the number)", (r.left + 20, r.top + 14), 18, K.GREY)
        for i, (k, label) in enumerate(self.TESTS.items()):
            fonts.text(surf, k, (r.left + 24, r.top + 52 + i * 42), 24, K.CYAN, mono=True, bold=True)
            fonts.text(surf, label, (r.left + 62, r.top + 52 + i * 42), 24, K.WHITE)
        y = 548
        fonts.text(surf, "CHECKLIST", (120, y - 6), 18, K.GREY)
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
        col = K.GREEN if ready else K.DIM
        pygame.draw.rect(surf, K.mix(K.PANEL, col, 0.28 if ready else 0.1), badge, border_radius=38)
        pygame.draw.rect(surf, col, badge, 3, border_radius=38)
        fonts.text(surf, "READY FOR DEMO" if ready else "%d of %d checks passed" % (sum(1 for v in self.status.values() if v), len(self.status)),
                   badge.center, 34 if ready else 26, col, bold=True, anchor="center")
        hints(surf, "1-7: run a test    Y / N: confirm what you saw    Esc / B: back")


class ResultsScreen:
    """The debrief: time survived, samples by type, strikes, the meter that failed first, why it matters, the NASA data used."""

    def handle(self, app, a):
        if a in ("start", "confirm"):
            app.after_results()

    def update(self, app, dt):
        pass

    def draw(self, surf, app):
        res = app.last_results
        pygame.draw.rect(surf, (0, 0, 0), (0, 0, C.RENDER_W, C.RENDER_H))
        cx = C.RENDER_W // 2
        title(surf, "OUTPOST LOST", 110, 90, K.RED)
        fonts.text(surf, "Time survived  %s" % mmss(res["time"]), (cx, 200), 34, K.WHITE, anchor="center")
        s = res["samples"]
        rows = (("Samples collected", "ice %d    regolith %d    mineral %d    (score %d)" % (s["ice"], s["regolith"], s["mineral"], res["score"])),
                ("Asteroid hits", str(res["strikes"])),
                ("Failed first", res["first_fail_label"].upper()))
        for i, (k, v) in enumerate(rows):
            fonts.text(surf, k, (cx - 40, 280 + i * 56), 28, K.GREY, anchor="topright")
            fonts.text(surf, v, (cx + 10, 280 + i * 56), 28, K.RED if i == 2 else K.WHITE, bold=(i == 2), anchor="topleft")
        CalibrateScreen.wrap(surf, res["why"], cx, 470, 1300, 28, K.YELLOW)
        fonts.text(surf, "NASA data used this run", (cx, 590), 20, K.GREY, anchor="center")
        for i, line in enumerate(res["nasa"] or ["none (no data files found in data/nasa)"]):
            fonts.text(surf, line, (cx, 625 + i * 32), 22, K.CYAN, anchor="center")
        if int(now() * 2) % 2:
            fonts.text(surf, "Press Start or Enter to try again", (cx, C.RENDER_H - 160), 44, K.YELLOW, bold=True, anchor="center")


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
            fonts.text(surf, "%s FAILED" % (self.fail.upper() or "LIFE SUPPORT"), (C.RENDER_W // 2, 200), 64, K.RED, bold=True, anchor="center", shadow=True)
            pygame.draw.rect(surf, K.RED, (6, 6, C.RENDER_W - 12, C.RENDER_H - 12), 5)
        s = pygame.Surface((C.RENDER_W, C.RENDER_H), pygame.SRCALPHA)
        s.fill((0, 0, 0, int(min(1.0, self.t / self.LENGTH) * 255)))
        surf.blit(s, (0, 0))

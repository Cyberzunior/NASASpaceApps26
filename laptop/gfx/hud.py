"""The heads-up display. Every panel floats over the game (the game fills the whole screen)."""
import math
import pygame
import config as C
from core import thermal as th
from core.clock import mmss
from core.model import angdiff
from core.game import KINDS, LABELS, METERS
from gfx import fonts, palette as K
from gfx.widgets import Hearts, Toasts, Tween, banner, bar, caption, dot, keycap, panel, pill
from gfx.world import SAMPLE_COLORS

METER_COLORS = {"power": K.YELLOW, "oxygen": K.CYAN, "food": K.GREEN, "shield": K.VIOLET}
LABELS_CONN = (("hud", "HUD"), ("tower", "TOWER"), ("robot", "ROVER"), ("camera", "CAM"))
STATUS_COLOR = {"connected": K.GREEN, "not connected": K.DIM, "lost": K.RED}


class Hud:
    def __init__(self):
        self.hearts = Hearts(C.LIVES, 24)
        self.toasts = Toasts()
        self.t = 0.0
        self.hit_flash = 0.0
        self.cam_surface = None
        self.cam_stamp = -1.0
        self.cam_t = -1.0
        self.cam_scaled = {}
        self.age_shown, self.age_t = 0, -1.0
        self.bars = {k: Tween(100.0, 8.0) for k in METERS}
        self.edge = 0.0
        self.edge_img = None
        self.dt = 1 / 60
        self.last = {k: 100.0 for k in METERS}      # meter values last frame: a jump starts a ghost or a glow
        self.ghost = {k: 100.0 for k in METERS}     # where a bar was before a sudden loss
        self.hold = {k: 0.0 for k in METERS}        # seconds the ghost waits before it drains
        self.gain = {k: 0.0 for k in METERS}        # glow after a sudden gain, 1 -> 0
        self.enter = 1.0                            # 0 -> 1: the panels slide in when a run starts
        self.banner_age = {}                        # banner name -> seconds on screen
        self.bearing = 0.0                          # compass arrow angle, smoothed
        self.count = 0                              # samples collected, to pulse the counter
        self.count_pulse = 0.0

    def update(self, dt, game):
        self.t += dt
        self.dt = dt
        self.hearts.set(game.hearts)
        self.hearts.update(dt)
        self.toasts.update(dt)
        self.hit_flash = max(0.0, self.hit_flash - dt)
        for k in METERS:
            v = game.m[k]
            if v < self.last[k] - 2.5:                          # a hit or an action cost: keep the old level visible for a moment
                self.ghost[k] = max(self.ghost[k], self.last[k])
                self.hold[k] = 0.45
            elif v > self.last[k] + 2.5:
                self.gain[k] = 1.0
            self.last[k] = v
            self.bars[k].set(v)
            self.bars[k].update(dt)
            self.hold[k] = max(0.0, self.hold[k] - dt)
            if self.hold[k] <= 0.0:
                self.ghost[k] = max(self.bars[k].v, self.ghost[k] - 55.0 * dt)
            self.gain[k] = max(0.0, self.gain[k] - dt * 1.8)
        warn = game.strike is not None and game.strike["phase"] == "warn"
        self.edge = min(1.0, self.edge + dt * 4) if warn else max(0.0, self.edge - dt * 3)
        if not game.intro_on:
            self.enter = min(1.0, self.enter + dt / 0.7)
        if game.sample:
            self.bearing += angdiff(game.sample_bearing(), self.bearing) * min(1.0, dt * 10.0)
        n = sum(game.samples.values())
        if n > self.count:
            self.count_pulse = 1.0
        self.count = n
        self.count_pulse = max(0.0, self.count_pulse - dt * 1.4)

    def reset(self, game):
        self.hearts.shown = game.hearts
        self.hearts.anim.clear()
        self.toasts.items.clear()
        for k in METERS:
            self.bars[k].v = self.last[k] = self.ghost[k] = game.m[k]
            self.hold[k] = self.gain[k] = 0.0
        self.enter = 0.0
        self.banner_age.clear()
        self.count = self.count_pulse = 0

    def slide(self, side):
        """Offset (dx, dy) of a panel on this side of the screen while the HUD slides in."""
        e = 1.0 - (1.0 - self.enter) ** 3
        d = int((1.0 - e) * 560)
        return {"left": (-d, 0), "right": (d, 0), "top": (0, -d // 3), "bottom": (0, d // 2)}[side]

    def _appear(self, key):
        """0..1 over the first 0.3 s a banner is shown."""
        self.banner_age[key] = self.banner_age.get(key, 0.0) + self.dt
        return min(1.0, self.banner_age[key] / 0.3)

    # ---- connection dots
    def conn_strip(self, surf, conn, x=None, y=16):
        """Compact strip of the four connection dots: green connected, grey not connected, red lost."""
        w = 430
        x = C.RENDER_W - 24 - w if x is None else x
        r = panel(surf, pygame.Rect(x, y, w, 40).move(self.slide("top")), 175, scan=False, radius=20)
        cx = r.left + 26
        for key, label in LABELS_CONN:
            st = conn.get(key, ("not connected",))[0] if conn else "not connected"
            dot(surf, (cx, r.centery), STATUS_COLOR[st], 6)
            fonts.text(surf, label, (cx + 14, r.centery), 15, K.WHITE if st == "connected" else K.GREY, bold=True, anchor="midleft", track=1)
            cx += fonts.width(label, 15, bold=True) + len(label) + 44
        return r

    # ---- pieces
    def meters_panel(self, surf, game):
        r = panel(surf, pygame.Rect(24, 16, 470, 250).move(self.slide("left")))
        self.hearts.draw(surf, (r.left + 16, r.top + 12), game.hearts, self.t)
        fonts.text(surf, "BASE INTEGRITY  %d / %d" % (game.hearts, C.LIVES), (r.left + 18, r.top + 46), 14, K.GREY, bold=True, track=1)
        fonts.text(surf, "T+ %s" % mmss(game.t), (r.right - 18, r.top + 42), 22, K.CYAN, mono=True, bold=True, anchor="topright")
        pygame.draw.line(surf, (40, 62, 104), (r.left + 16, r.top + 72), (r.right - 16, r.top + 72))
        y = r.top + 84
        for k in METERS:
            col = METER_COLORS[k]
            v = self.bars[k].v
            low = game.m[k] < 20
            blink = low and int(self.t * 4) % 2
            pygame.draw.rect(surf, K.RED if blink else col, (r.left + 18, y + 5, 4, 16), border_radius=2)
            fonts.text(surf, LABELS[k].upper(), (r.left + 30, y + 3), 17, K.RED if blink else K.WHITE, bold=True, track=1)
            b = pygame.Rect(r.left + 136, y + 3, 258, 20)
            bar(surf, b, v / 100.0, col, flash=K.RED if blink else None, ghost=self.ghost[k] / 100.0, gain=self.gain[k])
            fonts.text(surf, "%d" % round(v), (r.right - 18, b.centery), 21,
                       K.RED if low else K.mix(K.WHITE, K.GREEN, int(self.gain[k] * 5) / 5.0), mono=True, bold=True, anchor="midright")
            y += 38
        return r

    def thermal_panel(self, surf, game):
        th_ = game.thermal
        r = panel(surf, pygame.Rect(24, 280, 470, 128).move(self.slide("left")))
        col = (K.GREEN, K.ICE, K.HEAT)[th_.state]
        caption(surf, "LUNAR SURFACE", (r.left + 18, r.top + 14))
        fonts.text(surf, "%d C" % round(th_.lunar_c), (r.left + 18, r.top + 36), 40, K.WHITE, mono=True, bold=True, display=True)
        pill(surf, pygame.Rect(r.right - 150, r.top + 16, 132, 30), th.NAMES[th_.state], col, 16)
        day = th_.daylight()
        h = th_.local_hour()
        fonts.text(surf, ("DAY  " if day else "NIGHT  ") + "%02d:%02d" % (int(h), int((h % 1) * 60)), (r.right - 18, r.top + 60), 18,
                   K.YELLOW if day else K.ICE, mono=True, bold=True, anchor="topright")
        pygame.draw.line(surf, (40, 62, 104), (r.left + 16, r.bottom - 34), (r.right - 16, r.bottom - 34))
        src = th_.source() or "built-in curve"
        fonts.text(surf, ("solar charging" if day else "no sunlight") + "   |   " + src, (r.left + 18, r.bottom - 17), 14,
                   K.GREEN if day else K.GREY, anchor="midleft")
        return r

    def banners(self, surf, game, y):
        live = set()
        y = self._banners(surf, game, y, live)
        for key in [k for k in self.banner_age if k not in live]:
            del self.banner_age[key]
        return y

    def _banners(self, surf, game, y, live):
        if game.strike is not None and game.strike["phase"] == "warn":
            live.add("strike")
            s = game.strike
            sub = "Drive clear of the marked spot"
            if s.get("date"):
                sub = "Drive clear!  Impact flash of %s   Source: NASA lunar impact monitoring" % s["date"]
            banner(surf, C.RENDER_W // 2 + 180, y, "ASTEROID INCOMING  %.0f s" % math.ceil(max(0.0, s["left"])), sub, K.RED, self.t,
                   appear=self._appear("strike"))
            y += 108
        if game.storm:
            st = game.storm
            sub = "Shield draining. Press 3 to boost it."
            if st["nasa"]:
                sub = "%s  %s   Source: NASA DONKI" % (st["label"], st["date"])
            live.add("storm")
            banner(surf, C.RENDER_W // 2 + 180, y, "RADIATION STORM  %.0f s" % max(0.0, st["left"]), sub, K.VIOLET, self.t, appear=self._appear("storm"))
            y += 108
        if game.thermal.state != th.NORMAL:
            hot = game.thermal.state == th.HOT
            banner(surf, C.RENDER_W // 2 + 180, y, "HOT SURFACE: COOLING" if hot else "COLD SURFACE: HEATING",
                   ("Power drain doubled   " + game.thermal.source()).strip(),
                   K.HEAT if hot else K.ICE, self.t, appear=self._appear("thermal"))
            live.add("thermal")
            y += 108
        if game.m["power"] <= 0:
            banner(surf, C.RENDER_W // 2 + 180, y, "POWER OFF", "Rover and actions locked until power returns (sunlight, mineral samples)", K.YELLOW, self.t,
                   appear=self._appear("power"))
            live.add("power")
            y += 108
        elif game.t < game.rest_until:
            fonts.text(surf, "CREW RESTING  %.0f s" % (game.rest_until - game.t), (C.RENDER_W // 2, y + 10), 32, K.CYAN, bold=True, anchor="midtop", shadow=True)
            y += 60
        if game.fact[1] > game.t and game.fact[0]:
            fonts.text(surf, "%s   Source: NASA Veggie" % game.fact[0], (C.RENDER_W // 2, y + 6), 22, K.GREEN, anchor="midtop", shadow=True)
            y += 40
        return y

    def compass(self, surf, game):
        """Small top-view rover with an arrow to the current sample, relative to the heading, and the distance in metres."""
        r = panel(surf, pygame.Rect(24, C.RENDER_H - 24 - 220, 300, 220).move(self.slide("left")))
        cx, cy = r.left + 110, r.centery + 6
        caption(surf, "NEXT SAMPLE", (r.left + 18, r.top + 12))
        pygame.draw.circle(surf, K.TRACK, (cx, cy), 86)
        pygame.draw.circle(surf, (44, 70, 118), (cx, cy), 86, 2)
        pygame.draw.circle(surf, (30, 48, 86), (cx, cy), 48, 1)
        for i in range(12):                                             # bezel ticks
            a = math.radians(i * 30)
            pygame.draw.line(surf, (70, 104, 160), (cx + 78 * math.sin(a), cy - 78 * math.cos(a)), (cx + 85 * math.sin(a), cy - 85 * math.cos(a)), 2)
        for a in (-40, 40):                                              # the cone samples spawn in
            pygame.draw.line(surf, (40, 70, 110), (cx, cy), (cx + 86 * math.sin(math.radians(a)), cy - 86 * math.cos(math.radians(a))), 1)
        pygame.draw.rect(surf, K.HULL, (cx - 11, cy - 18, 22, 36), border_radius=5)            # rover icon, nose up
        pygame.draw.rect(surf, (70, 110, 150), (cx - 7, cy - 14, 14, 9), border_radius=2)
        if game.sample:
            b = game.sample_bearing()
            d = game.sample_distance()
            near = max(0.0, min(1.0, 1.0 - (d - C.SAMPLE_PICKUP_M) / (C.SAMPLE_MAX_M * 1.5)))
            near = int(near * 12) / 12.0                                  # in steps: a new colour every frame means new text every frame
            col = K.mix((90, 110, 150), SAMPLE_COLORS[game.sample["kind"]], 0.35 + 0.65 * near)
            col = K.mix(col, K.WHITE, 0.4 * near * near)
            a = math.radians(self.bearing)                                # the arrow swings smoothly to the new bearing
            ex, ey = cx + 70 * math.sin(a), cy - 70 * math.cos(a)
            pygame.draw.line(surf, col, (cx + 20 * math.sin(a), cy - 20 * math.cos(a)), (ex, ey), 5)
            hx, hy = math.sin(a), -math.cos(a)
            pygame.draw.polygon(surf, col, [(ex + hx * 14, ey + hy * 14), (ex - hy * 9 - hx * 4, ey + hx * 9 - hy * 4), (ex + hy * 9 - hx * 4, ey - hx * 9 - hy * 4)])
            fonts.text(surf, "%.0f m" % d, (r.right - 14, r.top + 70), 34, col, mono=True, bold=True, anchor="topright")
            fonts.text(surf, game.sample["kind"].upper(), (r.right - 18, r.top + 120), 20, SAMPLE_COLORS[game.sample["kind"]], bold=True, anchor="topright")
            fonts.text(surf, ("left " if b < -3 else "right " if b > 3 else "ahead ") + ("%d deg" % abs(b) if abs(b) > 3 else ""),
                       (r.right - 18, r.top + 148), 18, K.GREY, anchor="topright")
        fonts.text(surf, "ICE %d  REGOLITH %d  MINERAL %d" % tuple(game.samples[k] for k in KINDS), (r.left + 18, r.bottom - 28), 15,
                   K.mix(K.GREY, K.WHITE, int(self.count_pulse * 6) / 6.0))

    def actions_panel(self, surf, game, ap_on, pad_on=False):
        w = 860
        r = panel(surf, pygame.Rect(C.RENDER_W // 2 - w // 2, C.RENDER_H - 24 - 120, w, 120).move(self.slide("bottom")))
        locked = not game.can_act()
        items = (("1", "Scrubber", "-%d PWR  +%d O2" % (C.SCRUBBER_POWER, C.SCRUBBER_OXYGEN)),
                 ("2", "Greenhouse", "-%d PWR  +%d FOOD later" % (game.nasa.veggie.power, C.GREENHOUSE_FOOD)),
                 ("3", "Shield boost", "-%d PWR  +%d SHLD" % (C.SHIELD_BOOST_POWER, C.SHIELD_BOOST_GAIN)),
                 ("4", "Rest crew", "stop %d s  +%d O2 +%d FOOD" % (C.REST_S, C.REST_OXYGEN, C.REST_FOOD)))
        for i, (key, name, desc) in enumerate(items):
            key = ("A", "X", "L", "R3")[i] if pad_on else key              # 8BitDo Ultimate (Switch): A, X, L bumper, right-stick click
            x = r.left + 20 + i * 210
            if i:
                pygame.draw.line(surf, (40, 62, 104), (x - 12, r.top + 14), (x - 12, r.top + 74))
            keycap(surf, (x, r.top + 14), key, not locked)
            fonts.text(surf, name, (x + 40, r.top + 16), 20, K.DIM if locked else K.WHITE, bold=True)
            fonts.text(surf, desc, (x, r.top + 54), 13, K.DIM if locked else K.mix(K.GREY, K.WHITE, 0.3))
        pygame.draw.line(surf, (40, 62, 104), (r.left + 16, r.bottom - 40), (r.right - 16, r.bottom - 40))
        c = K.GREEN if ap_on else K.GREY
        dot(surf, (r.left + 28, r.bottom - 21), c, 6)
        fonts.text(surf, "AUTO-PILOT %s" % ("ON" if ap_on else "OFF"), (r.left + 44, r.bottom - 21), 14, c, bold=True, anchor="midleft", track=1)
        hint = ("Y autopilot   L-stick drive   R-stick camera   B rover cam" if pad_on
                else "Ctrl+Space autopilot   WASD drive   Q/E camera   R recentre   C rover cam")
        fonts.text(surf, hint,
                   (r.right - 20, r.bottom - 21), 14, K.GREY, anchor="midright")

    def camera(self, surf, cam, full, rect=None):
        if full:
            rect = pygame.Rect(0, 0, C.RENDER_W, C.RENDER_H)
        else:
            rect = pygame.Rect(C.RENDER_W - 24 - 360, C.RENDER_H - 24 - 290, 360, 290).move(self.slide("right"))
            panel(surf, rect, 200, scan=False)
            rect = pygame.Rect(rect.left + 8, rect.top + 8, rect.w - 16, rect.h - 54)
        frame = cam.frame if cam else None
        live = bool(cam and cam.live())
        if live and frame is not None:
            if cam.stamp != self.cam_stamp and self.t - self.cam_t >= 1 / 15:       # camera picture at most 15 times a second
                self.cam_stamp, self.cam_t = cam.stamp, self.t
                self.cam_surface = pygame.image.frombuffer(frame.tobytes(), (frame.shape[1], frame.shape[0]), "RGB")
                self.cam_scaled = {}                                                    # scaled copies belong to the new picture
            key = tuple(rect.size)
            img = self.cam_scaled.get(key) if self.cam_surface is not None else None
            if img is None and self.cam_surface is not None:
                img = self.cam_scaled[key] = (pygame.transform.scale(self.cam_surface, key) if full
                                              else pygame.transform.smoothscale(self.cam_surface, key))
            if img is not None:
                surf.blit(img, rect)
        else:
            pygame.draw.rect(surf, (8, 10, 18), rect)
            fonts.text(surf, "NO SIGNAL", rect.center, 40 if full else 26, K.GREY, bold=True, anchor="center")
            if cam is not None and cam.error:
                fonts.text(surf, cam.error[:60], (rect.centerx, rect.centery + (36 if full else 24)), 18 if full else 14, K.DIM, anchor="center")
        badge = pygame.Rect(rect.left + 14, rect.top + 12, 150, 30) if full else pygame.Rect(rect.left + 6, rect.bottom + 8, 190, 30)
        col = K.GREEN if live else K.RED
        age = cam.age_ms() if cam else None
        if age is not None and self.t - self.age_t >= 0.25:                 # the delay readout refreshes 4 times a second: readable, and no new text every frame
            self.age_shown, self.age_t = age, self.t
        pill(surf, badge, ("LIVE %d ms" % self.age_shown) if live and age is not None else "NO SIGNAL", col)
        if not full:
            fonts.text(surf, "ROVER CAM  [C]", (rect.right - 6, rect.bottom + 15), 14, K.GREY, bold=True, anchor="topright", track=1)

    def debug(self, surf, info):
        lines = ["FPS %5.1f   frame %5.1f ms   worst %5.1f ms   postfx %d" % (info["fps"], info["ms"], info["worst"], info["postfx"])]
        lines += ["%-8s %s" % (k, v) for k, v in info["threads"].items()]
        lines += info["packets"]
        r = pygame.Rect(C.RENDER_W // 2 - 330, 140, 660, 24 + 21 * len(lines))
        panel(surf, r, 215, scan=False)
        for i, l in enumerate(lines):
            fonts.text(surf, l, (r.left + 16, r.top + 12 + i * 21), 16, K.GREEN, mono=True)

    def edge_flash(self, surf):
        if self.edge > 0.01:                                    # asteroid warning: the screen edge flashes red
            if self.edge_img is None:                           # built once, faded with set_alpha
                self.edge_img = pygame.Surface((C.RENDER_W, C.RENDER_H), pygame.SRCALPHA)
                for i in range(14):
                    pygame.draw.rect(self.edge_img, (255, 40, 40, int(230 * (1 - i / 14) ** 2)), (i * 5, i * 5, C.RENDER_W - i * 10, C.RENDER_H - i * 10), 5)
            p = 0.5 + 0.5 * math.sin(self.t * 14)
            self.edge_img.set_alpha(int(255 * self.edge * (0.35 + 0.65 * p)))
            surf.blit(self.edge_img, (0, 0))

    def draw(self, surf, game, ui):
        """ui: dict(conn, ap_on, camera, cam_full, debug)"""
        if ui.get("cam_full"):
            self.camera(surf, ui["camera"], True)
        self.edge_flash(surf)
        self.conn_strip(surf, ui.get("conn"))
        y = self.banners(surf, game, 70)
        self.toasts.draw(surf, C.RENDER_W // 2, y + 6 if y != 70 else 74)
        self.meters_panel(surf, game)
        self.thermal_panel(surf, game)
        self.compass(surf, game)
        self.actions_panel(surf, game, ui["ap_on"], ui.get("pad_on"))
        if not ui.get("cam_full"):
            self.camera(surf, ui["camera"], False)
        if ui.get("debug"):
            self.debug(surf, ui["debug"])

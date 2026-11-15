"""The heads-up display. Every panel floats over the game (the game fills the whole screen)."""
import math
import pygame
import config as C
from core import thermal as th
from core.clock import mmss
from core.game import KINDS, LABELS, METERS
from gfx import fonts, palette as K
from gfx.widgets import Hearts, Toasts, Tween, banner, dot, panel
from gfx.world import SAMPLE_COLORS

METER_COLORS = {"power": K.YELLOW, "oxygen": K.CYAN, "food": K.GREEN, "shield": (190, 140, 255)}
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
        self.bars = {k: Tween(100.0, 8.0) for k in METERS}
        self.edge = 0.0

    def update(self, dt, game):
        self.t += dt
        self.hearts.set(game.hearts)
        self.hearts.update(dt)
        self.toasts.update(dt)
        self.hit_flash = max(0.0, self.hit_flash - dt)
        for k in METERS:
            self.bars[k].set(game.m[k])
            self.bars[k].update(dt)
        warn = game.strike is not None and game.strike["phase"] == "warn"
        self.edge = min(1.0, self.edge + dt * 4) if warn else max(0.0, self.edge - dt * 3)

    def reset(self, game):
        self.hearts.shown = game.hearts
        self.hearts.anim.clear()
        self.toasts.items.clear()
        for k in METERS:
            self.bars[k].v = game.m[k]

    # ---- connection dots
    def conn_strip(self, surf, conn, x=None, y=16):
        """Compact strip of the four connection dots: green connected, grey not connected, red lost."""
        w = 400
        x = C.RENDER_W - 24 - w if x is None else x
        r = panel(surf, pygame.Rect(x, y, w, 40), 175, scan=False, radius=20)
        cx = r.left + 24
        for key, label in LABELS_CONN:
            st = conn.get(key, ("not connected",))[0] if conn else "not connected"
            dot(surf, (cx, r.centery), STATUS_COLOR[st], 7)
            fonts.text(surf, label, (cx + 13, r.centery), 16, K.WHITE if st == "connected" else K.GREY, anchor="midleft")
            cx += fonts.width(label, 16) + 40
        return r

    # ---- pieces
    def meters_panel(self, surf, game):
        r = panel(surf, pygame.Rect(24, 16, 470, 250))
        self.hearts.draw(surf, (r.left + 16, r.top + 12), game.hearts, self.t)
        fonts.text(surf, "BASE %d / %d" % (game.hearts, C.LIVES), (r.left + 18, r.top + 46), 16, K.GREY)
        fonts.text(surf, "T+ %s" % mmss(game.t), (r.right - 18, r.top + 44), 20, K.CYAN, mono=True, anchor="topright")
        y = r.top + 78
        for k in METERS:
            col = METER_COLORS[k]
            v = self.bars[k].v
            low = game.m[k] < 20
            fonts.text(surf, LABELS[k], (r.left + 18, y + 2), 20, K.WHITE, bold=True)
            bar = pygame.Rect(r.left + 120, y + 2, 270, 22)
            pygame.draw.rect(surf, (20, 32, 60), bar, border_radius=6)
            fill = bar.copy()
            fill.w = int(bar.w * max(0.0, min(1.0, v / 100.0)))
            c = K.RED if low and int(self.t * 4) % 2 else col
            if fill.w > 0:
                pygame.draw.rect(surf, c, fill, border_radius=6)
            pygame.draw.rect(surf, K.mix(col, K.WHITE, 0.3), bar, 2, border_radius=6)
            fonts.text(surf, "%d" % round(game.m[k]), (bar.right + 14, bar.centery), 20, K.WHITE, mono=True, anchor="midleft")
            y += 38
        return r

    def thermal_panel(self, surf, game):
        th_ = game.thermal
        r = panel(surf, pygame.Rect(24, 280, 470, 128))
        col = (K.GREEN, K.ICE, K.HEAT)[th_.state]
        fonts.text(surf, th_.label(), (r.left + 18, r.top + 12), 22, K.WHITE, mono=True)
        src = "Source: NASA LRO Diviner" if game.nasa.diviner.ok else "built-in temperature curve"
        fonts.text(surf, src, (r.left + 18, r.top + 42), 16, K.GREY)
        badge = pygame.Rect(r.right - 150, r.top + 70, 132, 30)
        pygame.draw.rect(surf, K.mix(K.PANEL, col, 0.35), badge, border_radius=15)
        pygame.draw.rect(surf, col, badge, 2, border_radius=15)
        fonts.text(surf, th.NAMES[th_.state], badge.center, 19, col, bold=True, anchor="center")
        day = th_.daylight()
        h = th_.local_hour()
        fonts.text(surf, ("DAY  " if day else "NIGHT  ") + "%02d:%02d" % (int(h), int((h % 1) * 60)), (r.left + 18, r.top + 78), 22,
                   K.YELLOW if day else K.ICE, mono=True)
        fonts.text(surf, "solar charging" if day else "no sunlight", (r.left + 18, r.top + 104), 16, K.GREEN if day else K.DIM)
        return r

    def banners(self, surf, game, y):
        if game.strike is not None and game.strike["phase"] == "warn":
            s = game.strike
            sub = "Impact in %.0f s" % max(0.0, s["left"])
            if s.get("date"):
                sub += "   real flash: %s   Source: NASA lunar impact monitoring" % s["date"]
            banner(surf, C.RENDER_W // 2 + 180, y, "ASTEROID INCOMING", sub, K.RED, self.t)
            y += 108
        if game.storm:
            st = game.storm
            sub = "Shield draining. Press 3 to boost it."
            if st["nasa"]:
                sub = "%s  %s   Source: NASA DONKI" % (st["label"], st["date"])
            banner(surf, C.RENDER_W // 2 + 180, y, "RADIATION STORM  %.0f s" % max(0.0, st["left"]), sub, (190, 140, 255), self.t)
            y += 108
        if game.thermal.state != th.NORMAL:
            hot = game.thermal.state == th.HOT
            banner(surf, C.RENDER_W // 2 + 180, y, "HOT SURFACE: COOLING" if hot else "COLD SURFACE: HEATING",
                   "Power drain doubled   Source: NASA LRO Diviner" if game.nasa.diviner.ok else "Power drain doubled",
                   K.HEAT if hot else K.ICE, self.t)
            y += 108
        if game.m["power"] <= 0:
            banner(surf, C.RENDER_W // 2 + 180, y, "POWER OFF", "Rover and actions locked until power returns (sunlight, mineral samples)", K.YELLOW, self.t)
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
        r = panel(surf, pygame.Rect(24, C.RENDER_H - 24 - 220, 300, 220))
        cx, cy = r.left + 110, r.centery + 6
        fonts.text(surf, "SAMPLE", (r.left + 18, r.top + 10), 16, K.GREY)
        pygame.draw.circle(surf, (24, 40, 74), (cx, cy), 86, 2)
        for a in (-40, 40):                                              # the cone samples spawn in
            pygame.draw.line(surf, (40, 70, 110), (cx, cy), (cx + 86 * math.sin(math.radians(a)), cy - 86 * math.cos(math.radians(a))), 1)
        pygame.draw.rect(surf, K.HULL, (cx - 11, cy - 18, 22, 36), border_radius=5)            # rover icon, nose up
        pygame.draw.rect(surf, (70, 110, 150), (cx - 7, cy - 14, 14, 9), border_radius=2)
        if game.sample:
            b = game.sample_bearing()
            d = game.sample_distance()
            near = max(0.0, min(1.0, 1.0 - (d - C.SAMPLE_PICKUP_M) / (C.SAMPLE_MAX_M * 1.5)))
            col = K.mix((90, 110, 150), SAMPLE_COLORS[game.sample["kind"]], 0.35 + 0.65 * near)
            col = K.mix(col, K.WHITE, 0.4 * near * near)
            a = math.radians(b)
            ex, ey = cx + 70 * math.sin(a), cy - 70 * math.cos(a)
            pygame.draw.line(surf, col, (cx + 20 * math.sin(a), cy - 20 * math.cos(a)), (ex, ey), 5)
            hx, hy = math.sin(a), -math.cos(a)
            pygame.draw.polygon(surf, col, [(ex + hx * 14, ey + hy * 14), (ex - hy * 9 - hx * 4, ey + hx * 9 - hy * 4), (ex + hy * 9 - hx * 4, ey - hx * 9 - hy * 4)])
            fonts.text(surf, "%.0f m" % d, (r.right - 18, r.top + 70), 40, col, mono=True, bold=True, anchor="topright")
            fonts.text(surf, game.sample["kind"].upper(), (r.right - 18, r.top + 120), 20, SAMPLE_COLORS[game.sample["kind"]], bold=True, anchor="topright")
            fonts.text(surf, ("left " if b < -3 else "right " if b > 3 else "ahead ") + ("%d deg" % abs(b) if abs(b) > 3 else ""),
                       (r.right - 18, r.top + 148), 18, K.GREY, anchor="topright")
        fonts.text(surf, "ICE %d  REGOLITH %d  MINERAL %d" % tuple(game.samples[k] for k in KINDS), (r.left + 18, r.bottom - 28), 15, K.GREY)

    def actions_panel(self, surf, game, ap_on):
        w = 860
        r = panel(surf, pygame.Rect(C.RENDER_W // 2 - w // 2, C.RENDER_H - 24 - 120, w, 120))
        locked = not game.can_act()
        items = (("1", "Scrubber", "-%d PWR  +%d O2" % (C.SCRUBBER_POWER, C.SCRUBBER_OXYGEN)),
                 ("2", "Greenhouse", "-%d PWR  +%d FOOD later" % (game.nasa.veggie.power, C.GREENHOUSE_FOOD)),
                 ("3", "Shield boost", "-%d PWR  +%d SHLD" % (C.SHIELD_BOOST_POWER, C.SHIELD_BOOST_GAIN)),
                 ("4", "Rest crew", "stop %d s  +%d O2 +%d FOOD" % (C.REST_S, C.REST_OXYGEN, C.REST_FOOD)))
        for i, (key, name, desc) in enumerate(items):
            x = r.left + 18 + i * 210
            col = K.DIM if locked else K.WHITE
            pygame.draw.rect(surf, (24, 40, 74), (x, r.top + 14, 30, 30), border_radius=6)
            fonts.text(surf, key, (x + 15, r.top + 29), 22, K.CYAN if not locked else K.DIM, bold=True, anchor="center")
            fonts.text(surf, name, (x + 40, r.top + 16), 20, col, bold=True)
            fonts.text(surf, desc, (x, r.top + 54), 15, K.GREY if not locked else K.DIM)
        c = K.GREEN if ap_on else K.GREY
        dot(surf, (r.left + 28, r.bottom - 22), c, 6)
        fonts.text(surf, "AUTO-PILOT %s (Y or P)   WASD drive   Q / E pan camera   R recentre   C robot cam" % ("ON" if ap_on else "OFF"),
                   (r.left + 44, r.bottom - 22), 15, c if ap_on else K.GREY, anchor="midleft")

    def camera(self, surf, cam, full, rect=None):
        if full:
            rect = pygame.Rect(0, 0, C.RENDER_W, C.RENDER_H)
        else:
            rect = pygame.Rect(C.RENDER_W - 24 - 360, C.RENDER_H - 24 - 290, 360, 290)
            panel(surf, rect, 200, scan=False)
            rect = pygame.Rect(rect.left + 8, rect.top + 8, rect.w - 16, rect.h - 54)
        frame = cam.frame if cam else None
        live = bool(cam and cam.live())
        if live and frame is not None:
            if cam.stamp != self.cam_stamp:
                self.cam_stamp = cam.stamp
                self.cam_surface = pygame.image.frombuffer(frame.tobytes(), (frame.shape[1], frame.shape[0]), "RGB")
            surf.blit(pygame.transform.scale(self.cam_surface, rect.size) if full else pygame.transform.smoothscale(self.cam_surface, rect.size), rect)
        else:
            pygame.draw.rect(surf, (8, 10, 18), rect)
            fonts.text(surf, "NO SIGNAL", rect.center, 40 if full else 26, K.GREY, bold=True, anchor="center")
            if cam is not None and cam.error:
                fonts.text(surf, cam.error[:60], (rect.centerx, rect.centery + (36 if full else 24)), 18 if full else 14, K.DIM, anchor="center")
        badge = pygame.Rect(rect.left + 14, rect.top + 12, 150, 30) if full else pygame.Rect(rect.left + 6, rect.bottom + 8, 190, 30)
        col = K.GREEN if live else K.RED
        pygame.draw.rect(surf, K.mix(K.PANEL, col, 0.3), badge, border_radius=15)
        pygame.draw.rect(surf, col, badge, 2, border_radius=15)
        age = cam.age_ms() if cam else None
        fonts.text(surf, ("LIVE %d ms" % age) if live and age is not None else "NO SIGNAL", badge.center, 17, col, bold=True, anchor="center")
        if not full:
            fonts.text(surf, "ROVER CAM  [C]", (rect.right - 6, rect.bottom + 14), 15, K.GREY, anchor="topright")

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
            p = 0.5 + 0.5 * math.sin(self.t * 14)
            a = int(255 * self.edge * (0.35 + 0.65 * p))
            s = pygame.Surface((C.RENDER_W, C.RENDER_H), pygame.SRCALPHA)
            for i, al in enumerate((a, a // 2, a // 4)):
                pygame.draw.rect(s, (255, 40, 40, al), (i * 14, i * 14, C.RENDER_W - i * 28, C.RENDER_H - i * 28), 14)
            surf.blit(s, (0, 0))

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
        self.actions_panel(surf, game, ui["ap_on"])
        if not ui.get("cam_full"):
            self.camera(surf, ui["camera"], False)
        if ui.get("debug"):
            self.debug(surf, ui["debug"])

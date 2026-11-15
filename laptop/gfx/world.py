"""Draws the lunar surface seen from above: grey regolith with craters and rocks, the rover, the current sample,
tyre tracks, the day and night light and the radiation storm tint. The camera follows the rover."""
import collections
import math
import random
import pygame
import config as C
from core.game import KINDS
from gfx import palette as K
from gfx.particles import Particles
from gfx.starfield import Starfield
from gfx.rover import Rover, glow_sprite

SAMPLE_COLORS = {"ice": (140, 225, 255), "regolith": (225, 150, 80), "mineral": (230, 110, 255)}
CELL_M = 14.0


def _speckle_tile(size=256, seed=7):
    rnd = random.Random(seed)
    s = pygame.Surface((size, size))
    s.fill((112, 113, 118))
    for _ in range(1400):
        v = rnd.randint(-14, 14)
        c = (112 + v, 113 + v, 118 + v)
        pygame.draw.circle(s, c, (rnd.randrange(size), rnd.randrange(size)), rnd.choice((1, 1, 2, 3)))
    return s.convert()


def _crater(radius_px, seed):
    rnd = random.Random(seed)
    d = radius_px * 2 + 10
    s = pygame.Surface((d, d), pygame.SRCALPHA)
    c = d // 2
    pygame.draw.circle(s, (70, 71, 76, 255), (c, c), radius_px)
    pygame.draw.circle(s, (92, 93, 98, 255), (c + radius_px // 8, c + radius_px // 8), int(radius_px * 0.8))
    pygame.draw.circle(s, (150, 151, 156, 255), (c, c), radius_px, max(2, radius_px // 7))      # sunlit rim
    pygame.draw.arc(s, (50, 51, 56, 255), (c - radius_px, c - radius_px, radius_px * 2, radius_px * 2), 3.6, 5.4, max(2, radius_px // 6))
    return s


def _rock(radius_px, seed):
    rnd = random.Random(seed)
    d = radius_px * 2 + 6
    s = pygame.Surface((d, d), pygame.SRCALPHA)
    c = d // 2
    pts = [(c + radius_px * rnd.uniform(0.7, 1.0) * math.cos(6.283 * i / 8), c + radius_px * rnd.uniform(0.7, 1.0) * math.sin(6.283 * i / 8)) for i in range(8)]
    pygame.draw.polygon(s, (88, 86, 90), pts)
    pygame.draw.polygon(s, (140, 138, 142), [(c + (x - c) * 0.6 - 1, c + (y - c) * 0.6 - 1) for x, y in pts])
    pygame.draw.polygon(s, (50, 49, 54), pts, 2)
    return s


class WorldView:
    def __init__(self):
        self.W, self.H = C.RENDER_W, C.RENDER_H
        self.S = C.PX_PER_M
        self.t = 0.0
        self.tile = _speckle_tile()
        self.rover = Rover(self.S * 2.6)
        self.parts = Particles()
        self.sprites = {}
        self.glows = {k: glow_sprite(46, SAMPLE_COLORS[k], 1.5) for k in KINDS}
        self.track = collections.deque(maxlen=140)
        self.cam = (0.0, 0.0)
        self.dark = 0.0
        self.storm_t = 0.0
        self.shift = (0.0, 0.0)
        self.mode3d = C.VIEW_3D
        self.stars = Starfield()
        self.horizon = int(self.H * C.HORIZON_FRAC)
        self.ground3d = self._ground_gradient()
        self.theta = 270.0

    def _ground_gradient(self):
        h = self.H - self.horizon
        s = pygame.Surface((self.W, h))
        for y in range(h):
            f = (y / h) ** 0.6
            c = (int(60 + 62 * f), int(60 + 63 * f), int(65 + 65 * f))
            pygame.draw.line(s, c, (0, y), (self.W, y))
        return s.convert()

    # ---- 3D projection: x forward, lateral right, from a camera behind and above the rover
    def project(self, x, y):
        """World metres -> (screen x, screen y, depth). depth <= 0.6 means behind the camera."""
        dx, dy = x - self.cam[0], y - self.cam[1]
        a = math.radians(self.theta)
        fwd = dx * math.cos(a) + dy * math.sin(a)
        right = -dx * math.sin(a) + dy * math.cos(a)
        z = fwd + C.CAM_BACK_M
        if z <= 0.6:
            return self.W / 2, self.H, z
        k = C.CAM_FOCAL / z
        return self.W / 2 + right * k, self.horizon + C.CAM_HEIGHT_M * k, z

    # ---- coordinates
    def px(self, x, y):
        if self.mode3d:
            sx, sy, z = self.project(x, y)
            return (sx, sy) if z > 0.6 else (-999, -999)
        return self.W / 2 + (x - self.cam[0]) * self.S, self.H / 2 + (y - self.cam[1]) * self.S

    def update(self, dt, game, speed01):
        self.t += dt
        self.rover.update(dt)
        c = game.craft
        self.cam = (c.x, c.y)
        self.theta = c.theta
        self.stars.update(dt)
        self.parts.update(dt)
        h = game.thermal.local_hour()                              # dusk and dawn fade over one lunar hour
        target = max(0.0, 1.0 - min(abs(h - 6.0), abs(h - 18.0))) if game.thermal.daylight() else 1.0
        self.dark += (target - self.dark) * min(1.0, dt * 2.0)
        self.storm_t = self.storm_t + dt if game.storm else 0.0
        if speed01 > 0.05 and not game.over:
            if not self.track or math.hypot(self.track[-1][0] - c.x, self.track[-1][1] - c.y) > 0.5:
                a = math.radians(c.theta + 90)
                self.track.append((c.x - math.cos(math.radians(c.theta)) * 1.2 + math.cos(a) * 0.7, c.y - math.sin(math.radians(c.theta)) * 1.2 + math.sin(a) * 0.7,
                                   c.x - math.cos(math.radians(c.theta)) * 1.2 - math.cos(a) * 0.7, c.y - math.sin(math.radians(c.theta)) * 1.2 - math.sin(a) * 0.7))
            a = math.radians(c.theta + 180)
            sx, sy = self.px(c.x, c.y)
            self.parts.emit(sx + math.cos(a) * self.S * 1.4, sy + math.sin(a) * self.S * 1.4, 1, [(150, 150, 155), (120, 120, 125)],
                            40, (0.4, 0.9), (2, 4), 1.0, a, drag=2.0)

    def fx(self, game, e, shake, audio):
        kind, x, y, extra = e
        if kind == "pickup":
            sx, sy = self.px(x, y)
            col = SAMPLE_COLORS.get(extra, K.WHITE)
            self.parts.emit(sx, sy, 36, [col, K.WHITE], 220, (0.3, 0.9), (2, 5), drag=1.4)
            self.parts.ring(sx, sy, 90, col, 0.5)
        elif kind == "hit":
            sx, sy = self.px(game.craft.x, game.craft.y)
            self.parts.emit(sx, sy, 70, [K.ORANGE, K.YELLOW, K.RED, K.WHITE], 320, (0.4, 1.1), (2, 5), drag=1.6)
            self.parts.ring(sx, sy, 220, K.ORANGE)
            shake.add(18)
        elif kind == "heart":
            shake.add(8)

    # ---- drawing
    def draw_ground(self, surf):
        ts = self.tile.get_width()
        ox, oy = -(self.cam[0] * self.S) % ts, -(self.cam[1] * self.S) % ts
        for x in range(-ts + int(ox), self.W, ts):
            for y in range(-ts + int(oy), self.H, ts):
                surf.blit(self.tile, (x, y))
        x0, y0 = self.cam[0] - self.W / 2 / self.S - 6, self.cam[1] - self.H / 2 / self.S - 6
        x1, y1 = self.cam[0] + self.W / 2 / self.S + 6, self.cam[1] + self.H / 2 / self.S + 6
        for cx in range(math.floor(x0 / CELL_M), math.floor(x1 / CELL_M) + 1):
            for cy in range(math.floor(y0 / CELL_M), math.floor(y1 / CELL_M) + 1):
                rnd = random.Random(cx * 73856093 ^ cy * 19349663)
                for _ in range(rnd.choice((0, 1, 1, 2))):
                    r = rnd.uniform(0.9, 4.2)
                    wx, wy = (cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M
                    key = ("c", int(r * self.S), rnd.randrange(6))
                    if key not in self.sprites:
                        self.sprites[key] = _crater(int(r * self.S), key[2])
                    img = self.sprites[key]
                    sx, sy = self.px(wx, wy)
                    surf.blit(img, (sx - img.get_width() / 2, sy - img.get_height() / 2))
                for _ in range(rnd.choice((1, 2, 3))):
                    r = rnd.uniform(0.25, 0.7)
                    wx, wy = (cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M
                    key = ("r", int(r * self.S), rnd.randrange(6))
                    if key not in self.sprites:
                        self.sprites[key] = _rock(int(r * self.S), key[2])
                    img = self.sprites[key]
                    sx, sy = self.px(wx, wy)
                    surf.blit(img, (sx - img.get_width() / 2, sy - img.get_height() / 2))

    def draw_tracks(self, surf):
        for ax, ay, bx, by in self.track:
            pygame.draw.line(surf, (84, 85, 90), self.px(ax, ay), self.px(bx, by), 2)

    def draw_sample(self, surf, game):
        s = game.sample
        if not s:
            return
        x, y = self.px(s["x"], s["y"])
        if -60 < x < self.W + 60 and -60 < y < self.H + 60:
            col = SAMPLE_COLORS[s["kind"]]
            pulse = 0.5 + 0.5 * math.sin(self.t * 4)
            g = self.glows[s["kind"]]
            surf.blit(g, (x - g.get_width() / 2, y - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
            r = int(self.S * 0.7 * (1 + 0.1 * pulse))
            pygame.draw.polygon(surf, col, [(x, y - r), (x + r * 0.8, y), (x, y + r), (x - r * 0.8, y)])
            pygame.draw.polygon(surf, K.WHITE, [(x, y - r), (x + r * 0.8, y), (x, y + r), (x - r * 0.8, y)], 2)
            pygame.draw.circle(surf, col, (int(x), int(y)), int(C.SAMPLE_PICKUP_M * self.S), 1)
        else:                                                    # off screen: a marker on the screen edge
            a = math.atan2(y - self.H / 2, x - self.W / 2)
            ex = self.W / 2 + math.cos(a) * (self.H / 2 - 40) * 1.6
            ey = self.H / 2 + math.sin(a) * (self.H / 2 - 40)
            ex, ey = max(30, min(self.W - 30, ex)), max(30, min(self.H - 30, ey))
            pygame.draw.circle(surf, SAMPLE_COLORS[s["kind"]], (int(ex), int(ey)), 12)
            pygame.draw.circle(surf, K.WHITE, (int(ex), int(ey)), 12, 2)

    def draw_light(self, surf, game):
        if self.dark > 0.01:                                      # lunar night: the surface goes dark and blue
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((6, 10, 34, int(165 * self.dark)))
            surf.blit(ov, (0, 0))
        if game.storm:                                            # radiation storm: violet flicker
            p = 0.5 + 0.5 * math.sin(self.storm_t * 9)
            ov = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            ov.fill((120, 40, 200, int(40 + 40 * p)))
            surf.blit(ov, (0, 0))
            rnd = random.Random(int(self.t * 20))
            for _ in range(10):
                x = rnd.randrange(self.W)
                y = rnd.randrange(self.H)
                pygame.draw.line(surf, (220, 190, 255), (x, y), (x + rnd.randint(-8, 8), y + rnd.randint(10, 34)), 1)

    def draw3d(self, surf, game, ctx):
        """Chase camera: black sky with stars, grey ground with craters and rocks, the rover seen from behind at the bottom centre."""
        W, H, hz = self.W, self.H, self.horizon
        self.stars.draw(surf, (0, 0), (self.theta / 90.0, 0))
        pygame.draw.rect(surf, (0, 0, 0), (0, hz - 2, W, 4))
        surf.fill((0, 0, 0), (0, 0, W, 0))
        surf.blit(self.ground3d, (0, hz))
        pygame.draw.line(surf, (150, 152, 160), (0, hz), (W, hz), 2)
        items = []
        R = 46.0
        cx0, cy0 = self.cam
        for cx in range(math.floor((cx0 - R) / CELL_M), math.floor((cx0 + R) / CELL_M) + 1):
            for cy in range(math.floor((cy0 - R) / CELL_M), math.floor((cy0 + R) / CELL_M) + 1):
                rnd = random.Random(cx * 73856093 ^ cy * 19349663)
                for _ in range(rnd.choice((0, 1, 1, 2))):
                    r = rnd.uniform(0.9, 4.2)
                    wx, wy = (cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M
                    items.append((self.project(wx, wy), "c", r))
                for _ in range(rnd.choice((2, 3, 4))):
                    r = rnd.uniform(0.2, 0.7)
                    wx, wy = (cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M
                    items.append((self.project(wx, wy), "r", r))
        items.sort(key=lambda it: -it[0][2])
        for (sx, sy, z), kind, r in items:
            if z <= 1.0 or z > R * 1.6 or sx < -300 or sx > W + 300:
                continue
            k = C.CAM_FOCAL / z
            w = r * k
            fade = max(0.0, min(1.0, 1.0 - (z - 25.0) / 35.0))
            if kind == "c":
                h = max(2.0, w * C.CAM_HEIGHT_M / math.hypot(z, C.CAM_HEIGHT_M) * 1.0)
                rect = pygame.Rect(0, 0, int(w * 2), int(h * 2))
                rect.center = (int(sx), int(sy))
                shade = lambda v: int(v * (0.55 + 0.45 * fade) + 112 * (1 - fade) * 0.0)
                pygame.draw.ellipse(surf, (shade(66), shade(67), shade(72)), rect)
                inner = rect.inflate(-rect.w * 0.18, -rect.h * 0.18)
                pygame.draw.ellipse(surf, (shade(88), shade(89), shade(94)), inner.move(0, int(rect.h * 0.04)))
                pygame.draw.ellipse(surf, (shade(150), shade(152), shade(158)), rect, max(1, int(w * 0.05)))
            else:
                rw, rh = max(2, int(w * 1.3)), max(2, int(w * 0.9))
                body = pygame.Rect(0, 0, rw, rh)
                body.midbottom = (int(sx), int(sy))
                pygame.draw.ellipse(surf, (int(84 * (0.6 + 0.4 * fade)),) * 3, body)
                pygame.draw.ellipse(surf, (int(138 * (0.6 + 0.4 * fade)),) * 3, body.inflate(-rw * 0.4, -rh * 0.4).move(-rw // 10, -rh // 8))
        if not ctx.get("backdrop"):
            self.draw_sample3d(surf, game)
        if not ctx.get("hide_craft") and not ctx.get("backdrop"):
            self.rover.draw_back(surf, W / 2, H * 0.68, 170, not game.thermal.daylight() or self.dark > 0.2, self.t)
        self.parts.draw(surf)
        self.draw_light(surf, game)

    def draw_sample3d(self, surf, game):
        s = game.sample
        if not s:
            return
        sx, sy, z = self.project(s["x"], s["y"])
        col = SAMPLE_COLORS[s["kind"]]
        if z > 1.0 and -80 < sx < self.W + 80:
            k = C.CAM_FOCAL / z
            r = max(5, int(0.9 * k))
            lift = int(r * 1.2 + 4 * math.sin(self.t * 4))
            g = pygame.transform.smoothscale(self.glows[s["kind"]], (r * 3, r * 3))
            surf.blit(g, (sx - g.get_width() / 2, sy - lift - g.get_height() / 2))
            pts = [(sx, sy - lift - r), (sx + r * 0.8, sy - lift), (sx, sy - lift + r), (sx - r * 0.8, sy - lift)]
            pygame.draw.polygon(surf, col, pts)
            pygame.draw.polygon(surf, K.WHITE, pts, 2)
            ring = pygame.Rect(0, 0, int(C.SAMPLE_PICKUP_M * 2 * k), int(C.SAMPLE_PICKUP_M * 2 * k * 0.35))
            ring.center = (int(sx), int(sy))
            pygame.draw.ellipse(surf, col, ring, 2)
        else:                                                    # off screen: marker on the screen edge
            ex = 40 if sx < 0 or z <= 1.0 and game.sample_bearing() < 0 else self.W - 40
            pygame.draw.circle(surf, col, (ex, int(self.H * 0.5)), 12)
            pygame.draw.circle(surf, K.WHITE, (ex, int(self.H * 0.5)), 12, 2)

    def draw(self, surf, game, ctx):
        """ctx: dict(ap_on, speed01, shake, hide_craft, backdrop)."""
        if self.mode3d:
            return self.draw3d(surf, game, ctx)
        self.draw_ground(surf)
        self.draw_tracks(surf)
        if not ctx.get("backdrop"):
            self.draw_sample(surf, game)
        if not ctx.get("hide_craft") and not ctx.get("backdrop"):
            x, y = self.px(game.craft.x, game.craft.y)
            self.rover.draw_top(surf, x, y, game.craft.theta, self.S * 2.6, lights=not game.thermal.daylight() or self.dark > 0.2)
        self.parts.draw(surf)
        self.draw_light(surf, game)

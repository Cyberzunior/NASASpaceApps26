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
from gfx.rover import Rover, glow_add, glow_sprite
from gfx.widgets import overlay

SAMPLE_COLORS = {"ice": (140, 225, 255), "regolith": (225, 150, 80), "mineral": (230, 110, 255)}
CELL_M = 14.0
EARTH_AZ = 296.0            # world bearing of the Earth in the sky (the rover starts facing 270)


def make_earth(d=150):
    """The blue home planet hanging in the lunar sky: disc, soft clouds, night side, thin atmosphere. Drawn 3x and scaled down."""
    D = d * 3
    s = pygame.Surface((D, D), pygame.SRCALPHA)
    c, r = D // 2, D // 2 - 12
    rnd = random.Random(3)
    pygame.draw.circle(s, (120, 180, 255, 60), (c, c), r + 9)                 # atmosphere rim
    pygame.draw.circle(s, (26, 74, 170), (c, c), r)
    land = pygame.Surface((D, D), pygame.SRCALPHA)
    for _ in range(9):                                                        # continents
        x, y = c + rnd.uniform(-r, r) * 0.8, c + rnd.uniform(-r, r) * 0.8
        for _ in range(7):
            pygame.draw.ellipse(land, (52, 128, 84), (x + rnd.uniform(-r, r) * 0.2, y + rnd.uniform(-r, r) * 0.16, r * rnd.uniform(0.16, 0.42), r * rnd.uniform(0.1, 0.3)))
    for _ in range(26):                                                       # cloud bands
        x, y = c + rnd.uniform(-r, r), c + rnd.uniform(-r, r)
        pygame.draw.ellipse(land, (236, 242, 250, 150), (x, y, r * rnd.uniform(0.3, 0.9), r * rnd.uniform(0.04, 0.12)))
    mask = pygame.Surface((D, D), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (c, c), r)
    land.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    s.blit(land, (0, 0))
    night = pygame.Surface((D, D), pygame.SRCALPHA)                           # the unlit part: an offset dark disc
    pygame.draw.circle(night, (2, 4, 12, 236), (c, c), r + 2)
    pygame.draw.circle(night, (0, 0, 0, 0), (int(c - r * 0.62), int(c - r * 0.34)), int(r * 1.16))
    night.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    s.blit(night, (0, 0))
    return pygame.transform.smoothscale(s, (d, d))


KEY = (255, 0, 255)


def _ridge(width, height, seed, base, crest):
    """A 360 degree mountain silhouette that wraps seamlessly (a sum of whole-period sines) with a sunlit crest line."""
    rnd = random.Random(seed)
    waves = [(n, rnd.uniform(0, 6.283), rnd.uniform(0.5, 1.0) / n ** 0.9) for n in (2, 3, 5, 8, 11, 17, 26, 39, 61)]
    tot = sum(a for _, _, a in waves)
    pts = []
    for x in range(0, width + 4, 4):
        u = 6.283 * x / width
        v = 0.5 + 0.5 * sum(a * math.sin(n * u + ph) for n, ph, a in waves) / tot * 2.2
        pts.append((x, height - 4 - (height - 8) * max(0.0, min(1.0, v))))
    big = pygame.Surface((width, height))
    big.fill(KEY)                                                 # magenta is the transparent colour: colour-key blits are much faster than alpha
    pygame.draw.polygon(big, crest, [(0, height)] + pts + [(width + 4, height)])
    pygame.draw.polygon(big, base, [(0, height)] + [(x, y + 3) for x, y in pts] + [(width + 4, height)])
    big.set_colorkey(KEY)
    return big.convert()


def _horizon_glow(w, h, color):
    """Soft band of light for the sunlit limb, added over the sky just above the horizon."""
    col = pygame.Surface((1, h))
    for y in range(h):
        f = (y / (h - 1)) ** 2.4
        col.set_at((0, y), (int(color[0] * f), int(color[1] * f), int(color[2] * f)))
    return pygame.transform.scale(col, (w, h)).convert()


def _beam(color, w=56, h=420):
    """A column of light above a sample so it reads from far away (opaque on black, blitted with ADD)."""
    s = pygame.Surface((w, h))
    for x in range(w):
        fx = 1.0 - abs(x - w / 2 + 0.5) / (w / 2)
        for y in range(0, h, 4):
            f = fx ** 2.2 * (y / h) ** 1.5 * 0.55
            pygame.draw.line(s, (int(color[0] * f), int(color[1] * f), int(color[2] * f)), (x, y), (x, y + 3))
    return s.convert()


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


_cell_cache = {}


def cell_items(cx, cy):
    """Craters and rocks in one CELL_M square: (world x, world y, kind, radius m, variant). Cached, the layout never changes."""
    key = (cx, cy)
    out = _cell_cache.get(key)
    if out is None:
        if len(_cell_cache) > 6000:
            _cell_cache.clear()
        rnd = random.Random(cx * 73856093 ^ cy * 19349663)
        items = []
        for _ in range(rnd.choice((0, 1, 1, 2))):
            r = rnd.uniform(0.9, 4.2)
            items.append(((cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M, "c", r, rnd.randrange(6)))
        for _ in range(rnd.choice((2, 3, 4))):
            r = rnd.uniform(0.25, 0.7)
            items.append(((cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M, "r", r, rnd.randrange(6)))
        out = _cell_cache[key] = tuple(items)
    return out


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
        self.impact_fill = {}
        self.px_per_deg = C.CAM_FOCAL * math.pi / 180.0
        pano = int(360 * self.px_per_deg)
        self.ridge_far = _ridge(pano, 84, 21, (50, 51, 58), (104, 106, 116))
        self.ridge_near = _ridge(pano, 40, 8, (66, 67, 74), (132, 134, 144))
        self.earth = make_earth(150).convert_alpha()
        self.earth_glow = glow_add(170, (40, 80, 170), 2.6)
        self.limb = _horizon_glow(self.W, 70, (34, 40, 58))
        self.beams = {k: _beam(SAMPLE_COLORS[k]) for k in KINDS}
        self.glows_add = {k: glow_add(70, K.mix(SAMPLE_COLORS[k], (0, 0, 0), 0.35), 1.8) for k in KINDS}

    def _ground_gradient(self):
        """Regolith from the hazy far field to the lit foreground, with faint large-scale mottling."""
        h = self.H - self.horizon
        s = pygame.Surface((self.W, h))
        for y in range(h):
            f = (y / h) ** 0.55
            c = (int(74 + 58 * f), int(75 + 58 * f), int(82 + 56 * f))
            pygame.draw.line(s, c, (0, y), (self.W, y))
        rnd = random.Random(12)
        mot = pygame.Surface((self.W, h))
        mot.fill((8, 8, 8))
        for _ in range(260):                                                  # darker and lighter patches, flatter far away
            y = h * rnd.random() ** 1.8
            k = 0.15 + 0.85 * y / h
            v = rnd.randint(0, 16)
            pygame.draw.ellipse(mot, (v, v, v), (rnd.uniform(-0.1, 1.0) * self.W, y, rnd.uniform(120, 520) * k, rnd.uniform(10, 46) * k))
        small = pygame.transform.smoothscale(mot, (self.W // 6, h // 6))      # blur the patches
        s.blit(pygame.transform.smoothscale(small, (self.W, h)), (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        s.fill((8, 8, 8), special_flags=pygame.BLEND_RGB_SUB)
        return s.convert()

    def _wrap_strip(self, surf, img, x, y):
        """Blit a 360 degree panorama strip so it wraps around the screen."""
        w = img.get_width()
        x = int(x) % w - w
        while x < self.W:
            if x + w > 0:
                surf.blit(img, (x, y))
            x += w

    def draw_sky(self, surf):
        W, hz = self.W, self.horizon
        self.stars.draw(surf, (0, 0), (self.theta / 90.0, 0))
        d = (EARTH_AZ - self.theta + 180.0) % 360.0 - 180.0                   # the Earth hangs at a fixed bearing
        if abs(d) < 70:
            ex, ey = W / 2 + d * self.px_per_deg, hz * 0.40
            surf.blit(self.earth_glow, (ex - self.earth_glow.get_width() / 2, ey - self.earth_glow.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
            surf.blit(self.earth, (ex - self.earth.get_width() / 2, ey - self.earth.get_height() / 2))
        surf.blit(self.limb, (0, hz - self.limb.get_height()), special_flags=pygame.BLEND_RGB_ADD)
        off = W / 2 - self.theta * self.px_per_deg
        self._wrap_strip(surf, self.ridge_far, off * 0.999, hz - self.ridge_far.get_height() + 2)
        self._wrap_strip(surf, self.ridge_near, off + 900, hz - self.ridge_near.get_height() + 2)

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
                for wx, wy, kind, r, var in cell_items(cx, cy):
                    key = (kind, int(r * self.S), var)
                    img = self.sprites.get(key)
                    if img is None:
                        img = self.sprites[key] = _crater(int(r * self.S), var) if kind == "c" else _rock(int(r * self.S), var)
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
            g = self.glows_add[s["kind"]]
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
            overlay(surf, (6, 10, 34), 165 * self.dark)
        if game.storm:                                            # radiation storm: violet flicker
            p = 0.5 + 0.5 * math.sin(self.storm_t * 9)
            overlay(surf, (120, 40, 200), 40 + 40 * p)
            rnd = random.Random(int(self.t * 20))
            for _ in range(10):
                x = rnd.randrange(self.W)
                y = rnd.randrange(self.H)
                pygame.draw.line(surf, (220, 190, 255), (x, y), (x + rnd.randint(-8, 8), y + rnd.randint(10, 34)), 1)

    def draw3d(self, surf, game, ctx):
        """Chase camera: black sky with stars, grey ground with craters and rocks, the rover seen from behind at the bottom centre."""
        W, H, hz = self.W, self.H, self.horizon
        self.draw_sky(surf)
        surf.blit(self.ground3d, (0, hz))
        items = []
        R = 46.0
        cx0, cy0 = self.cam
        for cx in range(math.floor((cx0 - R) / CELL_M), math.floor((cx0 + R) / CELL_M) + 1):
            for cy in range(math.floor((cy0 - R) / CELL_M), math.floor((cy0 + R) / CELL_M) + 1):
                for wx, wy, kind, r, _var in cell_items(cx, cy):
                    items.append((self.project(wx, wy), kind, r))
        items.sort(key=lambda it: -it[0][2])
        for (sx, sy, z), kind, r in items:
            if z <= 1.0 or z > R * 1.6 or sx < -300 or sx > W + 300:
                continue
            k = C.CAM_FOCAL / z
            w = r * k
            fade = max(0.0, min(1.0, 1.0 - (z - 25.0) / 35.0))
            g = 76 + 56 * max(0.0, min(1.0, (sy - hz) / (H - hz))) ** 0.55                 # ground brightness at this depth
            if kind == "c":
                h = max(2.0, w * C.CAM_HEIGHT_M / math.hypot(z, C.CAM_HEIGHT_M))
                rect = pygame.Rect(0, 0, int(w * 2), int(h * 2))
                rect.center = (int(sx), int(sy))
                if rect.w < 6:
                    continue
                rim = rect.inflate(int(rect.w * 0.16), int(rect.h * 0.22))
                pygame.draw.ellipse(surf, (int(g + 26 * fade),) * 3, rim.move(0, int(rect.h * 0.05)))            # raised sunlit rim
                pygame.draw.ellipse(surf, (int(g - 34 * fade), int(g - 34 * fade), int(g - 30 * fade)), rect)   # shadowed wall
                floor = rect.inflate(-int(rect.w * 0.22), -int(rect.h * 0.30))
                pygame.draw.ellipse(surf, (int(g - 12 * fade),) * 3, floor.move(int(rect.w * 0.05), int(rect.h * 0.12)))
            else:
                rw, rh = max(2, int(w * 1.3)), max(2, int(w * 0.9))
                body = pygame.Rect(0, 0, rw, rh)
                body.midbottom = (int(sx), int(sy))
                if rw > 5:                                                                  # cast shadow, down-right
                    pygame.draw.ellipse(surf, (int(g - 30 * fade),) * 3, (body.left + rw * 0.18, body.bottom - rh * 0.30, rw * 1.15, rh * 0.42))
                pygame.draw.ellipse(surf, (int(g - 38 * fade), int(g - 38 * fade), int(g - 34 * fade)), body)
                pygame.draw.ellipse(surf, (int(g + 22 * fade),) * 3, body.inflate(-rw * 0.42, -rh * 0.45).move(-rw // 9, -rh // 7))
        if not ctx.get("backdrop"):
            self.draw_impact(surf, game)
            self.draw_sample3d(surf, game)
        if not ctx.get("hide_craft") and not ctx.get("backdrop"):
            self.rover.draw_back(surf, W / 2, H * 0.68, 170, not game.thermal.daylight() or self.dark > 0.2, self.t)
        self.parts.draw(surf)
        self.draw_light(surf, game)

    def draw_impact(self, surf, game):
        """The impact zone: a ring on the ground where the rock lands. It starts wide and closes in as the countdown runs out."""
        st = game.strike
        if not st or st["phase"] != "warn" or "x" not in st:
            return
        left = max(0.0, st["left"])
        frac = left / C.STRIKE_WARN_S if st["mode"] == "own" else min(1.0, left / C.STRIKE_WARN_S)
        r = C.STRIKE_RADIUS_M * (0.35 + 0.65 * frac)
        pulse = 0.5 + 0.5 * math.sin(self.t * (5.0 + 10.0 * (1.0 - frac)))
        col = K.mix(K.ORANGE, K.RED, 1.0 - frac)
        pts, box = [], [1e9, 1e9, -1e9, -1e9]
        for i in range(40):
            a = i * math.tau / 40
            p = self._ground_pt(st["x"] + math.cos(a) * r, st["y"] + math.sin(a) * r)
            if p is None:
                return
            pts.append(p)
            box = [min(box[0], p[0]), min(box[1], p[1]), max(box[2], p[0]), max(box[3], p[1])]
        w, h = int(box[2] - box[0]) + 2, int(box[3] - box[1]) + 2
        if w > 4 and h > 2:                                                    # soft fill, faded in and out with the pulse
            key = ("impact", min(w, 1400) // 6, min(h, 900) // 6, tuple(col))
            fill = self.impact_fill.get(key)
            if fill is None:
                if len(self.impact_fill) > 60:
                    self.impact_fill.clear()
                fill = self.impact_fill[key] = pygame.Surface((key[1] * 6 + 2, key[2] * 6 + 2), pygame.SRCALPHA)
                pygame.draw.ellipse(fill, (*col, 255), fill.get_rect())
            fill.set_alpha(int(38 + 40 * pulse))
            surf.blit(fill, (box[0], box[1]))
        pygame.draw.lines(surf, col, True, pts, 3)
        inner = [self._ground_pt(st["x"] + math.cos(a) * r * 0.45, st["y"] + math.sin(a) * r * 0.45) for a in (i * math.tau / 16 for i in range(16))]
        if all(inner):
            pygame.draw.lines(surf, K.mix(col, K.WHITE, 0.4), True, inner, 1)
        c = self._ground_pt(st["x"], st["y"])
        if c:
            pygame.draw.line(surf, K.mix(col, K.WHITE, 0.4), (c[0] - 12, c[1]), (c[0] + 12, c[1]), 2)
            pygame.draw.line(surf, K.mix(col, K.WHITE, 0.4), (c[0], c[1] - 12), (c[0], c[1] + 12), 2)

    def _ground_pt(self, x, y):
        """World metres -> screen point, or None when the point is behind or outside the screen."""
        if self.mode3d:
            sx, sy, z = self.project(x, y)
            if z <= 1.0:
                return None
            return sx, sy
        sx, sy = self.px(x, y)
        return sx, sy

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
            ring0 = pygame.Rect(0, 0, int(r * 2.2), int(r * 0.7))                          # contact shadow
            ring0.center = (int(sx), int(sy))
            pygame.draw.ellipse(surf, (58, 59, 66), ring0)
            b = self.beams[s["kind"]]
            surf.blit(b, (sx - b.get_width() / 2, sy - lift - b.get_height()), special_flags=pygame.BLEND_RGB_ADD)
            g = self.glows_add[s["kind"]]
            surf.blit(g, (sx - g.get_width() / 2, sy - lift - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
            pts = [(sx, sy - lift - r), (sx + r * 0.8, sy - lift), (sx, sy - lift + r), (sx - r * 0.8, sy - lift)]
            pygame.draw.polygon(surf, col, pts)
            pygame.draw.polygon(surf, K.mix(col, (0, 0, 0), 0.35), [pts[1], pts[2], (sx, sy - lift)])            # facets
            pygame.draw.polygon(surf, K.mix(col, K.WHITE, 0.55), [pts[0], pts[3], (sx, sy - lift)])
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
            self.draw_impact(surf, game)
            self.draw_sample(surf, game)
        if not ctx.get("hide_craft") and not ctx.get("backdrop"):
            x, y = self.px(game.craft.x, game.craft.y)
            self.rover.draw_top(surf, x, y, game.craft.theta, self.S * 2.6, lights=not game.thermal.daylight() or self.dark > 0.2)
        self.parts.draw(surf)
        self.draw_light(surf, game)

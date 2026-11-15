"""Draws the lunar surface seen from above: grey regolith with craters and rocks, the rover, the current sample,
tyre tracks, the day and night light and the radiation storm tint. The camera follows the rover."""
import collections
import math
import random
import pygame
import config as C
from core.game import KINDS
from core.model import angdiff
from gfx import fonts, palette as K
from gfx.particles import Particles
from gfx.perf import PERF
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


ROVER_W_M = 1.55            # body width of the rover sprite in world metres
G_MOON = 1.62               # m/s2. No air on the Moon: dust and debris fly in slow, clean ballistic arcs
METEOR_S = 1.1              # the incoming rock is visible for the last 1.1 s of the warning
_speck_cache = {}


def cell_specks(cx, cy):
    """Pebbles too small to be rocks: (x, y, shade). They give the ground visible motion when the rover drives."""
    key = (cx, cy)
    out = _speck_cache.get(key)
    if out is None:
        if len(_speck_cache) > 6000:
            _speck_cache.clear()
        rnd = random.Random(cx * 83492791 ^ cy * 39916801)
        out = _speck_cache[key] = tuple(((cx + rnd.random()) * CELL_M, (cy + rnd.random()) * CELL_M, rnd.choice((-20, -14, 14, 20)))
                                        for _ in range(12))
    return out


def _ease_out_back(x):
    """0..1 with a small overshoot at the end (things that pop into place)."""
    x = max(0.0, min(1.0, x)) - 1.0
    return 1.0 + x * x * (2.70158 * x + 1.70158)


class WorldView:
    def __init__(self):
        self.W, self.H = C.RENDER_W, C.RENDER_H
        self.S = C.PX_PER_M
        self.t = 0.0
        self.tile = _speckle_tile()
        self.rover = Rover(self.S * 2.6, quant=2)
        self.parts = Particles()
        self.sprites = {}
        self.glows = {k: glow_sprite(46, SAMPLE_COLORS[k], 1.5) for k in KINDS}
        self.track = collections.deque(maxlen=140)
        self.cam = (0.0, 0.0)
        self.dark = 0.0
        self.storm_t = 0.0
        self.shift = (0.0, 0.0)
        self.mode3d = C.VIEW_3D
        self.horizon = int(self.H * C.HORIZON_FRAC)
        self.stars = Starfield(self.W, self.horizon + 4)          # only the sky strip: the ground covers the rest
        self.stars.drift = 0.0
        self.ground3d = self._ground_gradient()
        gh = self.H - self.horizon
        self.gshade = [int(76 + 56 * (y / gh) ** 0.55) for y in range(gh + 1)]      # ground brightness per screen row
        self.theta = 270.0
        self.ca, self.sa = math.cos(math.radians(270.0)), math.sin(math.radians(270.0))
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
        self.meteor_glow = glow_add(54, (255, 170, 90), 1.7)
        self.flash_cache = {}
        self.pool = {}
        # motion state
        self.snap = True                  # next update jumps the camera straight to the rover (new run)
        self.prev_theta = 270.0
        self.turn_rate = 0.0              # deg/s, smoothed
        self.lean = 0.0
        self.speed01 = 0.0
        self.dust_acc = 0.0
        # world-anchored effects (they stay put on the ground while the camera moves)
        self.wparts = []                  # [x, y, h, vx, vy, vh, age, life, size m, colour0, colour1, die on landing, additive]
        self.rings3 = []                  # [x, y, age, life, max radius m, colour]
        self.flashes = []                 # [x, y, h, age, life, radius m, colour]
        self.floaters = []                # [x, y, text, colour, age]
        self.scars = collections.deque(maxlen=8)                  # (x, y, radius m): scorch marks left by impacts

    def reset_fx(self):
        """A new run: forget every effect and put the camera back on the rover."""
        self.wparts.clear()
        self.rings3.clear()
        self.flashes.clear()
        self.floaters.clear()
        self.scars.clear()
        self.track.clear()
        self.parts.p.clear()
        self.parts.rings.clear()
        self.snap = True

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
        self.stars.draw(surf, pan=-self.theta * self.px_per_deg)              # the whole sky turns with the heading
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
    def project(self, x, y, h=0.0):
        """World metres (h = height above the ground) -> (screen x, screen y, depth). depth <= 0.6 means behind the camera."""
        dx, dy = x - self.cam[0], y - self.cam[1]
        z = dx * self.ca + dy * self.sa + C.CAM_BACK_M
        if z <= 0.6:
            return self.W / 2, self.H, z
        k = C.CAM_FOCAL / z
        return self.W / 2 + (dy * self.ca - dx * self.sa) * k, self.horizon + (C.CAM_HEIGHT_M - h) * k, z

    def _wp(self, x, y, h=0.0):
        """World point -> (screen x, screen y, pixels per metre there). Pixels per metre is 0 when the point cannot be seen."""
        if self.mode3d:
            sx, sy, z = self.project(x, y, h)
            return (sx, sy, C.CAM_FOCAL / z) if z > 1.0 else (sx, sy, 0.0)
        return self.W / 2 + (x - self.cam[0]) * self.S, self.H / 2 + (y - self.cam[1]) * self.S - h * self.S * 0.6, self.S

    # ---- coordinates
    def px(self, x, y):
        if self.mode3d:
            sx, sy, z = self.project(x, y)
            return (sx, sy) if z > 0.6 else (-999, -999)
        return self.W / 2 + (x - self.cam[0]) * self.S, self.H / 2 + (y - self.cam[1]) * self.S

    # ---- world-anchored effects
    def _spawn(self, x, y, h, vx, vy, vh, life, size, c0, c1, land_dies=True, add=False):
        if len(self.wparts) < PERF.k["wparts"]:
            self.wparts.append([x, y, h, vx, vy, vh, 0.0, life, size, c0, c1, land_dies, add])

    def blast(self, x, y, power=1.0):
        """An impact: flash, two ground shock rings, glowing ejecta and regolith thrown on long lunar arcs, a scorch mark."""
        self.flashes.append([x, y, 1.0, 0.0, 0.5, 9.0 * power, (255, 196, 120)])
        self.rings3.append([x, y, 0.0, 0.9, 14.0 * power, K.ORANGE])
        self.rings3.append([x, y, 0.0, 1.7, 8.0 * power, (176, 176, 184)])
        for _ in range(int(46 * power)):                                      # hot fragments
            a, v = random.uniform(0, math.tau), random.uniform(1.0, 8.0)
            self._spawn(x, y, 0.3, math.cos(a) * v, math.sin(a) * v, random.uniform(2.0, 9.0), random.uniform(1.2, 3.2),
                        random.uniform(0.035, 0.085), random.choice((K.YELLOW, K.ORANGE, K.WHITE, (255, 120, 60))), (200, 70, 30), True, True)
        for _ in range(int(40 * power)):                                      # grey regolith
            a, v = random.uniform(0, math.tau), random.uniform(0.6, 5.0)
            self._spawn(x, y, 0.2, math.cos(a) * v, math.sin(a) * v, random.uniform(1.5, 6.5), 6.0,
                        random.uniform(0.03, 0.065), (186, 186, 192), (128, 129, 135), True, False)
        self.scars.append((x, y, 1.3 * power))

    def fx(self, game, e, shake, audio):
        kind, x, y, extra = e
        if kind == "pickup":
            col = SAMPLE_COLORS.get(extra, K.WHITE)
            for _ in range(30):                                               # the crystal bursts into sparks
                a, v = random.uniform(0, math.tau), random.uniform(0.5, 3.4)
                self._spawn(x, y, 1.0, math.cos(a) * v, math.sin(a) * v, random.uniform(1.0, 4.2), random.uniform(0.6, 1.5),
                            random.uniform(0.03, 0.06), K.mix(col, K.WHITE, random.random() * 0.6), col, True, True)
            self.rings3.append([x, y, 0.0, 0.55, 4.5, col])
            self.flashes.append([x, y, 1.0, 0.0, 0.3, 3.2, K.mix(col, K.WHITE, 0.3)])
            self.floaters.append([x, y, "+1 " + str(extra).upper(), col, 0.0])
        elif kind in ("hit", "asteroid_miss"):
            if not x and not y:                                               # no impact point given: on the rover
                x, y = game.craft.x, game.craft.y
            self.blast(x, y, 1.0)
            d = math.hypot(x - game.craft.x, y - game.craft.y)
            shake.add(18 if kind == "hit" else 3 + 11 * math.exp(-d / 14.0))    # the ground shakes less far from the impact
        elif kind == "heart":
            shake.add(8)

    def update(self, dt, game, speed01):
        self.t += dt
        self.rover.update(dt)
        c = game.craft
        if self.snap or math.hypot(c.x - self.cam[0], c.y - self.cam[1]) > 6.0:
            self.cam, self.theta, self.prev_theta, self.snap = (c.x, c.y), c.theta, c.theta, False
            self.turn_rate = self.lean = 0.0
        else:                                                     # the camera follows on a soft spring: the rover pulls ahead, the view catches up
            k = 1.0 - math.exp(-dt * 9.0)
            self.cam = (self.cam[0] + (c.x - self.cam[0]) * k, self.cam[1] + (c.y - self.cam[1]) * k)
            self.theta = (self.theta + angdiff(c.theta, self.theta) * (1.0 - math.exp(-dt * 8.0))) % 360.0
        if dt > 1e-6:
            self.turn_rate += (angdiff(c.theta, self.prev_theta) / dt - self.turn_rate) * min(1.0, dt * 6.0)
        self.prev_theta = c.theta
        self.speed01 += (speed01 - self.speed01) * min(1.0, dt * 8.0)
        self.lean += (max(-3.5, min(3.5, self.turn_rate * 0.04)) * (0.35 + 0.65 * self.speed01) - self.lean) * min(1.0, dt * 7.0)
        a = math.radians(self.theta)
        self.ca, self.sa = math.cos(a), math.sin(a)
        self.stars.update(dt)
        self.parts.update(dt)
        h = game.thermal.local_hour()                              # dusk and dawn fade over one lunar hour
        target = max(0.0, 1.0 - min(abs(h - 6.0), abs(h - 18.0))) if game.thermal.daylight() else 1.0
        self.dark += (target - self.dark) * min(1.0, dt * 2.0)
        self.storm_t = self.storm_t + dt if game.storm else 0.0
        if speed01 > 0.05 and not game.over:                       # wheel ruts, and dust thrown off the wheels
            ha = math.radians(c.theta)
            hx, hy = math.cos(ha), math.sin(ha)
            lx, ly = -hy, hx
            rx, ry = c.x - hx * 0.2, c.y - hy * 0.2
            if not self.track or math.hypot(self.track[-1][0] - rx - lx * 0.8, self.track[-1][1] - ry - ly * 0.8) > 0.5:
                self.track.append((rx + lx * 0.8, ry + ly * 0.8, rx - lx * 0.8, ry - ly * 0.8))
            back = -1.0 if game.speed_ms >= 0 else 1.0
            self.dust_acc += dt * 46.0 * speed01
            while self.dust_acc >= 1.0:
                self.dust_acc -= 1.0
                for side in (0.8, -0.8):
                    v = random.uniform(0.4, 1.9) * (0.4 + speed01)
                    self._spawn(rx + lx * side, ry + ly * side, 0.05, hx * back * v + lx * random.uniform(-0.5, 0.5),
                                hy * back * v + ly * random.uniform(-0.5, 0.5), random.uniform(0.6, 1.9) * (0.5 + 0.5 * speed01), 4.0,
                                random.uniform(0.022, 0.05), (188, 188, 194), (132, 133, 139))
        alive = []
        for p in self.wparts:                                      # ballistic flight under lunar gravity
            p[6] += dt
            if p[6] >= p[7]:
                continue
            p[5] -= G_MOON * dt
            p[0] += p[3] * dt
            p[1] += p[4] * dt
            p[2] += p[5] * dt
            if p[2] < 0.0:
                if p[11]:
                    continue
                p[2], p[3], p[4], p[5] = 0.0, 0.0, 0.0, 0.0
            alive.append(p)
        self.wparts = alive
        for r in self.rings3:
            r[2] += dt
        self.rings3 = [r for r in self.rings3 if r[2] < r[3]]
        for f in self.flashes:
            f[3] += dt
        self.flashes = [f for f in self.flashes if f[3] < f[4]]
        for f in self.floaters:
            f[4] += dt
        self.floaters = [f for f in self.floaters if f[4] < 1.4]

    # ---- drawing: effects
    def draw_wparts(self, surf):
        """Ballistic dust and fragments: round, shrinking as they age (they never fade to dark squares)."""
        W, H, fill, circle = self.W, self.H, surf.fill, pygame.draw.circle
        for p in self.wparts:
            sx, sy, k = self._wp(p[0], p[1], p[2])
            if k <= 0.0 or sx < 0 or sx >= W or sy < 0 or sy >= H:
                continue
            f = p[6] / p[7]
            r = min(7.0, p[8] * k * ((1.0 - f * f) if p[12] else (1.0 - 0.6 * f)))     # capped: a grain next to the lens stays a grain
            if r < 0.6:
                continue
            c0, c1 = p[9], p[10]
            col = (int(c0[0] + (c1[0] - c0[0]) * f), int(c0[1] + (c1[1] - c0[1]) * f), int(c0[2] + (c1[2] - c0[2]) * f))
            if r < 1.6:
                fill(col, (sx, sy, 2, 2))
            else:
                circle(surf, col, (sx, sy), r)

    def draw_rings3(self, surf):
        """Shock rings spreading over the ground (drawn in perspective, so they read as flat on the surface)."""
        for x, y, age, life, max_r, col in self.rings3:
            f = age / life
            r = max_r * (1.0 - (1.0 - f) ** 2.2)
            pts = []
            for i in range(48):
                a = i * math.tau / 48
                sx, sy, k = self._wp(x + math.cos(a) * r, y + math.sin(a) * r)
                if k <= 0.0:
                    pts = None
                    break
                pts.append((sx, sy))
            if pts:
                pygame.draw.lines(surf, K.mix(col, (122, 123, 129), f), True, pts, max(1, int(5 * (1.0 - f))))

    def _flash_img(self, r_px, level, color):
        key = (max(0, min(8, int(r_px) // 60)), level, color)
        img = self.flash_cache.get(key)
        if img is None:
            if len(self.flash_cache) > 48:
                self.flash_cache.clear()
            d = (key[0] + 1) * 120
            img = pygame.transform.smoothscale(glow_add(64, color, 1.6), (d, d))
            if level < 4:
                img.fill((level * 255 // 4,) * 3, special_flags=pygame.BLEND_RGB_MULT)
            self.flash_cache[key] = img
        return img

    def draw_flashes(self, surf):
        for x, y, h, age, life, r_m, col in self.flashes:
            sx, sy, k = self._wp(x, y, h)
            if k <= 0.0:
                continue
            f = age / life
            level = max(1, int(4.99 * (1.0 - f) ** 1.5))
            img = self._flash_img(r_m * k * (0.55 + 0.9 * f), min(4, level), col)
            surf.blit(img, (sx - img.get_width() / 2, sy - img.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)

    def draw_floaters(self, surf):
        for x, y, text, col, age in self.floaters:
            sx, sy, k = self._wp(x, y, 1.6 + age * 1.5)
            if k <= 0.0:
                continue
            pop = _ease_out_back(age / 0.25)
            fonts.text(surf, text, (sx, sy), max(12, int(28 * pop)), K.mix(col, K.WHITE, 0.35), bold=True, anchor="center",
                       alpha=int(255 * (1.0 - max(0.0, (age - 0.7) / 0.7) ** 2)), shadow=True)

    def draw_meteor(self, surf, game):
        """The incoming rock: a fireball that falls onto the impact point over the last second of the warning."""
        st = game.strike
        if not st or st["phase"] != "warn" or "x" not in st or st["left"] > METEOR_S:
            return
        u = 1.0 - max(0.0, st["left"]) / METEOR_S
        ex, ey, k = self._wp(st["x"], st["y"])
        if u >= 1.0 or k <= 0.0:
            return
        side = 1.0 if int(abs(st["x"]) * 7.0) % 2 else -1.0
        x0, y0 = ex + side * 640.0, -70.0
        f = u ** 1.5                                               # it speeds up as it comes down
        add = pygame.BLEND_RGB_ADD
        for i in range(14, 0, -1):                                 # the trail: soft glows, cooler and thinner further back
            fb = f - i * 0.02
            if fb <= 0.0:
                continue
            v = 1.0 - i / 15.0
            g = glow_add(max(4, int((10 + 26 * u) * v) // 2 * 2), (int(255 * v), int(150 * v * v), int(60 * v * v * v)), 1.5)
            surf.blit(g, (x0 + (ex - x0) * fb - g.get_width() / 2, y0 + (ey - y0) * fb - g.get_height() / 2), special_flags=add)
        hx, hy = x0 + (ex - x0) * f, y0 + (ey - y0) * f
        g = self.meteor_glow
        surf.blit(g, (hx - g.get_width() / 2, hy - g.get_height() / 2), special_flags=add)
        pygame.draw.circle(surf, (255, 246, 226), (int(hx), int(hy)), max(3, int(4 + 7 * u)))

    # ---- drawing: top-down map
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
        for x, y, r in self.scars:
            sx, sy = self.px(x, y)
            pygame.draw.circle(surf, (86, 87, 92), (int(sx), int(sy)), int(r * self.S * 1.3))
            pygame.draw.circle(surf, (52, 52, 58), (int(sx), int(sy)), int(r * self.S))

    def draw_tracks(self, surf):
        """Two wheel ruts behind the rover."""
        prev = None
        for cur in self.track:
            if prev is not None and math.hypot(cur[0] - prev[0], cur[1] - prev[1]) < 3.0:
                if self.mode3d:
                    for i in (0, 2):
                        ax, ay, az = self.project(prev[i], prev[i + 1])
                        bx, by, bz = self.project(cur[i], cur[i + 1])
                        if az > 1.0 and bz > 1.0 and az < 60.0:
                            g = self.gshade[max(0, min(len(self.gshade) - 1, int(by) - self.horizon))] - 17
                            pygame.draw.line(surf, (g, g, g + 3), (ax, ay), (bx, by), max(1, int(260.0 / bz)))
                else:
                    for i in (0, 2):
                        pygame.draw.line(surf, (84, 85, 90), self.px(prev[i], prev[i + 1]), self.px(cur[i], cur[i + 1]), 3)
            prev = cur

    def draw_sample(self, surf, game):
        s = game.sample
        if not s:
            return
        x, y = self.px(s["x"], s["y"])
        if -60 < x < self.W + 60 and -60 < y < self.H + 60:
            col = SAMPLE_COLORS[s["kind"]]
            pulse = 0.5 + 0.5 * math.sin(self.t * 4)
            g = self.glows_add[s["kind"]]
            surf.blit(g, (x - g.get_width() / 2, y - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
            r = int(self.S * 0.7 * (1 + 0.1 * pulse) * _ease_out_back(s.get("age", 1.0) / 0.45))
            if r > 1:
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

    def draw_light(self, surf, game, rover_at=None):
        if self.dark > 0.01:                                      # lunar night: the surface goes dark and blue
            a = 0.66 * self.dark                                  # one multiply pass: less than half the cost of an alpha overlay
            surf.fill((int(255 * (1 - a)), int(255 * (1 - a * 0.96)), int(255 * (1 - a * 0.78))), special_flags=pygame.BLEND_RGB_MULT)
            if rover_at is not None and self.dark > 0.2:          # the headlights light a pool of ground ahead
                level = max(1, min(4, int(self.dark * 4.99)))
                img = self.pool.get(level)
                if img is None:
                    img = pygame.transform.smoothscale(glow_add(64, (255, 232, 186), 1.3), (1080, 250))
                    img.fill((level * 150 // 4,) * 3, special_flags=pygame.BLEND_RGB_MULT)
                    self.pool[level] = img
                surf.blit(img, (rover_at[0] - img.get_width() / 2, self.horizon + C.CAM_HEIGHT_M * C.CAM_FOCAL / 17.0 - img.get_height() / 2),
                          special_flags=pygame.BLEND_RGB_ADD)
        if game.storm:                                            # radiation storm: violet flicker
            p = 0.5 + 0.5 * math.sin(self.storm_t * 9)
            overlay(surf, (120, 40, 200), 40 + 40 * p)
            rnd = random.Random(int(self.t * 20))
            for _ in range(10):
                x = rnd.randrange(self.W)
                y = rnd.randrange(self.H)
                pygame.draw.line(surf, (220, 190, 255), (x, y), (x + rnd.randint(-8, 8), y + rnd.randint(10, 34)), 1)

    # ---- drawing: chase camera
    def draw3d(self, surf, game, ctx):
        """Chase camera: black sky with stars, grey ground with craters and rocks, the rover seen from behind at the bottom centre."""
        W, H, hz = self.W, self.H, self.horizon
        gshade, gmax = self.gshade, len(self.gshade) - 1
        fill = surf.fill
        kn = PERF.k
        self.draw_sky(surf)
        surf.blit(self.ground3d, (0, hz))
        cx0, cy0 = self.cam
        ca, sa, focal = self.ca, self.sa, C.CAM_FOCAL
        half, chord = W * 0.5, C.CAM_BACK_M
        ell = pygame.draw.ellipse
        pstep = max(1, int(round(1.0 / max(0.05, kn["pebbles"]))))       # density knob
        R2 = 30.0
        for cx in range(math.floor((cx0 - R2) / CELL_M), math.floor((cx0 + R2) / CELL_M) + 1):     # pebbles: the ground visibly moves
            for cy in range(math.floor((cy0 - R2) / CELL_M), math.floor((cy0 + R2) / CELL_M) + 1):
                for i, (wx, wy, v) in enumerate(cell_specks(cx, cy)):
                    if i % pstep:
                        continue
                    dx, dy = wx - cx0, wy - cy0
                    z = dx * ca + dy * sa + chord
                    if z <= 2.5 or z >= 36.0:
                        continue
                    k = focal / z
                    sx = half + (dy * ca - dx * sa) * k
                    if sx < 0.0 or sx >= W:
                        continue
                    sy = hz + C.CAM_HEIGHT_M * k
                    if sy >= H:
                        continue
                    s = 1 if z > 18.0 else 2 if z > 12.0 else 3
                    gi = int(sy) - hz
                    g = gshade[gmax if gi > gmax else 0 if gi < 0 else gi] + v
                    fill((g, g, g + 3), (sx, sy, s + 1, s))
        self.draw_tracks(surf)
        items = []
        append = items.append
        R = 46.0 * kn["rocks"]
        far = R * 1.6
        for cx in range(math.floor((cx0 - R) / CELL_M), math.floor((cx0 + R) / CELL_M) + 1):
            for cy in range(math.floor((cy0 - R) / CELL_M), math.floor((cy0 + R) / CELL_M) + 1):
                for wx, wy, kind, r, _var in cell_items(cx, cy):
                    dx, dy = wx - cx0, wy - cy0
                    z = dx * ca + dy * sa + chord
                    if z <= 1.0 or z > far:
                        continue
                    k = focal / z
                    append((z, half + (dy * ca - dx * sa) * k, kind, r))
        for x, y, r in self.scars:
            dx, dy = x - cx0, y - cy0
            z = dx * ca + dy * sa + chord
            if z > 1.0:
                append((z, half + (dy * ca - dx * sa) * focal / z, "s", r))
        items.sort(reverse=True)                                         # painter's algorithm: far first
        step = max(1, int(round(1.0 / max(0.05, kn["rocks"]))))
        for i, (z, sx, kind, r) in enumerate(items):
            if z > 14.0 and step > 1 and i % step:                       # the far field thins out, the near field never
                continue
            k = focal / z
            w = r * k
            sy = hz + C.CAM_HEIGHT_M * k
            if sy - w > H or sy + w < 0 or sx + w * 2.0 < 0 or sx - w * 2.0 > W:
                continue                                                 # off screen: a near crater projects far below the edge
            fade = 1.0 - (z - 25.0) * 0.02857
            fade = 0.0 if fade < 0.0 else 1.0 if fade > 1.0 else fade
            gi = int(sy) - hz
            g = gshade[gmax if gi > gmax else 0 if gi < 0 else gi]                            # ground brightness at this depth
            isx, isy = int(sx), int(sy)
            if kind == "r":
                rw, rh = max(2, int(w * 1.3)), max(2, int(w * 0.9))
                left, bottom = isx - rw // 2, isy                                        # body sits on its ground point
                if rw < 7:                                                               # far away: one dark dot is enough
                    ell(surf, (int(g - 34 * fade),) * 3, (left, bottom - rh, rw, rh))
                    continue
                ell(surf, (int(g - 38 * fade), int(g - 38 * fade), int(g - 34 * fade)), (left, bottom - rh, rw, rh))
                if fade < 0.12:                                                          # too far to tell the parts apart
                    continue
                ell(surf, (int(g - 30 * fade),) * 3,                                                # cast shadow, down-right
                    (left + rw * 0.18, bottom - rh * 0.30, rw * 1.15, rh * 0.42))
                ell(surf, (int(g + 22 * fade),) * 3,
                    (left + rw * 0.21 - rw // 9, bottom - rh + rh * 0.225 - rh // 7, rw * 0.58, rh * 0.55))
                continue
            w2, h2 = int(w * 2), int(max(2.0, w * C.CAM_HEIGHT_M / math.hypot(z, C.CAM_HEIGHT_M)) * 2)
            if w2 < 6:
                continue
            rx, ry = isx - w2 // 2, isy - h2 // 2
            if kind == "c":
                dw, dh = int(w2 * 0.16), int(h2 * 0.22)
                ell(surf, (int(g + 26 * fade),) * 3,                                     # raised sunlit rim
                    (rx - dw // 2, ry - dh // 2 + int(h2 * 0.05), w2 + dw, h2 + dh))
                ell(surf, (int(g - 34 * fade), int(g - 34 * fade), int(g - 30 * fade)), (rx, ry, w2, h2))
                if fade > 0.12:                                                          # shadowed wall
                    cw, ch = int(w2 * 0.22), int(h2 * 0.30)
                    ell(surf, (int(g - 12 * fade),) * 3, (rx + cw // 2 + int(w2 * 0.05), ry + ch // 2 + int(h2 * 0.12),
                                                          w2 - cw, h2 - ch))
            else:                                                                        # a fresh impact scar: dark, with a pale ejecta apron
                if fade > 0.12:
                    dw, dh = int(w2 * 0.7), int(h2 * 0.7)
                    ell(surf, (int(g + 9 * fade),) * 3, (rx - dw // 2, ry - dh // 2, w2 + dw, h2 + dh))
                    dw, dh = int(w2 * 0.2), int(h2 * 0.2)
                    ell(surf, (int(g - 26 * fade),) * 3, (rx - dw // 2, ry - dh // 2, w2 + dw, h2 + dh))
                ell(surf, (int(g - 50 * fade), int(g - 50 * fade), int(g - 46 * fade)), (rx, ry, w2, h2))
                if fade > 0.12:
                    dw, dh = int(w2 * 0.45), int(h2 * 0.5)
                    ell(surf, (int(g - 34 * fade),) * 3, (rx + dw // 2 + int(w2 * 0.06), ry + dh // 2 + int(h2 * 0.1),
                                                          w2 - dw, h2 - dh))
        play = not ctx.get("backdrop")
        if play:
            self.draw_impact(surf, game)
            self.draw_sample3d(surf, game)
        self.draw_rings3(surf)
        rover_at = None
        if play and not ctx.get("hide_craft"):
            c = game.craft
            sx, sy, z = self.project(c.x, c.y)
            if z > 1.0:
                w = ROVER_W_M * C.CAM_FOCAL / z
                bob = (math.sin(self.t * 17.0) * 1.3 + math.sin(self.t * 29.3) * 0.8) * self.speed01     # the suspension works while driving
                lights = not game.thermal.daylight() or self.dark > 0.2
                self.rover.draw_back(surf, sx, sy - w * 0.55 * 0.82 + bob, w, lights, self.t, lean=self.lean)
                rover_at = (sx, sy) if lights else None
        self.draw_wparts(surf)
        self.draw_flashes(surf)
        if play:
            self.draw_meteor(surf, game)
            self.draw_floaters(surf)
        self.parts.draw(surf)
        self.draw_light(surf, game, rover_at)

    def draw_impact(self, surf, game):
        """The impact zone: a ring on the ground where the rock lands. It starts wide and closes in as the countdown runs out."""
        st = game.strike
        if not st or st["phase"] != "warn" or "x" not in st:
            return
        left = max(0.0, st["left"])
        frac = left / C.STRIKE_WARN_S if st["mode"] == "own" else min(1.0, left / C.STRIKE_WARN_S)
        r = C.STRIKE_HIT_M + (C.STRIKE_RADIUS_M - C.STRIKE_HIT_M) * frac      # closes to the blast radius at impact
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
        spin = self.t * 0.9                                                    # the inner reticle turns slowly
        inner = [self._ground_pt(st["x"] + math.cos(a + spin) * r * 0.45, st["y"] + math.sin(a + spin) * r * 0.45)
                 for a in (i * math.tau / 16 for i in range(16))]
        if all(inner):
            for i in range(0, 16, 2):                                          # dashed
                pygame.draw.line(surf, K.mix(col, K.WHITE, 0.4), inner[i], inner[i + 1], 2)
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
            age = s.get("age", 1.0)
            pop = _ease_out_back(age / 0.45)                                               # a new sample pops out of the ground
            r = max(2, int(max(5, 0.9 * k) * pop))
            lift = int(r * 1.2 + 4 * math.sin(self.t * 4))
            ring0 = pygame.Rect(0, 0, int(r * 2.2), max(2, int(r * 0.7)))                  # contact shadow
            ring0.center = (int(sx), int(sy))
            pygame.draw.ellipse(surf, (58, 59, 66), ring0)
            if age > 0.25:
                b = self.beams[s["kind"]]
                surf.blit(b, (sx - b.get_width() / 2, sy - lift - b.get_height()), special_flags=pygame.BLEND_RGB_ADD)
            g = self.glows_add[s["kind"]]
            surf.blit(g, (sx - g.get_width() / 2, sy - lift - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
            turn = math.cos(self.t * 1.7)                                                  # the crystal turns: its width breathes, the lit face swaps
            hw = r * 0.8 * (0.35 + 0.65 * abs(turn))
            pts = [(sx, sy - lift - r), (sx + hw, sy - lift), (sx, sy - lift + r), (sx - hw, sy - lift)]
            dark, lit = K.mix(col, (0, 0, 0), 0.35), K.mix(col, K.WHITE, 0.55)
            pygame.draw.polygon(surf, col, pts)
            pygame.draw.polygon(surf, dark, [pts[1] if turn >= 0 else pts[3], pts[2], (sx, sy - lift)])              # facets
            pygame.draw.polygon(surf, lit, [pts[0], pts[3] if turn >= 0 else pts[1], (sx, sy - lift)])
            pygame.draw.polygon(surf, K.WHITE, pts, 2)
            ring = pygame.Rect(0, 0, int(C.SAMPLE_PICKUP_M * 2 * k), int(C.SAMPLE_PICKUP_M * 2 * k * 0.35))
            ring.center = (int(sx), int(sy))
            pygame.draw.ellipse(surf, col, ring, 2)
        else:                                                    # off screen: a pulsing arrow on the screen edge
            left = sx < 0 or (z <= 1.0 and game.sample_bearing() < 0)
            ex = 46 if left else self.W - 46
            ey = int(self.H * 0.5)
            d = (-1 if left else 1) * (10 + 6 * math.sin(self.t * 6))
            pygame.draw.polygon(surf, col, [(ex + d + (14 if not left else -14), ey), (ex + d, ey - 16), (ex + d, ey + 16)])
            pygame.draw.polygon(surf, K.WHITE, [(ex + d + (14 if not left else -14), ey), (ex + d, ey - 16), (ex + d, ey + 16)], 2)

    def draw(self, surf, game, ctx):
        """ctx: dict(ap_on, speed01, shake, hide_craft, backdrop)."""
        if self.mode3d:
            return self.draw3d(surf, game, ctx)
        play = not ctx.get("backdrop")
        self.draw_ground(surf)
        self.draw_tracks(surf)
        if play:
            self.draw_impact(surf, game)
            self.draw_sample(surf, game)
        self.draw_rings3(surf)
        if play and not ctx.get("hide_craft"):
            x, y = self.px(game.craft.x, game.craft.y)
            self.rover.draw_top(surf, x, y, game.craft.theta, self.S * 2.6, lights=not game.thermal.daylight() or self.dark > 0.2)
        self.draw_wparts(surf)
        self.draw_flashes(surf)
        if play:
            self.draw_meteor(surf, game)
            self.draw_floaters(surf)
        self.parts.draw(surf)
        self.draw_light(surf, game)

"""The mobile lunar base: drawn in code (body, wheels, solar panels, lights), plus the glow sprite.
Everything is pre-rendered once and cached: nothing here allocates a surface per frame."""
import math
import pygame
from gfx import palette as K

_glows = {}


def glow_sprite(radius, color, power=2.0):
    """Radial glow, cached by (radius, colour, power). Treat the result as read-only."""
    key = (radius, tuple(color), power)
    s = _glows.get(key)
    if s is None:
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        for r in range(radius, 0, -2):
            a = (1.0 - r / radius) ** power
            pygame.draw.circle(s, (color[0], color[1], color[2], int(255 * a)), (radius, radius), r)
        if len(_glows) > 200:
            _glows.clear()
        _glows[key] = s
    return s


def glow_add(radius, color, power=2.0):
    """The same glow on opaque black, for BLEND_RGB_ADD blits (ADD ignores alpha, so the falloff must be in the colour)."""
    key = ("add", radius, tuple(color), power)
    s = _glows.get(key)
    if s is None:
        s = pygame.Surface((radius * 2, radius * 2))
        for r in range(radius, 0, -1):
            a = (1.0 - r / radius) ** power
            pygame.draw.circle(s, (int(color[0] * a), int(color[1] * a), int(color[2] * a)), (radius, radius), r)
        s = _glows[key] = s.convert()
    return s


def _shade_rect(s, rect, top, bottom, radius):
    """Rounded rectangle with a vertical gradient (lit from above)."""
    rect = pygame.Rect(rect)
    g = pygame.Surface(rect.size, pygame.SRCALPHA)
    for y in range(rect.h):
        pygame.draw.line(g, K.mix(top, bottom, y / max(1, rect.h - 1)), (0, y), (rect.w, y))
    mask = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    g.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    s.blit(g, rect.topleft)


def _rear_master(w=480):
    """The rover seen from behind, `w` pixels wide across the body. Returns (surface, body centre in the surface)."""
    h = w * 0.55
    W, H = int(w * 1.7), int(w * 1.55)
    s = pygame.Surface((W, H), pygame.SRCALPHA)
    cx, cy = W / 2, H * 0.60
    u = w / 480.0
    sh = pygame.Surface((int(w * 1.5), int(h * 0.42)), pygame.SRCALPHA)                    # ground shadow
    for i in range(6):
        pygame.draw.ellipse(sh, (0, 0, 0, 26), sh.get_rect().inflate(-i * sh.get_width() * 0.05, -i * sh.get_height() * 0.07))
    s.blit(sh, (cx - sh.get_width() / 2, cy + h * 0.80 - sh.get_height() / 2))
    for sx in (-1, 1):                                                                     # wheels with tread
        wr = pygame.Rect(0, 0, w * 0.21, h * 0.74)
        wr.midtop = (cx + sx * w * 0.53, cy + h * 0.08)
        _shade_rect(s, wr, (58, 62, 74), (16, 17, 22), int(16 * u))
        for i in range(1, 9):
            y = wr.top + wr.h * i / 9
            pygame.draw.line(s, (12, 13, 18), (wr.left + 4 * u, y), (wr.right - 4 * u, y + 5 * u), max(1, int(4 * u)))
        pygame.draw.rect(s, (86, 92, 108), (wr.left + (0 if sx > 0 else wr.w - 7 * u), wr.top + 14 * u, 7 * u, wr.h - 28 * u), border_radius=3)
        pygame.draw.line(s, (60, 66, 82), (cx + sx * w * 0.30, cy + h * 0.36), (wr.centerx - sx * wr.w * 0.5, cy + h * 0.42), max(2, int(12 * u)))
    for sx in (-1, 1):                                                                     # solar wings
        p = pygame.Rect(0, 0, w * 0.36, h * 0.13)
        p.midbottom = (cx + sx * w * 0.50, cy - h * 0.40)
        pygame.draw.line(s, (120, 130, 150), (cx + sx * w * 0.30, cy - h * 0.42), (p.centerx - sx * p.w * 0.3, p.bottom), max(2, int(6 * u)))
        _shade_rect(s, p, (70, 110, 210), (24, 44, 112), int(4 * u))
        for i in range(1, 6):
            x = p.left + p.w * i / 6
            pygame.draw.line(s, (130, 170, 250), (x, p.top + 2), (x, p.bottom - 2), 1)
        pygame.draw.rect(s, (150, 185, 255), p, max(1, int(2 * u)), border_radius=int(4 * u))
    body = pygame.Rect(0, 0, w, h)
    body.center = (cx, cy)
    pygame.draw.rect(s, (70, 84, 112), body.inflate(8 * u, 8 * u), border_radius=int(30 * u))
    _shade_rect(s, body, (244, 248, 255), (150, 164, 192), int(26 * u))
    pygame.draw.rect(s, (255, 255, 255), (body.left + 26 * u, body.top + 5 * u, body.w - 52 * u, 4 * u), border_radius=2)   # top highlight
    win = pygame.Rect(0, 0, w * 0.70, h * 0.24)                                            # rear window
    win.midtop = (cx, body.top + h * 0.13)
    _shade_rect(s, win, (28, 44, 80), (74, 112, 170), int(12 * u))
    pygame.draw.polygon(s, (130, 170, 225), [(win.left + win.w * 0.12, win.bottom - 3), (win.left + win.w * 0.26, win.top + 3),
                                              (win.left + win.w * 0.34, win.top + 3), (win.left + win.w * 0.20, win.bottom - 3)])
    pygame.draw.rect(s, (56, 70, 100), win, max(1, int(3 * u)), border_radius=int(12 * u))
    band = pygame.Rect(body.left + 10 * u, cy + h * 0.02, body.w - 20 * u, h * 0.10)       # gold foil band
    _shade_rect(s, band, (255, 205, 96), (190, 128, 34), int(4 * u))
    for i in range(1, 12):
        x = band.left + band.w * i / 12
        pygame.draw.line(s, (160, 104, 26), (x, band.top + 2), (x - 6 * u, band.bottom - 2), 1)
    hatch = pygame.Rect(0, 0, w * 0.26, h * 0.26)                                          # rear hatch
    hatch.midtop = (cx, band.bottom + h * 0.04)
    pygame.draw.rect(s, (176, 188, 212), hatch, border_radius=int(8 * u))
    pygame.draw.rect(s, (112, 126, 156), hatch, max(1, int(3 * u)), border_radius=int(8 * u))
    pygame.draw.circle(s, (90, 104, 134), (int(hatch.centerx), int(hatch.centery)), max(2, int(9 * u)), max(1, int(3 * u)))
    for sx in (-1, 1):                                                                     # tail light housings (unlit)
        pygame.draw.rect(s, (48, 26, 30), (cx + sx * w * 0.38 - 26 * u, band.bottom + h * 0.07, 52 * u, 28 * u), border_radius=int(6 * u))
    mx = cx + w * 0.22                                                                     # mast and dish
    pygame.draw.line(s, (120, 132, 156), (mx, body.top), (mx, body.top - h * 0.62), max(2, int(7 * u)))
    dish = pygame.Rect(0, 0, w * 0.20, h * 0.16)
    dish.center = (cx - w * 0.24, body.top - h * 0.16)
    pygame.draw.line(s, (120, 132, 156), (dish.centerx, body.top), dish.center, max(2, int(6 * u)))
    pygame.draw.ellipse(s, (226, 232, 244), dish)
    pygame.draw.ellipse(s, (150, 162, 188), dish.inflate(-dish.w * 0.3, -dish.h * 0.4))
    pygame.draw.ellipse(s, (96, 108, 136), dish, max(1, int(3 * u)))
    return s, (cx, cy), (mx, body.top - h * 0.62), band.bottom + h * 0.07 + 14 * u


class Rover:
    """draw_top(): the rover seen from above on the map. draw_back(): the same base seen from behind (chase view, intro)."""

    def __init__(self, scale, quant=8):
        self.S = scale
        self.quant = quant               # rear sprite width step in pixels (finer = smoother size changes, more sprites)
        self.rot = {}                    # leaned rear sprites, (width key, angle) -> surface
        self.t = 0.0
        self.headlight = glow_add(60, (255, 240, 200), 1.8)
        self.cache = {}
        self.master = None
        self.rear = {}

    def update(self, dt):
        self.t += dt

    def sprite(self, size):
        """The rover pointing right (+x), `size` pixels long, cached."""
        key = int(size)
        if key in self.cache:
            return self.cache[key]
        L, W = size, size * 0.62
        s = pygame.Surface((int(L * 1.5), int(W * 1.9)), pygame.SRCALPHA)
        cx, cy = s.get_width() / 2, s.get_height() / 2
        for sx in (-0.30, 0.30):                                              # wheels
            for sy in (-1, 1):
                pygame.draw.rect(s, (28, 30, 38), (cx + sx * L - L * 0.13, cy + sy * W * 0.62 - W * 0.14, L * 0.26, W * 0.28), border_radius=3)
        for sy in (-1, 1):                                                    # solar panels folded out
            pygame.draw.rect(s, (40, 70, 150), (cx - L * 0.3, cy + sy * W * 0.86 - W * 0.1, L * 0.6, W * 0.2))
            pygame.draw.rect(s, (110, 150, 230), (cx - L * 0.3, cy + sy * W * 0.86 - W * 0.1, L * 0.6, W * 0.2), 1)
        body = pygame.Rect(0, 0, L, W)
        body.center = (cx, cy)
        pygame.draw.rect(s, K.HULL_DARK, body.inflate(4, 4), border_radius=8)
        pygame.draw.rect(s, K.HULL, body, border_radius=8)
        pygame.draw.rect(s, (160, 175, 200), (body.left + L * 0.1, body.top + W * 0.12, L * 0.5, W * 0.76), border_radius=5)   # roof
        pygame.draw.rect(s, (70, 110, 150), (body.left + L * 0.62, body.top + W * 0.18, L * 0.26, W * 0.64), border_radius=4)   # cab window
        pygame.draw.circle(s, (255, 235, 170), (int(body.right - 3), int(body.top + W * 0.2)), max(2, int(W * 0.09)))
        pygame.draw.circle(s, (255, 235, 170), (int(body.right - 3), int(body.bottom - W * 0.2)), max(2, int(W * 0.09)))
        self.cache[key] = s
        return s

    def draw_top(self, surf, x, y, theta, size, lights=True, glow_scale=1.0):
        if lights:
            g = self.headlight
            a = math.radians(theta)
            lx, ly = x + math.cos(a) * size * 1.1, y + math.sin(a) * size * 1.1
            surf.blit(g, (lx - g.get_width() / 2, ly - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
        img = pygame.transform.rotate(self.sprite(size), -theta)
        surf.blit(img, img.get_rect(center=(int(x), int(y))))

    def _rear(self, w):
        """Rear sprite at body width w (quantized so the growing intro rover reuses sprites)."""
        if self.master is None:
            self.master = _rear_master()
        key = max(8, int(w) // self.quant * self.quant)
        if key not in self.rear:
            if len(self.rear) > 24:
                self.rear.clear()
                self.rot.clear()
            img, c, mast, tail_y = self.master
            k = key / 480.0
            self.rear[key] = (pygame.transform.smoothscale(img, (int(img.get_width() * k), int(img.get_height() * k))),
                              (c[0] * k, c[1] * k), (mast[0] * k, mast[1] * k), tail_y * k, k)
        return self.rear[key]

    def draw_back(self, surf, cx, cy, w, lights_on, t, lean=0.0):
        """Rear view for the chase camera and the intro: shaded body, treaded wheels, solar wings, dish, blinking beacon.
        lean (degrees, + = top to the left) rolls the whole base a little in a turn."""
        img, c, mast, tail_y, k = self._rear(w)
        ox, oy = cx - c[0], cy - c[1]
        px, py = ox + img.get_width() / 2, oy + img.get_height() / 2          # the sprite centre: the roll pivot
        q = round(lean * 2.0) / 2.0
        if q:
            key = (img.get_width(), q)
            rot = self.rot.get(key)
            if rot is None:
                if len(self.rot) > 60:
                    self.rot.clear()
                rot = self.rot[key] = pygame.transform.rotozoom(img, q, 1.0)
            surf.blit(rot, rot.get_rect(center=(int(px), int(py))))
            ca, sa = math.cos(math.radians(q)), math.sin(math.radians(q))
        else:
            surf.blit(img, (ox, oy))
            ca, sa = 1.0, 0.0

        def at(x, y):                                                         # a sprite point after the roll
            dx, dy = x - px, y - py
            return int(px + dx * ca + dy * sa), int(py - dx * sa + dy * ca)

        blink = int(t * 3) % 2
        bx, by = at(ox + mast[0], oy + mast[1])
        if blink:
            g = glow_add(max(6, int(44 * k)), (230, 50, 40), 2.0)
            surf.blit(g, (bx - g.get_width() // 2, by - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
        pygame.draw.circle(surf, K.RED if blink else (90, 40, 44), (bx, by), max(3, int(11 * k)))
        if lights_on:                                                         # tail lights, on once the base wakes up
            for sx in (-1, 1):
                lx, ly = at(cx + sx * w * 0.38, oy + tail_y)
                g = glow_add(max(6, int(70 * k)), (200, 46, 30), 2.0)
                surf.blit(g, (lx - g.get_width() // 2, ly - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
                pygame.draw.rect(surf, (255, 96, 70), (lx - 22 * k, ly - 10 * k, 44 * k, 20 * k), border_radius=max(1, int(5 * k)))
                pygame.draw.rect(surf, (255, 210, 190), (lx - 12 * k, ly - 4 * k, 24 * k, 8 * k), border_radius=max(1, int(3 * k)))

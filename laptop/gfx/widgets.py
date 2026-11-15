"""HUD building blocks: panels, hearts that crack, sparkline, banner, toasts, status dots, number tweening."""
import collections
import math
import pygame
from gfx import fonts, palette as K
from gfx.rover import glow_add

_panels = {}
_overlays = {}
SHADOW = 10                         # soft drop shadow margin baked into every panel sprite


def _vgradient(size, top, bottom):
    """Vertical gradient, built 1 pixel wide and stretched (cheap, done once per cached sprite)."""
    w, h = size
    col = pygame.Surface((1, max(2, h)), pygame.SRCALPHA)
    for y in range(col.get_height()):
        col.set_at((0, y), K.mix(top, bottom, y / (col.get_height() - 1)) + (255,))
    return pygame.transform.scale(col, (w, h))


def _rounded(surface, radius):
    """Clip a surface to a rounded rectangle (multiply by a white rounded mask)."""
    mask = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return surface


def panel(surf, rect, alpha=170, edge=K.PANEL_EDGE, radius=14, scan=True, title=None):
    """A glass panel: soft shadow, top-lit navy gradient, hairline edge, bright corner brackets. Built once per size.
    (`scan` is kept for callers; panels no longer carry scanlines.)"""
    rect = pygame.Rect(rect)
    key = (rect.w, rect.h, alpha, edge, radius, scan)
    if key not in _panels:
        m = SHADOW
        s = pygame.Surface((rect.w + 2 * m, rect.h + 2 * m), pygame.SRCALPHA)
        for i in range(m, 0, -2):                                   # shadow: stacked faint rounded rects
            pygame.draw.rect(s, (0, 0, 0, 14), pygame.Rect(m - i, m - i + 4, rect.w + 2 * i, rect.h + 2 * i), border_radius=radius + i)
        body = _rounded(_vgradient(rect.size, K.mix(K.PANEL, (60, 90, 150), 0.22), K.mix(K.PANEL, (0, 0, 0), 0.25)), radius)
        body.fill((255, 255, 255, min(250, alpha + 45)), special_flags=pygame.BLEND_RGBA_MIN)
        hole = pygame.Rect(m, m, rect.w, rect.h)
        pygame.draw.rect(s, (0, 0, 0, 0), hole, border_radius=radius)
        s.blit(body, hole.topleft)
        pygame.draw.rect(s, (*edge, 150), hole, 1, border_radius=radius)
        pygame.draw.line(s, (255, 255, 255, 36), (hole.left + radius, hole.top + 1), (hole.right - radius, hole.top + 1))
        hi = K.mix(edge, K.CYAN, 0.6) if edge == K.PANEL_EDGE else edge
        L = min(22, rect.w // 4, rect.h // 3)
        if radius <= 16:                                            # corner brackets (pills keep a plain edge)
            for cx, cy, dx, dy in ((hole.left, hole.top, 1, 1), (hole.right - 1, hole.top, -1, 1),
                                   (hole.left, hole.bottom - 1, 1, -1), (hole.right - 1, hole.bottom - 1, -1, -1)):
                r2 = radius // 2
                pygame.draw.line(s, (*hi, 230), (cx + dx * r2, cy), (cx + dx * (r2 + L), cy), 2)
                pygame.draw.line(s, (*hi, 230), (cx, cy + dy * r2), (cx, cy + dy * (r2 + L)), 2)
        _panels[key] = s
    surf.blit(_panels[key], (rect.left - SHADOW, rect.top - SHADOW))
    if title:
        caption(surf, title, (rect.left + 18, rect.top + 12))
    return rect


def caption(surf, text, pos, color=K.CYAN):
    """Small spaced section label with an accent tick, e.g. the name of a HUD panel."""
    pygame.draw.rect(surf, color, (pos[0], pos[1] + 3, 3, 12))
    return fonts.text(surf, text, (pos[0] + 10, pos[1]), 14, K.mix(color, K.GREY, 0.45), bold=True, track=2)


def overlay(surf, color, alpha, size=None):
    """Full-screen tint without a per-frame allocation: one cached opaque surface per colour, faded with set_alpha."""
    size = size or surf.get_size()
    key = (size, tuple(color))
    s = _overlays.get(key)
    if s is None:
        s = pygame.Surface(size).convert()
        s.fill(color)
        _overlays[key] = s
    s.set_alpha(max(0, min(255, int(alpha))))
    surf.blit(s, (0, 0))


def bar(surf, rect, frac, color, ticks=4, flash=None, ghost=None, gain=0.0):
    """A meter: dark track, bright fill with a lit top half and a hot tip, tick marks. No allocations.
    ghost (0..1): where the value was before a sudden loss, shown as a pale block that drains away.
    gain (0..1): how strongly the fill glows white after a sudden gain."""
    rect = pygame.Rect(rect)
    r = rect.h // 2
    pygame.draw.rect(surf, K.TRACK, rect, border_radius=r)
    c = flash or color
    if gain > 0.02:
        c = K.mix(c, K.WHITE, 0.7 * gain)
    w = int((rect.w - 4) * max(0.0, min(1.0, frac)))
    if ghost is not None and ghost > frac + 0.004:
        gw = int((rect.w - 4) * max(0.0, min(1.0, ghost)))
        pygame.draw.rect(surf, (236, 226, 226), (rect.left + 2 + max(0, w - 4), rect.top + 3, gw - max(0, w - 4), rect.h - 6), border_radius=r)
    if w > 2:
        fill = pygame.Rect(rect.left + 2, rect.top + 2, w, rect.h - 4)
        pygame.draw.rect(surf, K.mix(c, (0, 0, 0), 0.22), fill, border_radius=r)
        pygame.draw.rect(surf, c, (fill.left, fill.top, fill.w, max(2, fill.h // 2)), border_radius=r)
        pygame.draw.rect(surf, K.mix(c, K.WHITE, 0.55), (fill.left + 3, fill.top + 1, max(1, fill.w - 6), 2), border_radius=1)
        pygame.draw.rect(surf, K.mix(c, K.WHITE, 0.75), (fill.right - 3, fill.top + 1, 3, fill.h - 2), border_radius=1)
    for i in range(1, ticks):
        x = rect.left + rect.w * i // ticks
        pygame.draw.line(surf, K.BG, (x, rect.top + 3), (x, rect.bottom - 4))
    pygame.draw.rect(surf, K.mix(color, K.PANEL, 0.55), rect, 1, border_radius=r)


def select_row(surf, rect, radius=12):
    """Highlight behind the selected menu row (cached per size)."""
    rect = pygame.Rect(rect)
    key = ("sel", rect.w, rect.h, radius)
    s = _overlays.get(key)
    if s is None:
        s = _overlays[key] = pygame.Surface(rect.size, pygame.SRCALPHA)
        g = _vgradient(rect.size, (70, 150, 240), (30, 80, 170))
        g.fill((255, 255, 255, 84), special_flags=pygame.BLEND_RGBA_MIN)
        s.blit(_rounded(g, radius), (0, 0))
        pygame.draw.rect(s, (*K.CYAN, 235), s.get_rect(), 2, border_radius=radius)
        pygame.draw.rect(s, K.CYAN, (0, 10, 4, rect.h - 20), border_radius=2)
    surf.blit(s, rect.topleft)


def pill(surf, rect, text, color, size=17):
    """Status badge: tinted capsule with a coloured edge and bold label."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, K.mix(K.PANEL, color, 0.28), rect, border_radius=rect.h // 2)
    pygame.draw.rect(surf, color, rect, 2, border_radius=rect.h // 2)
    fonts.text(surf, text, rect.center, size, color, bold=True, anchor="center")


def keycap(surf, pos, label, on=True, size=30, color=None):
    """A keyboard key: raised cap with a darker base."""
    x, y = pos
    col = (color or K.CYAN) if on else K.DIM
    pygame.draw.rect(surf, K.mix(K.PANEL, (0, 0, 0), 0.4), (x, y + 3, size, size), border_radius=7)
    pygame.draw.rect(surf, K.mix((20, 28, 50), col, 0.18) if on else (20, 28, 50), (x, y, size, size), border_radius=7)
    pygame.draw.rect(surf, K.mix(col, K.PANEL, 0.35), (x, y, size, size), 1, border_radius=7)
    fonts.text(surf, label, (x + size // 2, y + size // 2), int(size * 0.68), col, bold=True, anchor="center")


class Tween:
    """Smoothly follows a target value (ease-out)."""

    def __init__(self, v=0.0, rate=8.0):
        self.v, self.target, self.rate = float(v), float(v), rate

    def set(self, t):
        self.target = float(t)

    def update(self, dt):
        self.v += (self.target - self.v) * min(1.0, dt * self.rate)
        return self.v


def _heart_poly(size, color, outline=None, width=0):
    ss = size * 4
    s = pygame.Surface((ss, ss), pygame.SRCALPHA)
    r = ss * 0.26
    cx = ss / 2
    pygame.draw.circle(s, color, (cx - r * 0.95, ss * 0.36), r, width)
    pygame.draw.circle(s, color, (cx + r * 0.95, ss * 0.36), r, width)
    pts = [(cx - r * 1.93, ss * 0.42), (cx, ss * 0.92), (cx + r * 1.93, ss * 0.42)]
    pygame.draw.polygon(s, color, pts, width)
    return pygame.transform.smoothscale(s, (size, size))


class Hearts:
    """15 glowing hearts. A lost heart cracks in two, the halves fall apart and fade to an outline."""

    def __init__(self, n=15, size=28):
        self.n, self.size = n, size
        self.full = _heart_poly(size, (255, 80, 100))
        shine = _heart_poly(size, (255, 170, 180))
        self.full.blit(pygame.transform.smoothscale(shine, (size // 2, size // 2)), (size // 4, size // 6), special_flags=pygame.BLEND_RGB_ADD)
        self.empty = _heart_poly(size, (90, 100, 130), width=6)
        self.glow = glow_add(int(size * 0.95), (150, 26, 50), 1.6)
        self.glow_levels = {}
        self.shown = n
        self.anim = {}                  # index -> age

    def set(self, lives):
        while self.shown > lives:
            self.shown -= 1
            self.anim[self.shown] = 0.0
        self.shown = lives if lives > self.shown else self.shown

    def update(self, dt):
        for k in list(self.anim):
            self.anim[k] += dt
            if self.anim[k] > 0.9:
                del self.anim[k]

    def draw(self, surf, pos, lives, t):
        x0, y0 = pos
        step = self.size + 4
        for i in range(self.n):
            x = x0 + i * step
            if i in self.anim:
                a = self.anim[i]
                f = a / 0.9
                if a < 0.3:                                                 # the crack line flashes across the heart
                    surf.blit(self.full, (x, y0))
                    pygame.draw.lines(surf, (20, 10, 20), False, [(x + self.size * 0.5, y0), (x + self.size * 0.42, y0 + self.size * 0.35),
                                                                   (x + self.size * 0.58, y0 + self.size * 0.6), (x + self.size * 0.5, y0 + self.size)], 3)
                else:
                    g = (a - 0.3) / 0.6
                    half = self.size // 2
                    left = self.full.subsurface((0, 0, half, self.size)).copy()
                    right = self.full.subsurface((half, 0, self.size - half, self.size)).copy()
                    left.set_alpha(int(255 * (1 - g)))
                    right.set_alpha(int(255 * (1 - g)))
                    surf.blit(left, (x - 10 * g, y0 + 24 * g * g))
                    surf.blit(right, (x + half + 10 * g, y0 + 30 * g * g))
                    surf.blit(self.empty, (x, y0))
                fl = pygame.Surface((self.size + 8, self.size + 8), pygame.SRCALPHA)
                if f < 0.35:
                    pygame.draw.rect(fl, (255, 60, 60, int(160 * (1 - f / 0.35))), fl.get_rect(), border_radius=8)
                    surf.blit(fl, (x - 4, y0 - 4))
            elif i < lives:
                pulse = 0.65 + 0.35 * math.sin(t * 2.5 + i * 0.5)
                level = int(pulse * 8)                                   # 8 brightness steps, each tinted once and reused
                g = self.glow_levels.get(level)
                if g is None:
                    g = self.glow.copy()
                    g.fill((int(255 * level / 8.0),) * 3, special_flags=pygame.BLEND_RGB_MULT)
                    self.glow_levels[level] = g
                surf.blit(g, (x + self.size // 2 - g.get_width() // 2, y0 + self.size // 2 - g.get_height() // 2),
                          special_flags=pygame.BLEND_RGB_ADD)
                surf.blit(self.full, (x, y0))
            else:
                surf.blit(self.empty, (x, y0))
        return x0 + self.n * step


def sparkline(surf, rect, values, color=K.CYAN, lo=None, hi=None):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surf, K.TRACK, rect, border_radius=6)
    if len(values) < 2:
        return
    v0 = min(values) if lo is None else lo
    v1 = max(values) if hi is None else hi
    if v1 - v0 < 4:
        mid = (v0 + v1) / 2
        v0, v1 = mid - 2, mid + 2
    n = len(values)
    pts = [(rect.left + 4 + (rect.w - 8) * i / (n - 1), rect.bottom - 4 - (rect.h - 8) * (v - v0) / (v1 - v0)) for i, v in enumerate(values)]
    pygame.draw.lines(surf, color, False, pts, 2)
    pygame.draw.circle(surf, K.WHITE, (int(pts[-1][0]), int(pts[-1][1])), 3)


def dot(surf, pos, color, r=8, pulse=0.0):
    glow = glow_add(int(r * 2.4), K.mix(color, (0, 0, 0), 0.45), 2.0)
    surf.blit(glow, (pos[0] - glow.get_width() // 2, pos[1] - glow.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)
    pygame.draw.circle(surf, K.mix(color, (0, 0, 0), 0.35), pos, r)
    pygame.draw.circle(surf, color, pos, r - 2)
    pygame.draw.circle(surf, K.mix(color, (255, 255, 255), 0.6), (pos[0] - r // 3, pos[1] - r // 3), max(1, r // 4))


class Toasts:
    def __init__(self):
        self.items = []                 # [text, kind, ttl]

    def add(self, text, kind="info", ttl=3.2):
        if self.items and self.items[-1][0] == text:
            self.items[-1][2] = ttl
            return
        self.items.append([text, kind, ttl])
        self.items = self.items[-4:]

    def update(self, dt):
        for it in self.items:
            it[2] -= dt
        self.items = [it for it in self.items if it[2] > 0]

    def draw(self, surf, cx, y):
        colors = {"info": K.CYAN, "ok": K.GREEN, "warn": K.YELLOW, "bad": K.RED}
        for text, kind, ttl in self.items:
            a = max(0.0, min(1.0, ttl / 0.5, (3.2 - ttl) / 0.15 + 0.2))
            col = colors.get(kind, K.CYAN)
            w = fonts.width(text, 22) + 64
            r = pygame.Rect(0, 0, w, 42)
            r.midtop = (cx, y - int(10 * (1 - a)))
            key = ("toast", w, kind)
            s = _overlays.get(key)
            if s is None:
                s = _overlays[key] = pygame.Surface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(s, (*K.mix(K.PANEL, col, 0.10), 235), s.get_rect(), border_radius=10)
                pygame.draw.rect(s, (*col, 120), s.get_rect(), 1, border_radius=10)
                pygame.draw.rect(s, col, (0, 8, 4, r.h - 16), border_radius=2)
            s.set_alpha(int(255 * a))
            surf.blit(s, r.topleft)
            fonts.text(surf, text, (r.centerx + 2, r.centery), 22, K.mix(col, K.WHITE, 0.35), anchor="center", alpha=int(255 * a))
            y += 50


def banner(surf, cx, y, title, sub, color, t, icon="warn", appear=1.0):
    """The big pulsing warning banner: tinted plate, hazard stripes at both ends, warning triangle."""
    w = max(fonts.width(title, 32, bold=True), fonts.width(sub, 21)) + 220
    r = pygame.Rect(0, 0, w, 96)
    r.midtop = (cx, y)
    p = 0.5 + 0.5 * math.sin(t * 7)
    if appear < 1.0:                                               # a new banner drops in and flashes bright
        e = 1.0 - (1.0 - max(0.0, appear)) ** 3
        r.y -= int((1.0 - e) * 46)
        p = max(p, 1.0 - e)
    key = ("banner", w, tuple(color))
    s = _overlays.get(key)
    if s is None:
        s = _overlays[key] = pygame.Surface(r.size, pygame.SRCALPHA)
        s.blit(_vgradient(r.size, K.mix(K.PANEL, color, 0.30), K.mix(K.PANEL, color, 0.12)), (0, 0))
        for x in range(-96, 40, 22):                               # hazard stripes, both ends
            for ox in (0, w - 44):
                pygame.draw.polygon(s, (*color, 70), [(ox + x, 96), (ox + x + 10, 96), (ox + x + 106, 0), (ox + x + 96, 0)])
        pygame.draw.rect(s, (0, 0, 0, 0), (44, 0, w - 88, 96))
        s.blit(_vgradient((w - 88, 96), K.mix(K.PANEL, color, 0.30), K.mix(K.PANEL, color, 0.12)), (44, 0))
        _rounded(s, 14)
        s.fill((255, 255, 255, 232), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(s, r.topleft)
    pygame.draw.rect(surf, K.mix(color, K.WHITE, 0.35 * p), r, 2 + int(p * 2), border_radius=14)
    ix, iy = r.left + 88, r.centery
    pygame.draw.polygon(surf, K.mix(color, K.WHITE, 0.2 * p), [(ix, iy - 32), (ix + 36, iy + 26), (ix - 36, iy + 26)])
    pygame.draw.polygon(surf, K.PANEL, [(ix, iy - 19), (ix + 25, iy + 20), (ix - 25, iy + 20)])
    fonts.text(surf, "!", (ix, iy + 3), 32, color, bold=True, anchor="center")
    fonts.text(surf, title, (r.centerx + 40, r.top + 34), 32, K.WHITE, bold=True, anchor="center", shadow=True)
    fonts.text(surf, sub, (r.centerx + 40, r.top + 72), 21, K.mix(color, K.WHITE, 0.55), anchor="center")
    return r

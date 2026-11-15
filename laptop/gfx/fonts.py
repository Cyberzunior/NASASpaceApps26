"""Fonts. Tries Segoe UI and Consolas, falls back to whatever exists, never crashes when they are missing."""
import pygame

_cache = {}


def reset():
    """Forget every font and rendered string (a new pygame session invalidates them)."""
    _cache.clear()
    _text_cache.clear()

import os

SANS = "segoeui,seguisemibold,helveticaneue,arial,dejavusans,liberationsans"
DISPLAY_FALLBACK = "bahnschrift,din alternate,avenirnextcondensed,segoeui,dejavusanscondensed,dejavusans,arial"  # used only if Doto is missing
MONO_FALLBACK = "consolas,menlo,dejavusansmono,liberationmono,couriernew"
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
# bundled open-licence faces (see assets/fonts/OFL-*.txt): titles use Doto (dot-matrix), numbers and code use JetBrains Mono
FILES = {"display": "Doto.ttf", "mono": "JetBrainsMono-Regular.ttf", "mono_bold": "JetBrainsMono-Bold.ttf"}


def _file(name):
    path = os.path.join(FONT_DIR, name)
    return path if os.path.isfile(path) else None


def get(size, mono=False, bold=False, display=False):
    key = (size, mono, bold, display)
    if key not in _cache:
        try:
            if display:
                path = _file(FILES["display"])
                _cache[key] = pygame.font.Font(path, size) if path else pygame.font.SysFont(DISPLAY_FALLBACK, size, bold=bold)
            elif mono:
                path = _file(FILES["mono_bold" if bold else "mono"])
                _cache[key] = pygame.font.Font(path, size) if path else pygame.font.SysFont(MONO_FALLBACK, size, bold=bold)
            else:
                _cache[key] = pygame.font.SysFont(SANS, size, bold=bold)
        except Exception:
            _cache[key] = pygame.font.Font(None, int(size * 1.2))
    return _cache[key]


_text_cache = {}


def _spaced(f, s, color, track):
    """Letter-spaced text (titles): each glyph on its own, `track` extra pixels apart."""
    glyphs = [f.render(ch, True, color) for ch in s]
    w = sum(g.get_width() for g in glyphs) + track * max(0, len(glyphs) - 1)
    out = pygame.Surface((max(1, w), f.get_linesize()), pygame.SRCALPHA)
    x = 0
    for g in glyphs:
        out.blit(g, (x, 0))
        x += g.get_width() + track
    return out


def _render(s, size, color, mono, bold, shadow, display=False, track=0):
    """Rendered text is cached: building a surface per string per frame was a big part of the HUD cost."""
    key = (s, size, color, mono, bold, shadow, display, track)
    img = _text_cache.get(key)
    if img is None:
        if len(_text_cache) > 900:
            _text_cache.clear()
        f = get(size, mono, bold, display)
        img = _spaced(f, s, color, track) if track else f.render(s, True, color)
        if shadow:
            sh = _spaced(f, s, (0, 0, 0), track) if track else f.render(s, True, (0, 0, 0))
            sh.set_alpha(150)
            both = pygame.Surface((img.get_width() + 2, img.get_height() + 2), pygame.SRCALPHA)
            both.blit(sh, (2, 2))
            both.blit(img, (0, 0))
            img = both
        _text_cache[key] = img
    return img


def text(surface, s, pos, size=24, color=(236, 242, 250), mono=False, bold=False, anchor="topleft", alpha=255, shadow=False,
         display=False, track=0):
    """Draw text and return its rect. anchor is any pygame rect attribute (topleft, center, midtop, topright...).
    display=True uses the title face, track adds letter spacing in pixels."""
    img = _render(str(s), size, tuple(color), mono, bold, shadow, display, track)
    r = img.get_rect()
    setattr(r, anchor, pos)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(alpha)
    surface.blit(img, r)
    return r


def width(s, size, mono=False, bold=False):
    return get(size, mono, bold).size(str(s))[0]

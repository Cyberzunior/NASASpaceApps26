"""One palette: deep navy space, cyan / blue accents, orange for danger, red for heat, ice blue for cold."""
BG = (5, 8, 20)
NAVY = (10, 16, 38)
PANEL = (10, 18, 40)
PANEL_EDGE = (40, 80, 130)
CYAN = (90, 220, 255)
BLUE = (70, 130, 255)
ICE = (150, 210, 255)
WHITE = (236, 242, 250)
GREY = (136, 150, 175)
DIM = (66, 78, 104)
ORANGE = (255, 150, 50)
YELLOW = (255, 214, 80)
RED = (255, 70, 70)
HEAT = (255, 90, 40)
GREEN = (80, 230, 140)
HULL = (225, 232, 245)
HULL_DARK = (110, 130, 165)
VIOLET = (190, 140, 255)
TRACK = (16, 26, 52)          # empty bar / field background
DOT = {"green": GREEN, "yellow": YELLOW, "red": RED}


_mix_cache = {}


def mix(a, b, t):
    """Blend two colours. Memoised: the HUD asks for the same 40-odd blends every frame."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    key = (a, b, t)
    c = _mix_cache.get(key)
    if c is None:
        if len(_mix_cache) > 1500:
            _mix_cache.clear()
        c = _mix_cache[key] = (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
                               int(a[2] + (b[2] - a[2]) * t))
    return c

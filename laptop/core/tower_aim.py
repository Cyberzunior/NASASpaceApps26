"""Where the tower points. The tower stands TOWER_BACK_CM behind the rover's start point and looks the way the rover faces at the
start (parallel lines of sight), so a point on the lunar surface maps to a yaw (bearing from the tower's forward) and a pitch
(down from level, from the laser height and the distance). The firmware only moves motors; everything here is geometry."""
import math

import config as C
from core.model import angdiff, start_pose


def tower_xy():
    """The tower's place in game metres: straight behind the rover's start point."""
    p = start_pose()
    a = math.radians(p.theta)
    d = C.TOWER_BACK_CM * C.METERS_PER_CM
    return p.x - d * math.cos(a), p.y - d * math.sin(a)


def angles(x, y):
    """(yaw, below): yaw in degrees from the tower's forward, positive to the right; below in degrees under level, so that the
    beam lands on the floor at the game point (x, y)."""
    tx, ty = tower_xy()
    dx, dy = x - tx, y - ty
    yaw = angdiff(math.degrees(math.atan2(dy, dx)), start_pose().theta) * C.TOWER_GAIN
    yaw = max(-C.TOWER_YAW_LIMIT_DEG, min(C.TOWER_YAW_LIMIT_DEG, yaw))
    cm = max(C.TOWER_MIN_CM, min(C.TOWER_MAX_CM, math.hypot(dx, dy) / C.METERS_PER_CM))
    below = math.degrees(math.atan2(C.TOWER_LASER_H_CM, cm)) * C.TOWER_GAIN
    return yaw, max(0.0, min(80.0, below))


def servo_for(below):
    """Servo angle for a beam `below` degrees under level (negative = above level, 90 up = straight up with below = -90)."""
    return C.TOWER_PITCH_LEVEL - C.TOWER_PITCH_DIR * below


def yaw_for(yaw):
    return C.TOWER_YAW_DIR * yaw


class TowerAim:
    """The tower's job in a run: sit at yaw 0 until the run starts, look left and right for TOWER_SCAN_S, then lock on the rover and
    follow it. While an asteroid is marked the beam sits on the marked spot instead, then goes back to the rover."""

    def __init__(self, link, log=None):
        self.link = link
        self.log = log or (lambda m: None)
        self.state = "idle"
        self.t = 0.0
        self.mark = None

    def start(self):
        """A run starts: yaw 0, then the scan."""
        self.state, self.t, self.mark = "scan", 0.0, None
        self.link.aim(0.0, None)                                   # yaw 0, pitch stays where it is
        self.log("tower: scan, then lock on the rover")

    def stop(self):
        self.state = "idle"
        self.link.idle()

    def update(self, dt, craft, mark=None):
        """Called every frame of a run. mark = (x, y) of a warned asteroid impact, or None."""
        if self.state == "idle" or not self.link.connected:
            return
        if self.state == "scan":
            self.t += dt
            if self.t < C.TOWER_SCAN_S:
                _, below = angles(craft.x, craft.y)
                self.link.aim(-C.TOWER_SCAN_DEG * C.TOWER_GAIN * math.sin(2 * math.pi * self.t / C.TOWER_SCAN_S), below)   # left first, then right
                return
            self.state = "track"
            self.log("tower: locked on the rover")
        x, y = mark if mark else (craft.x, craft.y)
        yaw, below = angles(x, y)
        if mark:
            below = max(below, C.TOWER_MARK_DOWN_DEG)              # the marked spot: beam clearly down onto the floor
        self.link.aim(yaw, below)

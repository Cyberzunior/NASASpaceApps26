"""The one movement model. The stick (or the auto-pilot) gives speed and turn in -1..1; mix() turns them into
the wheel command for the robot AND the exact speed / turn the game craft uses, so both bodies get the same numbers."""
import math
import config as C


def angdiff(a, b):
    """Smallest signed difference a - b in degrees."""
    return (a - b + 180.0) % 360.0 - 180.0


def shape_axis(x, dead=None, expo=None):
    """Dead zone (rescaled so motion starts from zero) then an expo curve for fine control near the centre."""
    dead = C.DEAD_ZONE if dead is None else dead
    expo = C.EXPO if expo is None else expo
    if abs(x) <= dead:
        return 0.0
    x = max(-1.0, min(1.0, x))
    y = (abs(x) - dead) / (1.0 - dead)
    y = (1.0 - expo) * y + expo * y ** 3
    return math.copysign(y, x)


def mix(speed, turn, k=None):
    """(speed, turn) -> (speed, turn, left, right). If a wheel would overflow, speed and turn are scaled together,
    so the game craft slows exactly like the robot does."""
    k = C.TURN_GAIN if k is None else k
    speed = max(-1.0, min(1.0, speed))
    turn = max(-1.0, min(1.0, turn))
    m = max(1.0, abs(speed + k * turn), abs(speed - k * turn))
    speed, turn = speed / m, turn / m
    return speed, turn, int(round(C.MAX_PWM * (speed + k * turn))), int(round(C.MAX_PWM * (speed - k * turn)))


def wheel_mix(speed, turn):
    return mix(speed, turn)[2:]


class Pose:
    """Position in metres on the lunar surface; theta in degrees, 0 = +x, increasing clockwise on the screen (y points down)."""
    __slots__ = ("x", "y", "theta")

    def __init__(self, x=0.0, y=0.0, theta=0.0):
        self.x, self.y, self.theta = x, y, theta

    def copy(self):
        return Pose(self.x, self.y, self.theta)

    def __repr__(self):
        return "Pose(%.1f, %.1f, %.0f)" % (self.x, self.y, self.theta)


def step_pose(pose, speed, turn, dt, turn_scale=1.0):
    """Advance a pose in place. speed / turn are the mixed values from mix(): the same numbers the real rover gets."""
    pose.theta = (pose.theta + turn * C.W_MAX * turn_scale * dt) % 360.0
    a = math.radians(pose.theta)
    d = speed * C.V_MAX * C.METERS_PER_CM * dt
    pose.x += d * math.cos(a)
    pose.y += d * math.sin(a)
    return pose


def start_pose():
    return Pose(0.0, 0.0, 270.0)           # facing up the screen


def bearing_to(pose, x, y):
    """Signed angle in degrees from the rover's heading to a point: negative = left, 0 = ahead, positive = right."""
    return angdiff(math.degrees(math.atan2(y - pose.y, x - pose.x)), pose.theta)

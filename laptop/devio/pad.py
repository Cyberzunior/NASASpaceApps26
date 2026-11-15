"""One gamepad layout for every pad. SDL's game controller database knows the Xbox wireless controller (Bluetooth, USB or
the wireless adapter), PlayStation, Switch Pro, 8BitDo and most others, and gives them one standard layout whatever the OS
or driver numbers the raw axes. open_pad() uses that layout when SDL knows the pad. Otherwise it falls back to the raw
joystick, and then the AXIS_* / BTN_* numbers in config.py apply (find them with tools/gamepad_test.py).

Every pad object here quacks like the parts of pygame's Joystick the game uses:
  get_name(), get_numaxes(), get_numbuttons(), get_axis(i), rumble(low, high, ms), and the attributes
  standard (True when the SDL layout is used), instance_id, and the axis numbers turn_axis, speed_axis, pan_axis,
  brake_axis, boost_axis.
Standard layout axes: 0 left X, 1 left Y (up is negative), 2 right X, 3 right Y, 4 left trigger, 5 right trigger
(sticks -1..1, triggers -1 released .. 1 pressed). Standard buttons are translated to the numbers config.py uses
(Xbox order: A 0, B 1, X 2, Y 3, LB 4, RB 5, Back 6, Start 7)."""
import pygame

import config as C

# SDL controller button -> the Xbox-order number used by BTN_* in config.py
_BUTTONS = {
    pygame.CONTROLLER_BUTTON_A: 0, pygame.CONTROLLER_BUTTON_B: 1, pygame.CONTROLLER_BUTTON_X: 2, pygame.CONTROLLER_BUTTON_Y: 3,
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: 4, pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: 5,
    pygame.CONTROLLER_BUTTON_BACK: 6, pygame.CONTROLLER_BUTTON_START: 7,
    pygame.CONTROLLER_BUTTON_LEFTSTICK: 8, pygame.CONTROLLER_BUTTON_RIGHTSTICK: 9,
}
_DPAD = {pygame.CONTROLLER_BUTTON_DPAD_UP: "up", pygame.CONTROLLER_BUTTON_DPAD_DOWN: "down",
         pygame.CONTROLLER_BUTTON_DPAD_LEFT: "left", pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "right"}
_AXES = (pygame.CONTROLLER_AXIS_LEFTX, pygame.CONTROLLER_AXIS_LEFTY, pygame.CONTROLLER_AXIS_RIGHTX, pygame.CONTROLLER_AXIS_RIGHTY,
         pygame.CONTROLLER_AXIS_TRIGGERLEFT, pygame.CONTROLLER_AXIS_TRIGGERRIGHT)


class ControllerPad:
    """A pad SDL has a standard mapping for (the Xbox wireless controller and most others)."""
    standard = True
    turn_axis, speed_axis, pan_axis, brake_axis, boost_axis = 0, 1, 2, 4, 5

    def __init__(self, ctrl):
        self.ctrl = ctrl
        try:
            self.instance_id = ctrl.as_joystick().get_instance_id()
        except Exception:
            self.instance_id = None

    def get_name(self):
        return self.ctrl.name

    def get_numaxes(self):
        return 6

    def get_numbuttons(self):
        return 10

    def get_axis(self, i):
        v = self.ctrl.get_axis(_AXES[i])
        if i >= 4:                                        # triggers read 0..32767: -1 released .. 1 pressed
            return max(-1.0, min(1.0, v / 32767.0 * 2.0 - 1.0))
        return max(-1.0, min(1.0, v / 32767.0))

    def rumble(self, low, high, ms):
        self.ctrl.rumble(low, high, ms)

    def init(self):
        pass


class RawPad:
    """A pad SDL has no mapping for: raw joystick numbers, set by AXIS_* and BTN_* in config.py."""
    standard = False

    def __init__(self, joy):
        self.joy = joy
        self.instance_id = joy.get_instance_id()
        self.turn_axis, self.speed_axis, self.pan_axis = C.AXIS_TURN, C.AXIS_SPEED, C.AXIS_PAN
        self.brake_axis, self.boost_axis = C.AXIS_BRAKE, C.AXIS_BOOST

    def get_name(self):
        return self.joy.get_name()

    def get_numaxes(self):
        return self.joy.get_numaxes()

    def get_numbuttons(self):
        return self.joy.get_numbuttons()

    def get_axis(self, i):
        return self.joy.get_axis(i)

    def rumble(self, low, high, ms):
        self.joy.rumble(low, high, ms)

    def init(self):
        pass


def init():
    """Call once after pygame.init()."""
    pygame.joystick.init()
    try:
        from pygame._sdl2 import controller
        controller.init()
    except Exception:
        pass


def open_pad(index):
    """The pad at joystick index `index`, using SDL's standard layout when it has one."""
    try:
        from pygame._sdl2 import controller
        if controller.is_controller(index):
            return ControllerPad(controller.Controller(index))
    except Exception:
        pass
    joy = pygame.joystick.Joystick(index)
    joy.init()
    return RawPad(joy)


def button_number(pad, e):
    """Button events -> (kind, number or direction) or None. kind is 'down' / 'up' / 'dpad'. For a standard pad only the
    controller events count (the joystick events of the same device are ignored); for a raw pad only the joystick events."""
    if pad is not None and pad.standard:
        if e.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            down = e.type == pygame.CONTROLLERBUTTONDOWN
            if e.button in _DPAD:
                return ("dpad", _DPAD[e.button]) if down else None
            n = _BUTTONS.get(e.button)
            return None if n is None else ("down" if down else "up", n)
        return None
    if e.type == pygame.JOYBUTTONDOWN:
        return ("down", e.button)
    if e.type == pygame.JOYBUTTONUP:
        return ("up", e.button)
    return None

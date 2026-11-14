"""Small custom widgets for the triage GUI (painted with QPainter, no OpenGL)."""
import math
import time
from collections import deque

from PyQt5 import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt


class RadarWidget(QtWidgets.QWidget):
    """Top-down view of the robot's ultrasonic sweep. 0 deg is straight ahead,
    positive angles are drawn to the right. Readings fade after a few seconds."""
    FADE_S = 3.0

    def __init__(self, max_cm=200, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.max_cm = max_cm
        self.points = deque(maxlen=300)     # (angle, cm, time)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(100)

    def add(self, angle, cm):
        self.points.append((angle, cm, time.monotonic()))

    def clear(self):
        self.points.clear()
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#f4f8f5"))
        cx, cy = self.width() / 2, self.height() - 14
        radius = min(self.width() / 2 - 12, self.height() - 28)
        rect = QtCore.QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        def r_of(cm):
            return min(cm, self.max_cm) / self.max_cm * radius

        # spec zones: <8 cm hardware stop, <25 cm danger, <40 cm warning
        for cm, colour in ((40, "#fff3c4"), (25, "#ffd9b0"), (8, "#ffb3b3")):
            rr = r_of(cm)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(colour))
            p.drawPie(QtCore.QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr), 0, 180 * 16)
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor("#9ccaae"), 1))
        for cm in range(50, self.max_cm + 1, 50):
            rr = r_of(cm)
            p.drawArc(QtCore.QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr), 0, 180 * 16)
            p.drawText(QtCore.QPointF(cx + 3, cy - rr - 2), f"{cm} cm")
        p.drawArc(rect, 0, 180 * 16)
        for ang in (-90, -45, 0, 45, 90):
            a = math.radians(ang)
            p.setPen(QtGui.QPen(QtGui.QColor("#5fa37c" if abs(ang) == 45 else "#9ccaae"), 1,
                                Qt.DashLine if abs(ang) == 45 else Qt.SolidLine))
            p.drawLine(QtCore.QPointF(cx, cy),
                       QtCore.QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a)))

        now = time.monotonic()
        newest = None
        for angle, cm, t in self.points:
            age = now - t
            if age > self.FADE_S:
                continue
            alpha = int(255 * (1 - age / self.FADE_S))
            a = math.radians(angle)
            no_echo = cm >= 400
            rr = radius if no_echo or cm > self.max_cm else r_of(cm)
            pt = QtCore.QPointF(cx + rr * math.sin(a), cy - rr * math.cos(a))
            colour = QtGui.QColor("#999999" if no_echo else "#1b9e55")
            colour.setAlpha(alpha)
            if no_echo or cm > self.max_cm:
                p.setPen(QtGui.QPen(colour, 1.5))
                p.setBrush(Qt.NoBrush)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(colour)
            p.drawEllipse(pt, 4, 4)
            newest = (angle, cm, a)
        if newest:
            _, _, a = newest
            p.setPen(QtGui.QPen(QtGui.QColor(30, 160, 90, 150), 2))
            p.drawLine(QtCore.QPointF(cx, cy),
                       QtCore.QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a)))
        p.setBrush(QtGui.QColor("#222222"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QtCore.QRectF(cx - 9, cy - 4, 18, 14), 3, 3)    # the robot
        p.setPen(QtGui.QColor("#555555"))
        p.drawText(8, 16, "red < 8 cm stop   orange < 25 cm danger   yellow < 40 cm warning")


class VideoWidget(QtWidgets.QLabel):
    """Shows the newest QImage, scaled to fit while keeping the aspect ratio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#000; color:#778;")
        self._img = None
        self.setText("no picture")

    def set_image(self, img):
        self._img = img
        self._rescale()

    def clear_image(self, text="no picture"):
        self._img = None
        self.clear()
        self.setText(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._img is not None:
            self.setPixmap(QtGui.QPixmap.fromImage(self._img).scaled(
                self.size(), Qt.KeepAspectRatio, Qt.FastTransformation))

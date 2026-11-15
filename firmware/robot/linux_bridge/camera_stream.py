"""Rover camera: Logitech C920 on the UNO Q's USB port (Linux side) -> MJPEG stream over Wi-Fi.

    python3 camera_stream.py [--device 0] [--port 8080] [--width 640] [--height 480] [--fps 15]

The game's Camera URL field points at  http://<rover ip>:8080/stream  (also /snapshot.jpg for one frame).
One thread grabs frames and keeps only the newest; each viewer gets the newest frame at most FPS times a second.
Start at 640 x 480, 15 fps. The wheel commands travel on a different UDP socket and are never blocked by this stream:
if steering lags anyway, lower --width / --height or --fps. Needs OpenCV (python3-opencv). Run it next to robot_bridge.py
as a second Python process of the App Lab app, or by hand. UNTESTED on a real board.
"""
import argparse
import http.server
import socketserver
import threading
import time

import cv2

latest = {"jpg": None, "stamp": 0.0}
lock = threading.Lock()


def grab(args):
    cap = None
    while True:
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            cap.set(cv2.CAP_PROP_FPS, args.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))      # the C920 compresses on the camera: light on the CPU
        ok, frame = cap.read()
        if not ok:
            cap.release()
            time.sleep(1.0)
            continue
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with lock:
                latest["jpg"], latest["stamp"] = jpg.tobytes(), time.time()


class Handler(http.server.BaseHTTPRequestHandler):
    fps = 15

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/snapshot"):
            with lock:
                jpg = latest["jpg"]
            if jpg is None:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        last = 0.0
        try:
            while True:
                with lock:
                    jpg, stamp = latest["jpg"], latest["stamp"]
                if jpg is None or stamp == last:
                    time.sleep(0.01)
                    continue
                last = stamp
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg) + jpg + b"\r\n")
                time.sleep(1.0 / self.fps)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=15)
    args = ap.parse_args()
    Handler.fps = args.fps
    threading.Thread(target=grab, args=(args,), daemon=True).start()
    print("camera stream on http://0.0.0.0:%d/stream  (%dx%d, %d fps)" % (args.port, args.width, args.height, args.fps))
    Server(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

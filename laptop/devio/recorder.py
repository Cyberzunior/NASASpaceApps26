"""Logging: logs/YYYYMMDD_HHMMSS.log (rotated, newest LOG_KEEP kept)."""
import glob
import logging
import os
import time
import config as C

ROOT = os.path.abspath(os.path.join(C.HERE, ".."))
LOG_DIR = os.path.join(ROOT, "logs")


def setup(debug=False):
    """Returns (log_function, path). Never raises: if the folder is read-only the game logs to the console only."""
    logger = logging.getLogger("tminus6")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    path = None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        old = sorted(glob.glob(os.path.join(LOG_DIR, "*.log")))
        for f in old[:max(0, len(old) - C.LOG_KEEP + 1)]:
            try:
                os.remove(f)
            except OSError:
                pass
        path = os.path.join(LOG_DIR, time.strftime("%Y%m%d_%H%M%S") + ".log")
        h = logging.FileHandler(path, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", "%H:%M:%S"))
        logger.addHandler(h)
    except OSError:
        pass
    if debug or path is None:
        logger.addHandler(logging.StreamHandler())
    return logger.info, path

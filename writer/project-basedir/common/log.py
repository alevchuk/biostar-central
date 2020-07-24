import logging
from prometheus_client import Gauge

LOG_COUNT = Gauge("log_count", "Count of log messages", ["level"])

try:
    from pathlib import Path
    HOME = str(Path.home())
except Exception:
    from os.path import expanduser
    HOME = expanduser("~")


class MetricsHandler(logging.StreamHandler):
    def __init__(self):
        logging.StreamHandler.__init__(self)

    def emit(self, record):
        LOG_COUNT.labels(record.levelname).inc()


def getLogger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s %(levelname).1s [%(filename)s:%(lineno)d] %(message)s')

    # Log to console (some)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Log to file (all)
    fh = logging.FileHandler("{}/log/{}.log".format(HOME, name))
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # collect metrics
    mh = MetricsHandler()
    mh.setLevel(logging.DEBUG)
    mh.setFormatter(formatter)
    logger.addHandler(mh)

    return logger


logger = getLogger("common")

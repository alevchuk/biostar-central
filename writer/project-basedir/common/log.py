import logging

try:
    from pathlib import Path
    HOME = str(Path.home())
except Exception:
    from os.path import expanduser
    HOME = expanduser("~")

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

    return logger


logger = getLogger("common")

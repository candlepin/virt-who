
import logging
import os

def init_logger():
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(_get_handler())

def _get_handler():
    path = '/var/log/rhsm/rhsm.log'
    try:
        if not os.path.isdir("/var/log/rhsm"):
            os.mkdir("/var/log/rhsm")
    except:
        pass
    fmt = '%(asctime)s [%(levelname)s]  @%(filename)s:%(lineno)d - %(message)s'

    # Try to write to /var/log, fallback on console logging:
    try:
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=0x100000, backupCount=5)
    except IOError:
        handler = logging.StreamHandler()
    except:
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(logging.DEBUG)

    return handler

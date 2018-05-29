# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import
import sys
import logging
import threading
import gc

import virtwho.main


def main():
    try:
        res = virtwho.main.main()
    except KeyboardInterrupt:
        virtwho.main.exit(1)
    except Exception as e:
        print(e, file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        logger = logging.getLogger("virtwho.main")
        logger.exception("Fatal error:")
        virtwho.main.exit(1, "virt-who failed: %s" % str(e))
    else:
        logger = logging.getLogger("virtwho.main")
        logger.debug("virt-who terminated")
        virtwho.main.exit(res)
    finally:
        for x in threading.enumerate():
            if x.name == 'QueueFeederThread' and x.ident is not None:
                x.join(1)


if __name__ == '__main__':
    main()

import sys
import logging
import virtwho.main


def main():
    try:
        res = virtwho.main.main()
    except KeyboardInterrupt:
        virtwho.main.exit(1)
    except Exception as e:
        print >>sys.stderr, e
        import traceback
        traceback.print_exc(file=sys.stderr)
        logger = logging.getLogger("virtwho.main")
        logger.exception("Fatal error:")
        virtwho.main.exit(1, "virt-who failed: %s" % str(e))
    logger = logging.getLogger("virtwho.main")
    logger.debug("virt-who terminated")
    virtwho.main.exit(res)

if __name__ == '__main__':
    main()

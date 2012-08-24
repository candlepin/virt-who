"""
Agent for reporting virtual guest IDs to subscription-manager

Copyright (C) 2011 Radek Novacek <rnovacek@redhat.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import sys
import os
import time
import atexit
import signal

from virt import Virt, VirtError
from vdsm import VDSM
from vsphere import VSphere
from event import virEventLoopPureStart
from subscriptionmanager import SubscriptionManager, SubscriptionManagerError

import logging
import log

from optparse import OptionParser, OptionGroup

class OptionParserEpilog(OptionParser):
    """ Epilog is new in Python 2.5, we need to support Python 2.4. """
    def __init__(self, description, epilog=None):
        self.myepilog = epilog
        OptionParser.__init__(self, description)

    def format_help(self, formatter=None):
        if formatter is None:
            formatter = self.formatter
        help = OptionParser.format_help(self, formatter)
        return help + "\n" + self.format_myepilog(formatter) + "\n"

    def format_myepilog(self, formatter=None):
        if self.myepilog is not None:
            return formatter.format_description(self.myepilog)
        else:
            return ""

from ConfigParser import NoOptionError

# Default interval to retry after unsuccessful run
RetryInterval = 60 # One minute
# Default interval for sending list of UUIDs
DefaultInterval = 3600 # Once per hour

PIDFILE = "/var/run/virt-who.pid"

class VirtWho(object):
    def __init__(self, logger, options):
        """
        VirtWho class provides bridge between virtualization supervisor and
        Subscription Manager.

        logger - logger instance
        options - options for virt-who, parsed from command line arguments
        """
        self.logger = logger
        self.options = options

        self.virt = None
        self.subscriptionManager = None

        self.unableToRecoverStr = "Unable to recover"
        if not options.oneshot:
            self.unableToRecoverStr += ", retry in %d seconds." % RetryInterval

        # True if reload is queued
        self.doReload = False


    def initVirt(self):
        """
        Connect to the virtualization supervisor (libvirt or VDSM)
        """
        if self.options.virtType == "vdsm":
            self.virt = VDSM(self.logger)
        elif self.options.virtType == "libvirt":
            self.virt = Virt(self.logger, registerEvents=not self.options.oneshot)
            # We can listen for libvirt events
            self.tryRegisterEventCallback()
        else:
            # ESX
            self.virt = VSphere(self.logger, self.options.esx_server, self.options.esx_username, self.options.esx_password)

    def initSM(self):
        """
        Connect to the subscription manager (candlepin).
        """
        try:
            self.subscriptionManager = SubscriptionManager(self.logger)
            self.subscriptionManager.connect()
        except NoOptionError, e:
            self.logger.exception("Error in reading configuration file (/etc/rhsm/rhsm.conf):")
            return
        except SubscriptionManagerError, e:
            self.logger.exception("Unable to obtain status from server, UEPConnection is likely not usable:")
            return

        if self.options.virtType == "libvirt":
            self.tryRegisterEventCallback()

    def tryRegisterEventCallback(self):
        """
        This method register the handler which listen to guest changes

        If virt-who is running in background mode with libvirt backend, it can
        monitor virt guests changes and send updates as soon as the change happens,

        """
        if self.options.background and self.options.virtType == "libvirt":
            if self.virt is not None and self.subscriptionManager is not None:
                # Send list of virt guests when something changes in libvirt
                self.virt.domainEventRegisterCallback(self.subscriptionManager.sendVirtGuests)

    def checkConnections(self):
        """
        Check if connection to subscription manager and virtualization supervisor
        is established and reconnect if needed.
        """
        if self.subscriptionManager is None:
            self.initSM()
        if self.virt is None:
            self.initVirt()

    def send(self):
        """
        Send list of uuids to subscription manager

        return - True if sending is successful, False otherwise
        """
        # Try to send it twice
        return self._send(True)

    def _send(self, retry):
        """
        Send list of uuids to subscription manager. This method will call itself
        once if sending fails.

        retry - Should be True on first run, False on second.
        return - True if sending is successful, False otherwise
        """
        logger = self.logger
        try:
            self.checkConnections()
        except Exception,e:
            if retry:
                logger.exception("Unable to create connection:")
                return self._send(False)
            else:
                logger.error(self.unableToRecoverStr)
                return False

        try:
            if self.options.virtType != "esx":
                virtualGuests = self.virt.listDomains()
            else:
                virtualGuests = self.virt.getHostGuestMapping()
        except Exception, e:
            # Communication with virtualization supervisor failed
            self.virt = None
            # Retry once
            if retry:
                logger.exception("Error in communication with virt backend, trying to recover:")
                return self._send(False)
            else:
                logger.error(self.unableToRecoverStr)
                return False

        try:
            if self.options.virtType != "esx":
                self.subscriptionManager.sendVirtGuests(virtualGuests)
            else:
                result = self.subscriptionManager.hypervisorCheckIn(self.options.esx_owner, self.options.esx_env, virtualGuests)

                # Show the result of hypervisorCheckIn
                for fail in result['failedUpdate']:
                    logger.error("Error during update list of guests: %s", str(fail))
                for updated in result['updated']:
                    guests = [x['guestId'] for x in updated['guestIds']]
                    logger.info("Updated host: %s with guests: [%s]", updated['uuid'], ", ".join(guests))
                for created in result['created']:
                    guests = [x['guestId'] for x in created['guestIds']]
                    logger.info("Created host: %s with guests: [%s]", created['uuid'], ", ".join(guests))
        except Exception, e:
            # Communication with subscription manager failed
            self.subscriptionManager = None
            # Retry once
            if retry:
                logger.exception("Error in communication with subscription manager, trying to recover:")
                return self._send(False)
            else:
                logger.error(self.unableToRecoverStr)
                return False

        return True

    def ping(self):
        """
        Test if connection to virtualization manager is alive.

        return - True if connection is alive, False otherwise
        """
        if self.virt is None:
            return False
        return self.virt.ping()

    def queueReload(self, *p):
        """
        Reload virt-who configuration. Called on SIGHUP signal arrival.
        """
        self.doReload = True

    def reloadConfig(self):
        if self.virt and self.virt.virt:
            self.virt.virt.close()
        self.virt = None
        self.subscriptionManager = None
        self.checkConnections()
        self.logger.debug("virt-who configution reloaded")
        self.doReload = False


def daemonize(debugMode):
    """ Perform double-fork and redirect std* to /dev/null """

    # First fork
    try:
        pid = os.fork()
    except OSError:
        return False

    if pid > 0:
        # Parent process
        os._exit(0)

    # First child process

    # Create session and set process group ID
    os.setsid()

    # Second fork
    try:
        pid = os.fork()
    except OSError:
        return False

    if pid > 0:
        # Parent process
        os._exit(0)

    # Second child process

    # Redirect std* to /dev/null
    devnull = os.open("/dev/null", os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    # Don't redirect stderr in debug mode, we need to write debugging output there
    if not debugMode:
        os.dup2(devnull, 2)

    # Reset file creation mask
    os.umask(0)
    # Forget current working directory
    os.chdir("/")
    return True

def createPidFile(logger):
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Write pid to pidfile
    try:
        f = open(PIDFILE, "w")
        f.write("%d" % os.getpid())
        f.close()
    except Exception, e:
        logger.error("Unable to create pid file: %s" % str(e))

def cleanup(sig=None, stack=None):
    try:
        os.remove(PIDFILE)
    except Exception:
        pass

    if sig is not None and sig in [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]:
        sys.exit(0)

def main():
    if os.access(PIDFILE, os.F_OK):
        print >>sys.stderr, "virt-who seems to be already running. If not, remove %s" % PIDFILE
        sys.exit(1)

    parser = OptionParserEpilog(description="Agent for reporting virtual guest IDs to subscription-manager",
                                epilog="virt-who also reads enviromental variables. They have the same name as command line arguments but uppercased, with underscore instead of dash and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are considered as disabled, non-empty as enabled")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-b", "--background", action="store_true", dest="background", default=False, help="Run in the background and monitor virtual guests")
    parser.add_option("-o", "--one-shot", action="store_true", dest="oneshot", default=False, help="Send the list of guest IDs and exit immediately")
    parser.add_option("-i", "--interval", type="int", dest="interval", default=0, help="Acquire and send list of virtual guest each N seconds")
    parser.add_option("--libvirt", action="store_const", dest="virtType", const="libvirt", default="libvirt", help="Use libvirt to list virtual guests [default]")
    parser.add_option("--vdsm", action="store_const", dest="virtType", const="vdsm", help="Use vdsm to list virtual guests")
    parser.add_option("--esx", action="store_const", dest="virtType", const="esx", help="Register ESX machines using vCenter")

    esxGroup = OptionGroup(parser, "vCenter/ESX options", "Use this options with --esx")
    esxGroup.add_option("--esx-owner", action="store", dest="esx_owner", default="", help="Organization who has purchased subscriptions of the products")
    esxGroup.add_option("--esx-env", action="store", dest="esx_env", default="", help="Environment where the vCenter server belongs to")
    esxGroup.add_option("--esx-server", action="store", dest="esx_server", default="", help="URL of the vCenter server to connect to")
    esxGroup.add_option("--esx-username", action="store", dest="esx_username", default="", help="Username for connecting to vCenter")
    esxGroup.add_option("--esx-password", action="store", dest="esx_password", default="", help="Password for connecting to vCenter")
    parser.add_option_group(esxGroup)


    (options, args) = parser.parse_args()

    # Handle enviromental variables

    env = os.getenv("VIRTWHO_DEBUG", "0").strip().lower()
    if env in ["1", "true"]:
        options.debug = True

    env = os.getenv("VIRTWHO_BACKGROUND", "0").strip().lower()
    if env in ["1", "true"]:
        options.background = True

    logger = log.getLogger(options.debug, options.background)

    env = os.getenv("VIRTWHO_ONE_SHOT", "0").strip().lower()
    if env in ["1", "true"]:
        options.oneshot = True

    env = os.getenv("VIRTWHO_INTERVAL", "0").strip().lower()
    try:
        if int(env) > 0 and options.interval == 0:
            options.interval = int(env)
    except ValueError:
        logger.warning("Interval is not number, ignoring")

    env = os.getenv("VIRTWHO_VDSM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "vdsm"

    env = os.getenv("VIRTWHO_ESX", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "esx"

    def checkEnv(variable, option, name):
        """
        If `option` is empty, check enviromental `variable` and return its value.
        Exit if it's still empty
        """
        if len(option) == 0:
            option = os.getenv(variable, "").strip()
        if len(option) == 0:
            logger.error("Required parameter '%s' for vCenter is not set, exitting" % name)
            sys.exit(1)
        return option

    if options.virtType == "esx":
        options.esx_owner = checkEnv("VIRTWHO_ESX_OWNER", options.esx_owner, "owner")
        options.esx_env = checkEnv("VIRTWHO_ESX_ENV", options.esx_env, "env")
        options.esx_server = checkEnv("VIRTWHO_ESX_SERVER", options.esx_server, "server")
        options.esx_username = checkEnv("VIRTWHO_ESX_USERNAME", options.esx_username, "username")
        if len(options.esx_password) == 0:
            options.esx_password = os.getenv("VIRTWHO_ESX_PASSWORD", "")

    # Url must contain protocol (usualy https://)
    if not "://" in options.esx_server:
        options.esx_server = "https://%s" % options.esx_server

    if options.interval < 0:
        logger.warning("Interval is not positive number, ignoring")
        options.interval = 0

    if options.background and options.oneshot:
        logger.error("Background and oneshot can't be used together, using background mode")
        options.oneshot = False

    if options.oneshot and options.interval > 0:
        logger.error("Interval doesn't make sense in oneshot mode, ignoring")

    if not options.oneshot and options.interval == 0:
        # Interval is still used in background mode, because events can get lost
        # (e.g. libvirtd restart)
        options.interval = DefaultInterval

    if options.background:
        # Do a double-fork and other daemon initialization
        if not daemonize(options.debug):
            logger.error("Unable to fork, continuing in foreground")

    if not options.oneshot:
        if options.background and options.virtType == "libvirt":
            logger.debug("Starting event loop")
            virEventLoopPureStart()
        else:
            logger.warning("Listening for events is not available in VDSM or ESX mode")

    global RetryInterval
    if options.interval < RetryInterval:
        RetryInterval = options.interval

    virtWho = VirtWho(logger, options)
    signal.signal(signal.SIGHUP, virtWho.queueReload)
    try:
        virtWho.checkConnections()
    except Exception:
        pass

    createPidFile(logger)

    logger.debug("Virt-who is running in %s mode" % options.virtType)

    if options.oneshot:
        # Send list of virtual guests and exit
        virtWho.send()
    else:
        if options.background:
            logger.debug("Starting infinite loop with %d seconds interval and event handling" % options.interval)
        else:
            logger.debug("Starting infinite loop with %d seconds interval" % options.interval)

        while 1:
            # Run in infinite loop and send list of UUIDs every 'options.interval' seconds

            if virtWho.send():
                # Check if connection is established each 'RetryInterval' seconds
                slept = 0
                while slept < options.interval:
                    # Sleep 'RetryInterval' or the rest of options.interval
                    t = min(RetryInterval, options.interval - slept)
                    # But sleep at least one second
                    t = max(t, 1)
                    time.sleep(t)
                    slept += t

                    # Reload configuration if queued
                    if virtWho.doReload:
                        virtWho.reloadConfig()
                        break

                    # Check the connection
                    if not virtWho.ping():
                        # End the cycle
                        break
            else:
                # If last send fails, new try will be sooner
                time.sleep(RetryInterval)

if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception, e:
        logger = log.getLogger(False, False)
        logger.exception("Fatal error:")
        sys.exit(1)

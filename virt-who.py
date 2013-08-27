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
from rhevm import RHEVM
from hyperv import HyperV
from event import virEventLoopPureStart
from subscriptionmanager import SubscriptionManager, SubscriptionManagerError
from satellite import Satellite, SatelliteError

import logging
import log

from optparse import OptionParser, OptionGroup

class OptionParserEpilog(OptionParser):
    """ Epilog is new in Python 2.5, we need to support Python 2.4. """
    def __init__(self, usage="%prog [options]", description=None, epilog=None):
        self.myepilog = epilog
        OptionParser.__init__(self, usage=usage, description=description)

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
            self.virt = Virt(self.logger, registerEvents=self.options.background)
            # We can listen for libvirt events
            self.tryRegisterEventCallback()
        elif self.options.virtType == "rhevm":
            self.virt = RHEVM(self.logger, self.options.server, self.options.username, self.options.password)
        elif self.options.virtType == "hyperv":
            self.virt = HyperV(self.logger, self.options.server, self.options.username, self.options.password)
        else:
            # ESX
            self.virt = VSphere(self.logger, self.options.server, self.options.username, self.options.password)

    def initSM(self):
        """
        Connect to the subscription manager (candlepin).
        """
        try:
            if self.options.smType == "rhsm":
                self.subscriptionManager = SubscriptionManager(self.logger)
                self.subscriptionManager.connect()
            elif self.options.smType == "satellite":
                self.subscriptionManager = Satellite(self.logger)
                self.subscriptionManager.connect(self.options.sat_server, self.options.sat_username, self.options.sat_password)
        except NoOptionError, e:
            self.logger.exception("Error in reading configuration file (/etc/rhsm/rhsm.conf):")
            raise
        except SubscriptionManagerError, e:
            self.logger.exception("Unable to obtain status from server, UEPConnection is likely not usable:")
            raise
        except SatelliteError, e:
            self.logger.exception("Unable to connect to the RHN Satellite:")
            raise
        except Exception, e:
            self.logger.exception("Unknown error")
            raise

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
            if self.options.virtType not in ["esx", "rhevm", "hyperv"]:
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
            if self.options.virtType not in ["esx", "rhevm", "hyperv"]:
                self.subscriptionManager.sendVirtGuests(virtualGuests)
            else:
                result = self.subscriptionManager.hypervisorCheckIn(self.options.owner, self.options.env, virtualGuests, type=self.options.virtType)

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
        try:
            self.virt.virt.close()
        except AttributeError:
            pass
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

def createPidFile(logger=None):
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Write pid to pidfile
    try:
        f = open(PIDFILE, "w")
        f.write("%d" % os.getpid())
        f.close()
    except Exception, e:
        if logger is not None:
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
    createPidFile()

    parser = OptionParserEpilog(usage="virt-who [-d] [-i INTERVAL] [-b] [-o] [--sam|--satellite] [--libvirt|--vdsm|--esx|--rhevm|--hyperv]",
                                description="Agent for reporting virtual guest IDs to subscription manager",
                                epilog="virt-who also reads enviromental variables. They have the same name as command line arguments but uppercased, with underscore instead of dash and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are considered as disabled, non-empty as enabled")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-b", "--background", action="store_true", dest="background", default=False, help="Run in the background and monitor virtual guests")
    parser.add_option("-o", "--one-shot", action="store_true", dest="oneshot", default=False, help="Send the list of guest IDs and exit immediately")
    parser.add_option("-i", "--interval", type="int", dest="interval", default=0, help="Acquire and send list of virtual guest each N seconds")

    virtGroup = OptionGroup(parser, "Virtualization backend", "Choose virtualization backend that should be used to gather host/guest associations")
    virtGroup.add_option("--libvirt", action="store_const", dest="virtType", const="libvirt", default="libvirt", help="Use libvirt to list virtual guests [default]")
    virtGroup.add_option("--vdsm", action="store_const", dest="virtType", const="vdsm", help="Use vdsm to list virtual guests")
    virtGroup.add_option("--esx", action="store_const", dest="virtType", const="esx", help="Register ESX machines using vCenter")
    virtGroup.add_option("--rhevm", action="store_const", dest="virtType", const="rhevm", help="Register guests using RHEV-M")
    virtGroup.add_option("--hyperv", action="store_const", dest="virtType", const="hyperv", help="Register guests using Hyper-V")
    parser.add_option_group(virtGroup)

    managerGroup = OptionGroup(parser, "Subscription manager", "Choose where the host/guest associations should be reported")
    managerGroup.add_option("--sam", action="store_const", dest="smType", const="sam", help="Report host/guest associations to the Subscription Asset Manager [default]")
    managerGroup.add_option("--satellite", action="store_const", dest="smType", const="satellite", help="Report host/guest associations to the Satellite")
    parser.add_option_group(managerGroup)

    esxGroup = OptionGroup(parser, "vCenter/ESX options", "Use this options with --esx")
    esxGroup.add_option("--esx-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    esxGroup.add_option("--esx-env", action="store", dest="env", default="", help="Environment where the vCenter server belongs to")
    esxGroup.add_option("--esx-server", action="store", dest="server", default="", help="URL of the vCenter server to connect to")
    esxGroup.add_option("--esx-username", action="store", dest="username", default="", help="Username for connecting to vCenter")
    esxGroup.add_option("--esx-password", action="store", dest="password", default="", help="Password for connecting to vCenter")
    parser.add_option_group(esxGroup)

    rhevmGroup = OptionGroup(parser, "RHEV-M options", "Use this options with --rhevm")
    rhevmGroup.add_option("--rhevm-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    rhevmGroup.add_option("--rhevm-env", action="store", dest="env", default="", help="Environment where the RHEV-M belongs to")
    rhevmGroup.add_option("--rhevm-server", action="store", dest="server", default="", help="URL of the RHEV-M server to connect to (preferable use secure connection - https://<ip or domain name>:<secure port, usually 8443>)")
    rhevmGroup.add_option("--rhevm-username", action="store", dest="username", default="", help="Username for connecting to RHEV-M in the format username@domain")
    rhevmGroup.add_option("--rhevm-password", action="store", dest="password", default="", help="Password for connecting to RHEV-M")
    parser.add_option_group(rhevmGroup)

    hypervGroup = OptionGroup(parser, "Hyper-V options", "Use this options with --hyperv")
    hypervGroup.add_option("--hyperv-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    hypervGroup.add_option("--hyperv-env", action="store", dest="env", default="", help="Environment where the Hyper-V belongs to")
    hypervGroup.add_option("--hyperv-server", action="store", dest="server", default="", help="URL of the Hyper-V server to connect to")
    hypervGroup.add_option("--hyperv-username", action="store", dest="username", default="", help="Username for connecting to Hyper-V")
    hypervGroup.add_option("--hyperv-password", action="store", dest="password", default="", help="Password for connecting to Hyper-V")
    parser.add_option_group(hypervGroup)

    satelliteGroup = OptionGroup(parser, "Satellite options", "Use this options with --satellite")
    satelliteGroup.add_option("--satellite-server", action="store", dest="sat_server", default="", help="Satellite server URL")
    satelliteGroup.add_option("--satellite-username", action="store", dest="sat_username", default="", help="Username for connecting to Satellite server")
    satelliteGroup.add_option("--satellite-password", action="store", dest="sat_password", default="", help="Password for connecting to Satellite server")
    parser.add_option_group(satelliteGroup)

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

    env = os.getenv("VIRTWHO_SAM", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = "sam"

    env = os.getenv("VIRTWHO_SATELLITE", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = "satellite"

    env = os.getenv("VIRTWHO_VDSM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "vdsm"

    env = os.getenv("VIRTWHO_ESX", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "esx"

    env = os.getenv("VIRTWHO_RHEVM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "rhevm"

    env = os.getenv("VIRTWHO_HYPERV", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "hyperv"


    def checkEnv(variable, option, name):
        """
        If `option` is empty, check enviromental `variable` and return its value.
        Exit if it's still empty
        """
        if len(option) == 0:
            option = os.getenv(variable, "").strip()
        if len(option) == 0:
            logger.error("Required parameter '%s' is not set, exitting" % name)
            sys.exit(1)
        return option

    if options.smType == "satellite":
        options.sat_server = checkEnv("VIRTWHO_SATELLITE_SERVER", options.sat_server, "satellite-server")
        if len(options.sat_username) == 0:
            options.sat_username = os.getenv("VIRTWHO_SATELLITE_USERNAME", "")
        if len(options.sat_password) == 0:
            options.sat_password = os.getenv("VIRTWHO_SATELLITE_PASSWORD", "")

        if len(options.sat_username) == 0:
            logger.info('Satellite username is not specified, assuming preregistered system')

    if options.virtType == "esx":
        options.owner = checkEnv("VIRTWHO_ESX_OWNER", options.owner, "owner")
        options.env = checkEnv("VIRTWHO_ESX_ENV", options.env, "env")
        options.server = checkEnv("VIRTWHO_ESX_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_ESX_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_ESX_PASSWORD", "")

    if options.virtType == "rhevm":
        options.owner = checkEnv("VIRTWHO_RHEVM_OWNER", options.owner, "owner")
        options.env = checkEnv("VIRTWHO_RHEVM_ENV", options.env, "env")
        options.server = checkEnv("VIRTWHO_RHEVM_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_RHEVM_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_RHEVM_PASSWORD", "")

    if options.virtType == "hyperv":
        options.owner = checkEnv("VIRTWHO_HYPERV_OWNER", options.owner, "owner")
        options.env = checkEnv("VIRTWHO_HYPERV_ENV", options.env, "env")
        options.server = checkEnv("VIRTWHO_HYPERV_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_HYPERV_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_HYPERV_PASSWORD", "")

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
        createPidFile(logger)

    if not options.oneshot:
        if options.background and options.virtType == "libvirt":
            logger.debug("Starting event loop")
            virEventLoopPureStart()
        else:
            logger.warning("Listening for events is not available in VDSM, ESX, RHEV-M or Hyper-V mode")

    global RetryInterval
    if options.interval < RetryInterval:
        RetryInterval = options.interval

    virtWho = VirtWho(logger, options)
    signal.signal(signal.SIGHUP, virtWho.queueReload)
    try:
        virtWho.checkConnections()
    except Exception:
        pass

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

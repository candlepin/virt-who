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

from virt import Virt, VirtError
from vdsm import VDSM
from vsphere import VSphere
from event import virEventLoopPureStart
from subscriptionmanager import SubscriptionManager, SubscriptionManagerError

import logging
import log

from optparse import OptionParser, OptionGroup

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

    def initVirt(self):
        """
        Connect to the virtualization supervisor (libvirt or VDSM)
        """
        if self.options.virtType == "vdsm":
            self.virt = VDSM(self.logger)
        elif self.options.virtType == "libvirt":
            self.virt = Virt(self.logger)
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
            self.tryRegisterEventCallback()
        except NoOptionError, e:
            self.logger.error("Error in reading configuration file (/etc/rhsm/rhsm.conf): %s" % e)
            # Unability to parse configuration file is fatal error, so we'll quit
            sys.exit(4)
        except Exception, e:
            raise e

    def tryRegisterEventCallback(self):
        """
        This method register the handler which listen to guest changes

        If virt-who is running in background mode with libvirt backend, it can
        monitor virt guests changes and send updates as soon as the change happens,

        """
        if self.options.background and self.options.virtType == "libvirt":
            if self.virt is not None and self.subscriptionManager is not None:
                # Send list of virt guests when something changes in libvirt
                self.virt.domainListChangedCallback(self.subscriptionManager.sendVirtGuests)
                # Register listener for domain changes
                self.virt.virt.domainEventRegister(self.virt.changed, None)

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
            if self.options.virtType == "esx":
                result = self.subscriptionManager.hypervisorCheckIn(self.options.esx_owner, self.options.esx_env, self.virt.getHostGuestMapping())
                # Show the result of hypervisorCheckIn
                for fail in result['failedUpdate']:
                    logger.error("Error during update list of guests: %s", str(fail))
                for updated in result['updated']:
                    guests = [x['guestId'] for x in updated['guestIds']]
                    logger.info("Updated host: %s with guests: [%s]", updated['uuid'], ", ".join(guests))
                for created in result['created']:
                    guests = [x['guestId'] for x in created['guestIds']]
                    logger.info("Created host: %s with guests: [%s]", created['uuid'], ", ".join(guests))
            else:
                self.subscriptionManager.sendVirtGuests(self.virt.listDomains())
            return True
        except SystemExit,e:
            # In python2.4 SystemExit is inherited from Exception, so must be catched extra
            raise e
        except VirtError, e:
            # Communication with virtualization supervisor failed
            logger.exception(e)
            self.virt = None
            # Retry once
            if retry:
                logger.error("Error in communication with virt backend, trying to recover")
                return self._send(False)
            else:
                logger.error("Unable to recover, retry in %d seconds." % RetryInterval)
                return False
        except SubscriptionManagerError, e:
            # Communication with subscription manager failed
            logger.exception(e)
            self.subscriptionManager = None
            # Retry once
            if retry:
                logger.error("Error in communication with candlepin, trying to recover")
                return self._send(False)
            else:
                logger.error("Unable to recover, retry in %d seconds." % RetryInterval)
                return False
        except Exception, e:
            # Some other error happens
            logger.exception(e)
            self.virt = None
            self.subscriptionManager = None
            # Retry once
            if retry:
                logger.error("Unexcepted error occurs, trying to recover")
                return self._send(False)
            else:
                logger.error("Unable to recover, retry in %d seconds." % RetryInterval)
                return False

    def ping(self):
        """
        Test if connection to virtualization manager is alive.

        return - True if connection is alive, False otherwise
        """
        if self.virt is None:
            return False
        return self.virt.ping()

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

    # Write pid to pidfile
    try:
        f = open(PIDFILE, "w")
        f.write("%d" % os.getpid())
        f.close()
    except Exception, e:
        logger.error("Unable to create pid file: %s" % str(e))

def cleanup():
    try:
        os.remove(PIDFILE)
    except Exception:
        pass

if __name__ == '__main__':
    if os.access(PIDFILE, os.F_OK):
        print >>sys.stderr, "virt-who seems to be already running. If not, remove %s" % PIDFILE
        sys.exit(1)

    log.init_logger()

    logger = logging.getLogger("rhsm-app." + __name__)

    parser = OptionParser(description="Agent for reporting virtual guest IDs to subscription-manager")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-b", "--background", action="store_true", dest="background", default=False, help="Run in the background and monitor virtual guests")
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
    if options.debug:
        # Enable debugging output to be writen in /var/log
        logger.setLevel(logging.DEBUG)

        # Print debugging output to stderr too
        logger.addHandler(logging.StreamHandler())
    else:
        logger.setLevel(logging.INFO)

    env = os.getenv("VIRTWHO_BACKGROUND", "0").strip().lower()
    if env in ["1", "true"]:
        options.background = True

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

    if options.background and options.interval == 0:
        # Interval is still used in background mode, because events can get lost
        # (e.g. libvirtd restart)
        options.interval = DefaultInterval

    if options.background:
        # Do a double-fork and other daemon initialization
        if not daemonize(options.debug):
            logger.error("Unable to fork, continuing in foreground")

    if options.background:
        if options.virtType == "libvirt":
            virEventLoopPureStart()
        else:
            logger.warning("Listening for events is not available in VDSM or ESX mode")

    virtWho = VirtWho(logger, options)
    virtWho.checkConnections()

    createPidFile(logger)

    logger.debug("Virt-who is running in %s mode" % options.virtType)

    if options.interval > 0:
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
                    time.sleep(t)
                    slept += t
                    # Check the connection
                    if not virtWho.ping():
                        # End the cycle
                        break
            else:
                # If last send fails, new try will be sooner
                time.sleep(RetryInterval)
    else:
        # Send list of virtual guests and exit
        virtWho.send()

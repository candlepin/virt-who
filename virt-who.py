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

from virt import Virt, VirtError
from vdsm import VDSM
from event import virEventLoopPureStart
from subscriptionmanager import SubscriptionManager, SubscriptionManagerError

import logging
import log

from optparse import OptionParser

from ConfigParser import NoOptionError

# Default interval to retry after unsuccessful run
RetryInterval = 60 # One minute
# Default interval for sending list of UUIDs
DefaultInterval = 3600 # Once per hour

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
        if self.options.useVDSM:
            self.virt = VDSM(self.logger)
        else:
            self.virt = Virt(self.logger)
            # We can listen for libvirt events
            self.tryRegisterEventCallback()

    def initSM(self):
        """
        Connect to the subscription manager (candlepin).
        """
        try:
            self.subscriptionManager = SubscriptionManager(self.logger)
            self.subscriptionManager.connect()
            self.tryRegisterEventCallback()
        except NoOptionError, e:
            logger.error("Error in reading configuration file (/etc/rhsm/rhsm.conf): %s" % e)
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
        if self.options.background and not self.options.useVDSM:
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
        try:
            self.checkConnections()
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

if __name__ == '__main__':
    log.init_logger()

    logger = logging.getLogger("rhsm-app." + __name__)

    parser = OptionParser(description="Agent for reporting virtual guest IDs to subscription-manager")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-b", "--background", action="store_true", dest="background", default=False, help="Run in the background and monitor virtual guests")
    parser.add_option("-i", "--interval", type="int", dest="interval", default=0, help="Acquire and send list of virtual guest each N seconds")
    parser.add_option("--libvirt", action="store_false", dest="useVDSM", default=False, help="Use libvirt to list virtual guests [default]")
    parser.add_option("--vdsm", action="store_true", dest="useVDSM", default=False, help="Use vdsm to list virtual guests")

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
        options.useVDSM = True

    if options.interval < 0:
        logger.warning("Interval is not positive number, ignoring")
        options.interval = 0

    if options.background and options.interval == 0:
        # Interval is still used in background mode, because events can get lost
        # (e.g. libvirtd restart)
        options.interval = DefaultInterval

    if options.background and options.useVDSM:
        logger.error("Unable to start in background in VDSM mode, use interval instead")
        sys.exit(4)

    if options.background:
        try:
            pid = os.fork()
        except OSError:
            logger.error("Unable to fork, continuing in foreground")
            pid = 0

        if pid > 0:
            # Parent process
            sys.exit(0)

        # Write pid to pidfile
        try:
            f = open("/var/run/virt-who.pid", "w")
            f.write("%d" % os.getpid())
            f.close()
        except Exception, e:
            logger.error("Unable to create pid file: %s" % str(e))

        if not options.useVDSM:
            virEventLoopPureStart()

    virtWho = VirtWho(logger, options)

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
                    t = min(RetryInterval, options.interval - RetryInterval)
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

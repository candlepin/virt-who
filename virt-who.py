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

from virt import Virt
from event import virEventLoopPureStart
from subscriptionmanager import SubscriptionManager

import logging
import log

from optparse import OptionParser

from ConfigParser import NoOptionError


if __name__ == '__main__':
    log.init_logger()

    logger = logging.getLogger("rhsm-app." + __name__)

    parser = OptionParser(description="Agent for reporting virtual guest IDs to subscription-manager")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-b", "--background", action="store_true", dest="background", default=False, help="Run in the background and monitor virtual guests")

    (options, args) = parser.parse_args()

    if options.debug:
        # Enable debugging output to be writen in /var/log
        logger.setLevel(logging.DEBUG)
        # Print debugging output to stderr too
        logger.addHandler(logging.StreamHandler())

    if options.background:
        virEventLoopPureStart()

    try:
        subscriptionManager = SubscriptionManager(logger)
    except NoOptionError, e:
        logger.error("Error in reading configuration file (/etc/rhsm/rhsm.conf): %s" % e)
        sys.exit(2)

    virt = Virt(logger)

    subscriptionManager.connect()

    if options.background:
        # Run rhsm.sendVirtGuests when something changes in libvirt
        virt.domainListChangedCallback(subscriptionManager.sendVirtGuests)
        # Register listener for domain changes
        virt.virt.domainEventRegister(virt.changed, None)
        # Send current virt guests
        subscriptionManager.sendVirtGuests(virt.listDomains())
        # libvirt event loop is running in separate thread, wait forever
        logger.debug("Entering infinite loop")
        while 1:
            time.sleep(1)
    else:
        # Send list of virtual guests and exit
        subscriptionManager.sendVirtGuests(virt.listDomains())

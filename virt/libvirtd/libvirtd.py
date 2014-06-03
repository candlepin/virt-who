"""
Module for communcating with libvirt, part of virt-who

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

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

import time
import logging
import libvirt
import threading
from event import virEventLoopPureStart

import virt


eventLoopThread = None


class LibvirtMonitor(threading.Thread):
    """ Singleton class that performs background event monitoring. """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LibvirtMonitor, cls).__new__(cls, *args, **kwargs)
            cls._instance.event = None
            cls._instance.terminate = threading.Event()
            cls._instance.domainIds = []
            cls._instance.definedDomains = []
        return cls._instance

    STATUS_NOT_STARTED, STATUS_RUNNING, STATUS_DISABLED = range(3)

    def _prepare(self):
        self.logger = logging.getLogger("rhsm-app")
        self.running = threading.Event()
        self.status = LibvirtMonitor.STATUS_NOT_STARTED

    def run(self):
        self._prepare()
        while not self.terminate.isSet():
            self._checkChange()
            time.sleep(5)

    def _checkChange(self):
        try:
            virt = libvirt.openReadOnly('')
        except libvirt.libvirtError, e:
            # Show error only once
            if self.status != LibvirtMonitor.STATUS_DISABLED:
                self.logger.debug("Unable to connect to libvirtd, disabling event monitoring")
                self.logger.exception(e)
            self.status = LibvirtMonitor.STATUS_DISABLED
            return

        domainIds = virt.listDomainsID()
        definedDomains = virt.listDefinedDomains()

        changed = domainIds != self.domainIds or definedDomains != self.definedDomains

        self.domainIds = domainIds
        self.definedDomains = definedDomains

        virt.close()

        if changed and self.event is not None and self.status != LibvirtMonitor.STATUS_NOT_STARTED:
            self.event.set()

        if self.status == LibvirtMonitor.STATUS_DISABLED:
            self.logger.debug("Event monitoring resumed")
        self.status = LibvirtMonitor.STATUS_RUNNING

    def set_event(self, event):
        self.event = event

    def stop(self):
        self.terminate.set()


class Libvirtd(virt.DirectVirt):
    """ Class for interacting with libvirt. """
    CONFIG_TYPE = "libvirt"

    def __init__(self, logger, config, registerEvents=True):
        self.changedCallback = None
        self.logger = logger
        self.registerEvents = registerEvents
        libvirt.registerErrorHandler(lambda ctx, error: None, None)

    def _connect(self):
        monitor = LibvirtMonitor()
        try:
            self.virt = libvirt.openReadOnly('')
        except libvirt.libvirtError, e:
            self.logger.exception("Error in libvirt backend")
            raise virt.VirtError(str(e))

    def listDomains(self):
        """ Get list of all domains. """
        domains = []
        self._connect()

        try:
            # Active domains
            for domainID in self.virt.listDomainsID():
                domain = self.virt.lookupByID(domainID)
                if domain.UUIDString() == "00000000-0000-0000-0000-000000000000":
                    # Don't send Domain-0 on xen (zeroed uuid)
                    continue
                domains.append(virt.Domain(self.virt, domain))
                self.logger.debug("Virtual machine found: %s: %s" % (domain.name(), domain.UUIDString()))

            # Non active domains
            for domainName in self.virt.listDefinedDomains():
                domain = self.virt.lookupByName(domainName)
                domains.append(virt.Domain(self.virt, domain))
                self.logger.debug("Virtual machine found: %s: %s" % (domainName, domain.UUIDString()))
        except libvirt.libvirtError, e:
            raise virt.VirtError(str(e))
        return domains

    def canMonitor(self):
        return True

    def startMonitoring(self, event):
        monitor = LibvirtMonitor()
        if not monitor.isAlive():
            monitor.set_event(event)
            monitor.start()


def eventToString(event):
    eventStrings = ("Defined", "Undefined", "Started", "Suspended", "Resumed",
                    "Stopped", "Shutdown")
    try:
        return eventStrings[event]
    except IndexError:
        return "Unknown (%d)" % event


def detailToString(event, detail):
    eventStrings = (
        ("Added", "Updated"), # Defined
        ("Removed", ), # Undefined
        ("Booted", "Migrated", "Restored", "Snapshot", "Wakeup"), # Started
        ("Paused", "Migrated", "IOError", "Watchdog", "Restored", "Snapshot"), # Suspended
        ("Unpaused", "Migrated", "Snapshot"), # Resumed
        ("Shutdown", "Destroyed", "Crashed", "Migrated", "Saved", "Failed", "Snapshot"), # Stopped
        ("Finished",), # Shutdown
    )
    try:
        return eventStrings[event][detail]
    except IndexError:
        return "Unknown (%d)" % detail

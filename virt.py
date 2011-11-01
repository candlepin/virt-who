"""
Module for accessing libvirt, part of virt-who

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

import libvirt

class VirtError(Exception):
    pass

class Virt:
    """ Class for interacting with libvirt. """
    def __init__(self, logger):
        self.changedCallback = None
        self.logger = logger
        self.virt = None
        # Log libvirt errors
        libvirt.registerErrorHandler(lambda ctx, error: None, None) #self.logger.exception(error), None)
        try:
            self.virt = libvirt.openReadOnly("")
        except libvirt.libvirtError, e:
            raise VirtError(str(e))

    def listDomains(self):
        """ Get list of all domains. """
        domains = []

        try:
            # Active domains
            for domainID in self.virt.listDomainsID():
                domain = self.virt.lookupByID(domainID)
                domains.append(domain)
                self.logger.debug("Virtual machine found: %s: %s" % (domain.name(), domain.UUIDString()))

            # Non active domains
            for domainName in self.virt.listDefinedDomains():
                domain = self.virt.lookupByName(domainName)
                domains.append(domain)
                self.logger.debug("Virtual machine found: %s: %s" % (domainName, domain.UUIDString()))
        except libvirt.libvirtError, e:
            raise VirtError(str(e))
        return domains

    def __del__(self):
        if self.virt:
            self.virt.close()

    def changed(self, conn, dom, event, detail, opaque):
        print "EVENT: Domain %s(%s) %s %s" % (dom.name(), dom.ID(), eventToString(event), detailToString(event, detail))
        if self.changedCallback:
            self.changedCallback(self.listDomains())

    def domainListChangedCallback(self, callback):
        self.changedCallback = callback

    def ping(self):
        try:
            self.virt.getVersion()
            return True
        except Exception:
            return False

def eventToString(event):
    eventStrings = ( "Defined",
                     "Undefined",
                     "Started",
                     "Suspended",
                     "Resumed",
                     "Stopped" )
    return eventStrings[event]

def detailToString(event, detail):
    eventStrings = (
        ( "Added", "Updated" ),
        ( "Removed" ),
        ( "Booted", "Migrated", "Restored", "Snapshot" ),
        ( "Paused", "Migrated", "IOError", "Watchdog" ),
        ( "Unpaused", "Migrated"),
        ( "Shutdown", "Destroyed", "Crashed", "Migrated", "Saved", "Failed", "Snapshot")
        )
    return eventStrings[event][detail]

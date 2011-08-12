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

class Virt:
    """ Class for interacting with libvirt. """
    def __init__(self, logger):
        self.logger = logger
        self.virt = libvirt.openReadOnly("")
        # Log libvirt errors
        libvirt.registerErrorHandler(lambda ctx, error: self.logger.debug(error), None)

    def listDomains(self):
        """ Get list of all domains. """
        domains = []

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

        return domains

    def __del__(self):
        self.virt.close()

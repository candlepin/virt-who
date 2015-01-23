"""
Module for abstraction of all virtualization backends, part of virt-who

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


class VirtError(Exception):
    pass


class Domain(dict):
    def __init__(self, virt, domain):
        self['guestId'] = domain.UUIDString()
        self['attributes'] = {
            'hypervisorType': virt.getType(),
            'virtWhoType': "libvirt",
            'active': 0
        }
        if domain.isActive():
            self['attributes']['active'] = 1
        try:
            self['state'] = domain.state(0)[0]
        except AttributeError:
            # Some versions of libvirt doesn't have domain.state() method,
            # use first value from info instead
            self['state'] = domain.info()[0]


class Virt(object):
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config

    @classmethod
    def fromConfig(cls, logger, config):
        """
        Create instance of inherited class based on the config.
        """

        # Imports can't be top-level, it would be circular dependency
        import libvirtd
        import esx
        import rhevm
        import vdsm
        import hyperv

        for subcls in cls.__subclasses__():
            if config.type == subcls.CONFIG_TYPE:
                return subcls(logger, config)
        raise KeyError("Invalid config type: %s" % config.type)

    def canMonitor(self):
        """
        Return true if inherited class can perform background monitoring
        for changes in host/guest association.
        """
        return False

    def startMonitoring(self, event):
        """
        Start the monitoring for changes in host/guest association.

        This should set the 'event' to force resending of host/guest associations.
        """
        raise NotImplementedError()

    def isHypervisor(self):
        """
        Return True if the virt instance represents hypervisor and the guests
        should be obtained by using getHostGuestMapping method. Otherwise
        plain listDomains will be used
        """
        return True

    def listDomains(self):
        raise NotImplementedError()

    def getHostGuestMapping(self, regname):
        raise NotImplementedError()

"""
Abstraction for accessing different subscription managers.

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


class ManagerError(Exception):
    pass

class ManagerFatalError(Exception):
    pass

class Manager(object):
    def sendVirtGuests(self, domains):
        raise NotImplementedError()

    def hypervisorCheckIn(self, config, mapping, type=None):
        raise NotImplementedError()

    @classmethod
    def fromOptions(cls, logger, options, config=None):
        # Imports can't be top-level, it would be circular dependency
        import subscriptionmanager
        import satellite

        # Silence pyflakes errors
        assert subscriptionmanager
        assert satellite

        for subcls in cls.__subclasses__():
            if subcls.smType == config.smType:
                return subcls(logger, options)

        raise KeyError("Invalid config type: %s" % config.smType)

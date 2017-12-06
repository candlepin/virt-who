# -*- coding: utf-8 -*-
from __future__ import print_function
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

from virtwho.config import VW_ENV_CLI_SECTION_NAME


class ManagerError(Exception):
    pass


class ManagerFatalError(Exception):
    pass


class ManagerThrottleError(Exception):
    """
    Exception that is thrown when manager is too busy and want us to
    send reports less often.
    """
    def __init__(self, retry_after=None):
        self.retry_after = retry_after


class Manager(object):
    """
    This class is an abstract representation of an object that, given info
    to be used to connect, can transform reports from virt-who internal format
    to the format necessary for the endpoint. In addition these classes must be
    able to establish and maintain a connection to the given "destination"
    backend.
    """
    def __repr__(self):
        return '{0.__class__.__name__}({0.logger!r}, {0.options!r})'.format(self)

    def sendVirtGuests(self, report, options=None):
        raise NotImplementedError()

    def hypervisorCheckIn(self, report, options=None):
        raise NotImplementedError()

    def check_report_state(self, report):
        """
        Check state of given report. This is used to check server side
        job if finished.
        """
        raise NotImplementedError()

    @classmethod
    def from_config(cls, logger, config):
        """
        Try to get instance of manager from config
        :param logger: Logger used by virt-who
        :param config: instance of ConfigSection or subclass
        :return: instance of manager or subclass
        """
        # Imports can't be top-level, it would be circular dependency
        import virtwho.manager.subscriptionmanager
        import virtwho.manager.satellite
        # Silence pyflakes errors
        assert virtwho

        try:
            sm_type = config['sm_type']
        except KeyError:
            sm_type = 'sam'

        for subcls in cls.__subclasses__():
            if subcls.sm_type == sm_type:
                return subcls(logger, config)

    @classmethod
    def fromOptions(cls, logger, options, config=None):
        # Imports can't be top-level, it would be circular dependency
        import virtwho.manager.subscriptionmanager
        import virtwho.manager.satellite

        # Silence pyflakes errors
        assert virtwho

        config_sm_type = config.sm_type if config else None
        sm_type = config_sm_type or options[VW_ENV_CLI_SECTION_NAME].get('sm_type', None) or 'sam'

        for subcls in cls.__subclasses__():
            if subcls.sm_type == sm_type:
                return subcls(logger, options)

        raise KeyError("Invalid config type: %s" % sm_type)

    @classmethod
    def fromInfo(cls, logger, options, info):
        """
        @param logger: The logging object to pass into the new manager object
        @type logger: logger

        @param options: The options object to create a manager with.

        @param info: The config.Info object to be used to determine which
        manager object to create
        @type info: virtwho.config.Info

        @return: An initialized Manager subclass for the given info object
        @rtype: manager.Manager
        """
        from virtwho.manager.subscriptionmanager import SubscriptionManager
        from virtwho.manager.satellite import Satellite

        from virtwho.config import Satellite6DestinationInfo, \
            Satellite5DestinationInfo, DefaultDestinationInfo

        info_to_manager_map = {
            Satellite5DestinationInfo: Satellite,
            Satellite6DestinationInfo: SubscriptionManager,
            DefaultDestinationInfo: SubscriptionManager,
        }

        return info_to_manager_map[type(info)](logger, options)

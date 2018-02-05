# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import

#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import json

from virtwho.config import VirtConfigSection, accessible_file, str_to_bool
from virtwho.virt import Virt, VirtError, Guest, Hypervisor
from virtwho.util import decode


class FakeVirtConfigSection(VirtConfigSection):
    """
    This class is used for validation of fake virtualization backend
    section(s). It tries to validate options and combination of options that
    are specific for this virtualization backend. In specific, it attempts to read
    the given file and produces error messages if it is not usable.
    """
    VIRT_TYPE = 'fake'

    def __init__(self, *args, **kwargs):
        super(FakeVirtConfigSection, self).__init__(*args, **kwargs)
        self.add_key('is_hypervisor', validation_method=self._validate_str_to_bool, default=True,
                     required=True)
        self.add_key('file', validation_method=self._validate_fake_virt_file, required=True)

    def _validate_fake_virt_file(self, key):
        file_path = self.get(key)
        # Ensure the value we've got is a file we can access
        try:
            accessible_file(file_path)
        except ValueError as e:
            message = "Error validating key '%s': '%s'" % (key, str(e))
            return 'error', message
        # We do not know if the is_hypervisor key will have been parsed yet
        # TODO Allow for specification of which key requires which parsed values
        try:
            is_hypervisor = self.get('is_hypervisor')
            if isinstance(is_hypervisor, str):
                is_hypervisor = str_to_bool(is_hypervisor)
        except ValueError as e:
            message = "Error validating key '%s': '%s'" % (key, str(e))
            return 'error', message
        try:
            if is_hypervisor is True:
                # Try to read and parse the file as if it were a host guest mapping
                FakeVirt.read_host_guest_mapping_from_file(file_path)
            elif is_hypervisor is False:
                # Try to read and parse the file as if it were a domain list
                FakeVirt.list_domains_from_file(file_path)
        except VirtError as e:
            message = "Error validating key '%s': '%s'" % (key, str(e))
            return 'error', message


class FakeVirt(Virt):
    CONFIG_TYPE = 'fake'

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(FakeVirt, self).__init__(logger, config, dest,
                                       terminate_event=terminate_event,
                                       interval=interval,
                                       oneshot=oneshot)
        self.logger = logger
        self.config = config

    @staticmethod
    def _read_data(file_path):
        # TODO: do some checking of the file content
        try:
            with open(file_path, 'r') as f:
                return json.load(f, object_hook=decode)
        except (IOError, ValueError) as e:
            raise VirtError("Can't read fake '%s' virt data: %s" % (file_path, str(e)))

    def isHypervisor(self):
        if self.config["is_hypervisor"] is None:
            return True
        return self.config["is_hypervisor"]

    @classmethod
    def process_guest(cls, guest):
        attributes = guest.get('attributes', {})
        virt_type = attributes.get('virtWhoType', 'fake')
        return Guest(guest['guestId'], virt_type, guest['state'])

    @classmethod
    def process_hypervisor(cls, hypervisor):
        guests = []
        for guest in hypervisor['guests']:
            guests.append(cls.process_guest(guest))
        return Hypervisor(hypervisor['uuid'],
                          guests,
                          hypervisor.get('name'),
                          hypervisor.get('facts'))

    @classmethod
    def read_host_guest_mapping_from_file(cls, file_path):
        # Used to read the host-guest mapping from a file. Raises VirtError if
        # we are unable to parse the file
        assoc = {'hypervisors': []}
        try:
            for hypervisor in cls._read_data(file_path)['hypervisors']:
                assoc['hypervisors'].append(cls.process_hypervisor(hypervisor))
        except KeyError as e:
            raise VirtError("Fake virt file '%s' is not properly formed: %s" % (file_path, str(e)))
        return assoc

    def getHostGuestMapping(self):
        return self.read_host_guest_mapping_from_file(self.config['file'])

    @classmethod
    def list_domains_from_file(cls, file_path):
        hypervisor = cls._read_data(file_path)['hypervisors'][0]
        if 'uuid' in hypervisor:
            raise VirtError("Fake virt file '%s' is not properly formed: "
                            "uuid key shouldn't be present, try to check is_hypervisor value" %
                            file_path)
        guests = []
        for guest in hypervisor['guests']:
            guests.append(cls.process_guest(guest))
        return guests

    def listDomains(self):
        return self.list_domains_from_file(self.config['file'])

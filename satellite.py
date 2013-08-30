"""
Module for communcating with Satellite (RHN Classic), part of virt-who

Copyright (C) 2013 Radek Novacek <rnovacek@redhat.com>

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
import xmlrpclib
import pickle

class SatelliteError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

class Satellite(object):
    """ Class for interacting with satellite (RHN Classic). """
    HYPERVISOR_SYSTEMID_FILE="/var/lib/virt-who/hypervisor-systemid-%s"
    def __init__(self, logger):
        self.logger = logger
        self.server = None

    def connect(self, server, username, password, options=None, force_register=False):
        if not server.startswith("http://") and not server.startswith("https://"):
            server = "https://%s" % server
        if not server.endswith("XMLRPC"):
            server = "%s/XMLRPC" % server

        self.username = username
        self.password = password

        self.logger.debug("Initializing satellite connection to %s" % server)
        try:
            self.server = xmlrpclib.Server(server, verbose=0)
        except Exception:
            self.logger.exception("Unable to connect to the Satellite server")
            raise SatelliteError("Unable to connect to the Satellite server")
        self.logger.info("Initialized satellite connection")

    def _load_hypervisor(self, hypervisor_uuid, type):
        systemid_filename = self.HYPERVISOR_SYSTEMID_FILE % hypervisor_uuid
        # attempt to read the existing systemid file for the hypervisor
        try:
            self.logger.debug("Loading system id info from %s" % systemid_filename)
            new_system = pickle.load(open(systemid_filename, "rb"))
        except IOError:
            # assume file was not found, create a new hypervisor
            try:
                # TODO: what to do here? 6Server will consume subscription
                new_system = self.server.registration.new_system_user_pass("%s hypervisor %s" % (type, hypervisor_uuid),
                        "unknown", "6Server", "x86_64", self.username, self.password, {})
                self.server.registration.refresh_hw_profile(new_system['system_id'], [])
            except Exception, e:
                self.logger.exception("Unable to refresh HW profile")
                raise SatelliteError("Unable to refresh HW profile: %s" % str(e))
            # save the hypervisor systemid
            try:
                f = open(systemid_filename, "w")
                try:
                    pickle.dump(new_system, f)
                finally:
                    f.close()
            except (OSError, IOError), e:
                self.logger.error("Unable to write system id to %s: %s" % (systemid_filename, str(e)))

            self.logger.debug("New system created in satellite, system id saved in %s" % systemid_filename)

        if new_system is None:
            raise SatelliteError("Unable to register hypervisor %s" % hypervisor_uuid)

        return new_system

    def readConfig(self):
        """
        not implemented; config info is passed in via virt-who conf
        """
        pass

    def _assemble_plan(self, hypervisor_mapping, hypervisor_uuid, type):

        # Get rid of dashes from UUID, spacewalk does not like them
        #hypervisor_uuid = (str(hypervisor_uuid).replace("-", ""))
        events = []

        # the stub_instance_info is not used by the report. When the guest system checks in, it will provide
        # actual hardware info
        stub_instance_info = {
            'vcpus' : 1,
            'memory_size' : 0,
            'virt_type' : 'fully_virtualized',
            'state' : 'running',
        }

        # again, remove dashes
        guest_uuids = []
        for g_uuid in hypervisor_mapping:
            guest_uuids.append(str(g_uuid).replace("-", ""))


        # TODO: spacewalk wants all zeroes for the hypervisor uuid??
        events.append([0, 'exists', 'system', {'identity': 'host', 'uuid': '0000000000000000'}])

        events.append([0, 'crawl_began', 'system', {}])
        for guest_uuid in guest_uuids:
            stub_instance_info['uuid'] = guest_uuid
            stub_instance_info['name'] = "VM from %s hypervisor %s" % (type, hypervisor_uuid)
            events.append([0, 'exists', 'domain', stub_instance_info.copy()])

        events.append([0, 'crawl_ended', 'system', {}])

        return events

    def sendVirtGuests(self, domains):
        raise SatelliteError("virt-who does not support sending local hypervisor data to satellite; use rhn-virtualization-host instead")

    def hypervisorCheckIn(self, owner, env, mapping, type=None):

        if len(mapping) == 0:
            self.logger.info("no hypervisors found, not sending data to satellite")

        for hypervisor_uuid, guest_uuids in mapping.items():
            self.logger.debug("Loading systemid for %s" % hypervisor_uuid)
            hypervisor_systemid = self._load_hypervisor(hypervisor_uuid, type=type) 

            self.logger.debug("Building plan for hypervisor %s: %s" % (hypervisor_uuid, guest_uuids))
            plan = self._assemble_plan(guest_uuids, hypervisor_uuid, type=type)

            try:
                self.logger.debug("Sending plan: %s" % plan)
                self.server.registration.virt_notify(hypervisor_systemid["system_id"], plan)
            except Exception, e:
                self.logger.exception("Unable to send host/guest assocaition to the satellite:")
                raise SatelliteError("Unable to send host/guest assocaition to the satellite: % " % str(e))

        # TODO: figure out what to populate here
        result = {}
        for type in ['failedUpdate', 'created', 'updated']:
            result[type] = []

        return result

    def uuid(self):
        """ not implemented """
        return '0000000000000000'

    def getFacts(self):
        """ Not implemented """
        pass

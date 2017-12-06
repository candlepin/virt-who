# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for communication with Satellite (RHN Classic), part of virt-who

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

from six.moves import xmlrpc_client
from six.moves import cPickle as pickle
import json

from virtwho.manager import Manager, ManagerError
from virtwho.util import RequestsXmlrpcTransport
from virtwho.virt import Guest, AbstractVirtReport


class SatelliteError(ManagerError):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


GUEST_STATE_TO_SATELLITE = {
    Guest.STATE_RUNNING: 'running',
    Guest.STATE_BLOCKED: 'blocked',
    Guest.STATE_PAUSED: 'paused',
    Guest.STATE_SHUTINGDOWN: 'shutdown',
    Guest.STATE_SHUTOFF: 'shutoff',
    Guest.STATE_CRASHED: 'crashed',
    Guest.STATE_UNKNOWN: 'nostate'
}


class Satellite(Manager):
    sm_type = "satellite"
    """ Class for interacting with satellite (RHN Classic). """
    HYPERVISOR_SYSTEMID_FILE = "/var/lib/virt-who/hypervisor-systemid-%s"

    def __init__(self, logger, options):
        self.logger = logger
        self.server_xmlrpc = None
        self.server_rpcapi = None
        self.options = options

    def _connect(self, config):
        server = config['sat_server']
        self.username = config['sat_username']
        self.password = config['sat_password']

        if not server.startswith("http://") and not server.startswith("https://"):
            server = "https://%s" % server
        if not server.endswith("XMLRPC"):
            server = "%s/XMLRPC" % server

        try:
            self.force_register = self.options.force_register
        except AttributeError:
            self.force_register = False

        self.logger.debug("Initializing satellite connection to %s", server)
        try:
            # We need two API endpoints: /XMLRPC and /rpc/api
            self.server_xmlrpc = xmlrpc_client.ServerProxy(server, verbose=0, transport=RequestsXmlrpcTransport(server))
            server_api = server.replace('/XMLRPC', '/rpc/api')
            self.server_rpcapi = xmlrpc_client.ServerProxy(server_api, verbose=0, transport=RequestsXmlrpcTransport(server_api))
        except Exception as e:
            self.logger.exception("Unable to connect to the Satellite server")
            raise SatelliteError("Unable to connect to the Satellite server: " % str(e))
        self.logger.debug("Initialized satellite connection")

    def _register_system(self, hypervisor_uuid, hypervisor_type, systemid_filename):
        try:
            session = self.server_rpcapi.auth.login(self.username, self.password)
        except Exception as e:
            self.logger.exception("Unable to login to satellite5 server")
            raise SatelliteError("Unable to login to satellite5 server: %s" % str(e))

        try:
            userdetail = self.server_rpcapi.user.getDetails(session, self.username)
            org_id = userdetail["org_id"]
        except Exception as e:
            self.logger.exception("Unable to get user details")
            raise SatelliteError("Unable to get user details: %s" % str(e))

        base_channel_name = 'hypervisor-base-%s' % org_id
        base_channel_label = 'Hypervisor Base - %s' % org_id

        try:
            hypervisor_base_channel = self.server_rpcapi.channel.software.getDetails(session, base_channel_name)
            self.logger.debug("Using existing hypervisor-base channel")
        except xmlrpc_client.Fault as e:
            if e.faultCode == -210:
                # The channel doesn't exist yet
                hypervisor_base_channel = None
            else:
                self.logger.exception("Unable to find info about hypervisor-base channel")
                raise SatelliteError("Unable to find info about hypervisor-base channel: %s" % str(e))

        if not hypervisor_base_channel:
            self.logger.debug("hypervisor-base channel was not found, creating one")
            # Create the channel
            try:
                result = self.server_rpcapi.channel.software.create(
                    session, base_channel_name, base_channel_label,
                    'Channel used by virt-who for hypervisor registration',
                    'channel-x86_64', '')
            except Exception as e:
                self.logger.exception("Unable to create hypervisor-base channel")
                raise SatelliteError("Unable to create hypervisor-base channel: %s" % str(e))
            if result != 1:
                raise SatelliteError("Unable to create hypervisor-base channel, satellite returned code %s" % result)

            try:
                result = self.server_rpcapi.distchannel.setMapForOrg(session, 'Hypervisor OS', 'unknown', 'x86_64', base_channel_name)
            except Exception as e:
                self.logger.exception("Unable to create mapping for hypervisor-base channel")
                raise SatelliteError("Unable to create mapping for hypervisor-base channel: %s" % str(e))
            if result != 1:
                raise SatelliteError("Unable to create mapping for hypervisor-base channel, satellite returned code %s" % result)

        try:
            new_system = self.server_xmlrpc.registration.new_system_user_pass(
                "%s hypervisor %s" % (hypervisor_type, hypervisor_uuid),
                "Hypervisor OS", "unknown", "x86_64", self.username, self.password, {})
        except Exception as e:
            self.logger.exception("Unable to register system:")
            raise SatelliteError("Unable to register system: %s" % str(e))

        try:
            self.server_xmlrpc.registration.refresh_hw_profile(new_system['system_id'], [])
        except Exception as e:
            self.logger.exception("Unable to refresh HW profile:")
            raise SatelliteError("Unable to refresh HW profile: %s" % str(e))
        # save the hypervisor systemid
        try:
            with open(systemid_filename, "wb") as f:
                pickle.dump(new_system, f)
        except (OSError, IOError) as e:
            self.logger.exception("Unable to write system id to %s: %s", systemid_filename, str(e))

        self.logger.debug("New system created in satellite, system id saved in %s", systemid_filename)
        return new_system

    def _load_hypervisor(self, hypervisor_uuid, hypervisor_type, force=False):
        systemid_filename = self.HYPERVISOR_SYSTEMID_FILE % hypervisor_uuid
        # attempt to read the existing systemid file for the hypervisor
        try:
            if force or self.force_register:
                raise IOError()
            self.logger.debug("Loading system id info from %s", systemid_filename)
            new_system = pickle.load(open(systemid_filename, "rb"))
        except IOError:
            # assume file was not found, create a new hypervisor
            new_system = self._register_system(hypervisor_uuid, hypervisor_type, systemid_filename)

        if new_system is None:
            raise SatelliteError("Unable to register hypervisor %s" % hypervisor_uuid)

        return new_system

    def readConfig(self):
        """
        not implemented; config info is passed in via virt-who conf
        """
        pass

    def _assemble_plan(self, guests, hypervisor_uuid, hypervisor_type):

        events = []

        # the stub_instance_info is not used by the report. When the guest system checks in, it will provide
        # actual hardware info
        stub_instance_info = {
            'vcpus': 1,
            'memory_size': 0,
            'virt_type': 'fully_virtualized'
        }

        # TODO: spacewalk wants all zeroes for the hypervisor uuid??
        events.append([0, 'exists', 'system', {'identity': 'host', 'uuid': '0000000000000000'}])

        events.append([0, 'crawl_began', 'system', {}])
        for guest in guests:
            stub_instance_info['uuid'] = guest.uuid.replace("-", "")
            stub_instance_info['name'] = "VM %s from %s hypervisor %s" % (guest.uuid, hypervisor_type, hypervisor_uuid)
            stub_instance_info['state'] = GUEST_STATE_TO_SATELLITE.get(guest.state, "nostate")
            events.append([0, 'exists', 'domain', stub_instance_info.copy()])

        events.append([0, 'crawl_ended', 'system', {}])

        return events

    def sendVirtGuests(self, report, options=None):
        raise SatelliteError("virt-who does not support sending local hypervisor "
                             "data to satellite; use rhn-virtualization-host instead")

    def hypervisorCheckIn(self, report, options=None):
        mapping = report.association
        self._connect(report.config)

        hypervisor_count = len(mapping['hypervisors'])
        guest_count = sum(len(hypervisor.guestIds) for hypervisor in mapping['hypervisors'])
        self.logger.info("Sending update in hosts-to-guests mapping: %d hypervisors and %d guests found", hypervisor_count, guest_count)
        serialized_mapping = {'hypervisors': [h.toDict() for h in mapping['hypervisors']]}
        self.logger.debug("Host-to-guest mapping: %s", json.dumps(serialized_mapping, indent=4))
        if len(mapping) == 0:
            self.logger.info("no hypervisors found, not sending data to satellite")

        for hypervisor in mapping['hypervisors']:
            self.logger.debug("Loading systemid for %s", hypervisor.hypervisorId)
            hypervisor_systemid = self._load_hypervisor(hypervisor.hypervisorId,
                                                        hypervisor_type=report.config['type'])

            self.logger.debug("Building plan for hypervisor %s: %s", hypervisor.hypervisorId, hypervisor.guestIds)
            plan = self._assemble_plan(hypervisor.guestIds, hypervisor.hypervisorId,
                                       hypervisor_type=report.config['type'])

            try:
                try:
                    self.logger.debug("Sending plan: %s", plan)
                    self.server_xmlrpc.registration.virt_notify(hypervisor_systemid["system_id"], plan)
                except xmlrpc_client.Fault as e:
                    if e.faultCode == -9:
                        self.logger.warn("System was deleted from Satellite 5, reregistering")
                        hypervisor_systemid = self._load_hypervisor(hypervisor.hypervisorId,
                                                                    hypervisor_type=report.config['type'], force=True)
                        self.server_xmlrpc.registration.virt_notify(hypervisor_systemid["system_id"], plan)
            except Exception as e:
                self.logger.exception("Unable to send host/guest association to the satellite:")
                raise SatelliteError("Unable to send host/guest association to the satellite: %s" % str(e))

        self.logger.info("Mapping for config \"%s\" updated", report.config.name)
        report.state = AbstractVirtReport.STATE_FINISHED

        # TODO: figure out what to populate here
        result = {}
        for type in ['failedUpdate', 'created', 'updated']:
            result[type] = []

        return result

    def uuid(self):
        """ not implemented """
        return '0000000000000000'

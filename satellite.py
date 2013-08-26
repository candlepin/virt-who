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
    VAR_DIR = "/var/lib/virt-who/"
    HYPERVISOR_SYSTEMID_FILE = VAR_DIR + "hypervisor-systemid"
    def __init__(self, logger):
        self.logger = logger
        self.server = None

    def connect(self, server, username, password, options=None, force_register=False):
        # initialize a new system if one doesn't already exist
        if not server.startswith("http://") and not server.startswith("https://"):
            server = "https://%s" % server
        if not server.endswith("XMLRPC"):
            server = "%s/XMLRPC" % server

        self.logger.debug("Initializing satellite connection to %s" % server)
        try:
            self.server = xmlrpclib.Server(server, verbose=0)
        except Exception:
            self.logger.exception("Unable to connect to the Satellite server")
            raise SatelliteError("Unable to connect to the Satellite server")
        self.logger.info("Initialized satellite connection")

        # initialize a new system if one doesn't already exist
        if force_register:
            new_system = self._register_hypervisor(username, password, options)
        else:
            try:
                self.logger.debug("Loading system id info from %s" % self.HYPERVISOR_SYSTEMID_FILE)
                new_system = pickle.load(open(self.HYPERVISOR_SYSTEMID_FILE, "rb"))
            except IOError:
                new_system = self._register_hypervisor(username, password, options)

        if new_system is None:
            raise SatelliteError("Unable to register hypervisor")

        self.systemid = new_system["system_id"]

    def _register_hypervisor(self, username, password, options):
        if options is None:
            # We need to emulate options object from argparse
            class O(object): pass
            options = O()
        # Fill in some defaults
        if not hasattr(options, "profile_name") or options.profile_name is None:
            options.profile_name = "hypervisor"
        if not hasattr(options, "os_release_name") or options.os_release_name is None:
            options.os_release_name = "unknown"
        if not hasattr(options, "version") or options.version is None:
            # TODO: what to do here? 6Server will consume subscription
            options.version = "6Server"
        if not hasattr(options, "arch") or options.arch is None:
            options.arch = "x86_64"

        try:
            new_system = self.server.registration.new_system_user_pass(options.profile_name,
                    options.os_release_name, options.version, options.arch, username, password, {})
            self.server.registration.refresh_hw_profile(new_system['system_id'], [])
        except Exception, e:
            self.logger.exception("Unable to refresh HW profile")
            raise SatelliteError("Unable to refresh HW profile: %s" % str(e))
        try:
            if not os.path.isdir(self.VAR_DIR):
                os.mkdir(self.VAR_DIR, 0600)
            f = open(self.HYPERVISOR_SYSTEMID_FILE, "w")
            try:
                pickle.dump(new_system, f)
            finally:
                f.close()
        except (OSError, IOError), e:
            self.logger.error("Unable to write system id to %s: %s" % (self.HYPERVISOR_SYSTEMID_FILE, str(e)))

        self.logger.debug("New system created in satellite, system id saved in %s" % self.HYPERVISOR_SYSTEMID_FILE)

        return new_system

    def readConfig(self):
        """
        not implemented; config info is passed in via virt-who conf
        """
        pass

    def _assemble_plan(self, uuids):

        events = []

        # the stub_instance_info is not used by the report. When the guest system checks in, it will provide
        # actual hardware info
        stub_instance_info = {
            'vcpus' : 1,
            'memory_size' : 0,
            'virt_type' : 'fully_virtualized',
            'state' : 'running',
            # TODO: put hypervisor's hostname here maybe
            'name': "virtual machine from %s" % 'vmware hypervisor'
        }

        # declare the hypervisor. always use 16 zeros for the hypervisor's UUID, per rhn-virtualization-host
        events.append([0, 'exists', 'system', {'identity': 'host', 'uuid': self.uuid()}])

        events.append([0, 'crawl_began', 'system', {}])
        for uuid in uuids:
            stub_instance_info['uuid'] = uuid
            events.append([0, 'exists', 'domain', stub_instance_info.copy()])
        events.append([0, 'crawl_ended', 'system', {}])

        return events

    def sendVirtGuests(self, domains):
        raise SatelliteError("virt-who does not support sending local hypervisor data to satellite; use rhn-virtualization-host instead")

    def hypervisorCheckIn(self, owner, env, mapping):
        self.logger.debug("Building plan for mapping: %s" % mapping)
        if self.server is None:
            return
        uuids = []
        for guestlist in mapping.values():
            for uuid in guestlist:
                # Get rid of dashes from UUID
                uuids.append(str(uuid).replace("-", ""))
        uuids.sort()

        self.logger.debug("Sending flattened list of uuids: %s" % uuids)

        plan = self._assemble_plan(uuids)
        self.logger.debug("Sending plan: %s" % plan)
        # Send the mapping
        try:
            res = self.server.registration.virt_notify(self.systemid, plan)
        except Exception, e:
            self.logger.exception("Unable to send host/guest assocaition to the satellite:")
            raise SatelliteError("Unable to send host/guest assocaition to the satellite: % " % str(e))

        # TODO: figure out what to populate here
        result = {}
        for type in ['failedUpdate', 'created', 'updated']:
            result[type] = []

        return result

    def uuid(self):
        """ Satellite expects a zeroed-out hypervisor UUID """
        return '0000000000000000'

    def getFacts(self):
        """ Not implemented """
        pass

if __name__ == '__main__':
    from optparse import OptionParser
    import logging
    parser = OptionParser(usage="virt-who-register-satellite [-n name] [-o operating_system] [-v version] [-a arch] server username password",
                          description="Register hypervisor to the satellite server")
    parser.add_option("-n", "--name", action="store", dest="profile_name", default=None, help="Name of the hypervisor")
    parser.add_option("-o", "--operating-system", action="store", dest="os_release_name", default=None, help="Operating system of the hypervisor")
    parser.add_option("-v", "--version", action="store", dest="version", default=None, help="Operating system version")
    parser.add_option("-a", "--arch", action="store", dest="arch", default=None, help="Hypervisor architecture")
    (options, args) = parser.parse_args()
    if len(args) < 3:
        parser.print_usage()
        sys.exit(1)

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    satellite = Satellite(logger)
    try:
        satellite.connect(args[0], args[1], args[2], force_register=True, options=options)
    except Exception:
        logger.exception("Unable to connect to Satellite:")

#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

import socket
import time

from .ahv_interface import AhvInterface2, AhvInterface3

from virtwho import virt
from virtwho.config import VirtConfigSection
from virtwho.virt import Hypervisor, Guest

DefaultUpdateInterval = 1800
MinimumUpdateInterval = 60
DefaultWaitTime = 900
MinWaitTime = 60


class Ahv(virt.Virt):
    """
    AHV Rest client
    """

    CONFIG_TYPE = "ahv"

    SERVER_BASE_URIL = 'https://%s:%d/api/nutanix/%s'

    DEFAULT_PORT = 9440

    def __init__(self, logger, config, dest, interval=None,
                 terminate_event=None, oneshot=False, status=False):
        """
        Args:
            logger (Logger): Framework logger.
            config (onfigSection): virt-who configuration.
            dest (Datastore): Data store for destination.
            interval (Int): Wait interval for continuous run.
            terminate_event (Event): Event on termination.
            oneshot (bool): Flag to run virt-who as onetime or continuously.
        Returns:
            None.
        """
        super(Ahv, self).__init__(
            logger,
            config,
            dest,
            terminate_event=terminate_event,
            interval=interval,
            oneshot=oneshot,
            status=status
        )
        self.config = config
        self.version = AhvInterface2.VERSION

        if 'prism_central' in self.config:
            # FIXME: should we really allow to have there any value, shouldn't we check true/false?
            if self.config['prism_central']:
                self.version = AhvInterface3.VERSION

        self.port = self.DEFAULT_PORT
        self.url = self.SERVER_BASE_URIL % (self.config['server'], self.port, self.version)
        self.username = self.config['username']
        self.password = self.config['password']
        if self.version == AhvInterface2.VERSION:
            self._interface = AhvInterface2(
                logger,
                self.url,
                self.username,
                self.password,
                self.port,
                ahv_internal_debug=self.config['ahv_internal_debug']
            )
        elif self.version == AhvInterface3.VERSION:
            self._interface = AhvInterface3(
                logger,
                self.url,
                self.username,
                self.password,
                self.port,
                ahv_internal_debug=self.config['ahv_internal_debug']
            )
        else:
            raise ValueError("Unsupported version of REST API")

    def get_host_guest_mapping_v3(self):
        """
        Get a dict of host to uvm mapping.
        Returns:
            Dictionary with host-guest mapping
        """
        mapping = {'hypervisors': []}
        hypervisor_id = None

        host_uvm_map = self._interface.build_host_to_uvm_map()

        cluster_uuid_name_list = self._interface.get_ahv_cluster_uuid_name_list()

        for host_uuid in host_uvm_map:
            host = host_uvm_map[host_uuid]

            try:
                if self.config['hypervisor_id'] == 'uuid':
                    hypervisor_id = host_uuid
                elif self.config['hypervisor_id'] == 'hostname':
                    hypervisor_id = host['name']

            except KeyError:
                self.logger.debug("Host '%s' doesn't have hypervisor_id property", host_uuid)
                continue

            guests = []
            if 'guest_list' in host and len(host['guest_list']) > 0:
                for guest_vm in host['guest_list']:
                    vm_uuid = None
                    try:
                        if guest_vm["status"]["resources"]["power_state"] == 'ON':
                            state = virt.Guest.STATE_RUNNING
                        elif guest_vm["status"]["resources"]["power_state"] == 'OFF':
                            state = virt.Guest.STATE_SHUTOFF
                        else:
                            state = virt.Guest.STATE_UNKNOWN
                        vm_uuid = guest_vm["metadata"]["uuid"]
                    except KeyError:
                        self.logger.warning(
                            f"Guest {vm_uuid} is missing power state. Perhaps they"
                            " are powered off",
                        )
                        continue
                    guests.append(Guest(vm_uuid, self.CONFIG_TYPE, state))
            else:
                self.logger.debug("Host '%s' doesn't have any vms", host_uuid)

            cluster_name = self._interface.get_host_cluster_name(host, cluster_uuid_name_list)
            host_version = self._interface.get_host_version(host)
            host_name = host["status"]['name']

            facts = {
                Hypervisor.CPU_SOCKET_FACT: str(host["status"]["resources"]['num_cpu_sockets']),
                Hypervisor.HYPERVISOR_TYPE_FACT: "AHV",
                Hypervisor.HYPERVISOR_VERSION_FACT: str(host_version),
                Hypervisor.SYSTEM_UUID_FACT: str(host_uuid)}
            if cluster_name:
                facts[Hypervisor.HYPERVISOR_CLUSTER] = str(cluster_name)

            if hypervisor_id:
                mapping['hypervisors'].append(virt.Hypervisor(
                    hypervisorId=hypervisor_id,
                    guestIds=guests,
                    name=host_name,
                    facts=facts
                ))
        return mapping

    def get_host_guest_mapping_v2(self):
        """
        Get a dict of host to uvm mapping.
        Args:
            None.
        Returns:
            None.
        """

        mapping = {'hypervisors': []}
        hypervisor_id = None

        host_uvm_map = self._interface.build_host_to_uvm_map()

        cluster_uuid_name_list = self._interface.get_ahv_cluster_uuid_name_list()

        for host_uuid in host_uvm_map:
            host = host_uvm_map[host_uuid]

            try:
                if self.config['hypervisor_id'] == 'uuid':
                    hypervisor_id = host_uuid
                elif self.config['hypervisor_id'] == 'hostname':
                    hypervisor_id = host['name']

            except KeyError:
                self.logger.debug("Host '%s' doesn't have hypervisor_id property", host_uuid)
                continue

            guests = []
            if 'guest_list' in host and len(host['guest_list']) > 0:
                for guest_vm in host['guest_list']:
                    try:
                        if guest_vm['power_state'] == 'on':
                            state = virt.Guest.STATE_RUNNING
                        elif guest_vm['power_state'] == 'off':
                            state = virt.Guest.STATE_SHUTOFF
                        else:
                            state = virt.Guest.STATE_UNKNOWN
                    except KeyError:
                        self.logger.warning(
                            "Guest %s is missing power state. Perhaps they"
                            " are powered off", guest_vm['uuid']
                        )
                        continue
                    guests.append(Guest(guest_vm['uuid'], self.CONFIG_TYPE, state))
            else:
                self.logger.debug("Host '%s' doesn't have any vms", host_uuid)

            cluster_name = self._interface.get_host_cluster_name(host, cluster_uuid_name_list)
            host_version = self._interface.get_host_version(host)
            host_name = host['name']

            facts = {
                Hypervisor.CPU_SOCKET_FACT: str(host['num_cpu_sockets']),
                Hypervisor.HYPERVISOR_TYPE_FACT: host.get('hypervisor_type', 'AHV'),
                Hypervisor.HYPERVISOR_VERSION_FACT: str(host_version),
                Hypervisor.SYSTEM_UUID_FACT: str(host_uuid)}
            if cluster_name:
                facts[Hypervisor.HYPERVISOR_CLUSTER] = str(cluster_name)

            if hypervisor_id:
                mapping['hypervisors'].append(virt.Hypervisor(
                    hypervisorId=hypervisor_id,
                    guestIds=guests,
                    name=host_name,
                    facts=facts
                ))
        return mapping

    def getHostGuestMapping(self):
        """
        Get a dict of host to uvm mapping.
        Args:
            None.
        Returns:
            None.
        """
        if self.version == AhvInterface3.VERSION:
            return self.get_host_guest_mapping_v3()
        elif self.version == AhvInterface2.VERSION:
            return self.get_host_guest_mapping_v2()

    def _run(self):
        """
        Continuous run loop for virt-who on AHV.
        Args:
            None.
        Returns:
            None.
        """
        self.next_update = None
        initial = True
        while not self.is_terminated():

            if initial:
                if self.status:
                    report = virt.StatusReport(self.config)
                    self._send_data(data_to_send=report)
                else:
                    assoc = self.getHostGuestMapping()
                    self._send_data(data_to_send=virt.HostGuestAssociationReport(self.config, assoc))
                initial = False
                self.next_update = time.time() + self.interval

            if self._oneshot:
                break

            time.sleep(1)
            if time.time() > self.next_update:
                report = virt.StatusReport(self.config)
                self._send_data(data_to_send=report)
                self.next_update = time.time() + self.interval


class AhvConfigSection(VirtConfigSection):
    """
    Class for initializing and processing AHV config
    """

    VIRT_TYPE = 'ahv'
    HYPERVISOR_ID = ('uuid', 'hostname')

    def __init__(self, *args, **kwargs):
        """
        Initialize AHV config and add config keys.
        Args:
            args: args
            kwargs : kwargs
         Returns:
            None.
        """
        super(AhvConfigSection, self).__init__(*args, **kwargs)
        self.add_key(
            'server',
            validation_method=self._validate_server,
            required=True
        )
        self.add_key(
            'username',
            validation_method=self._validate_username,
            required=True
        )
        self.add_key(
            'password',
            validation_method=self._validate_unencrypted_password,
            required=True
        )
        self.add_key(
            'is_hypervisor',
            validation_method=self._validate_str_to_bool,
            default=True
        )
        self.add_key(
            'prism_central',
            validation_method=self._validate_str_to_bool,
            default=False
        )
        self.add_key(
            'ahv_internal_debug',
            validation_method=self._validate_str_to_bool,
            default=False
        )

    def _validate_server(self, key):
        """
        Validate the server IP address.
        Args:
            key (Str): server Ip address.
        Returns:
            Socket error is returned in case of an invalid ip.
        """
        error = super(AhvConfigSection, self)._validate_server(key)
        if error is None:
            try:
                ip = self._values[key]
                socket.inet_aton(ip)
            except socket.error:
                error = (
                   'error',
                   'Invalid server IP address provided'
                    )

        return error

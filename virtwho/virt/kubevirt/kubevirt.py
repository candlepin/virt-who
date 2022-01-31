#
# Copyright 2019 Red Hat, Inc.
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
from __future__ import absolute_import

import math
import os
import os.path

from virtwho import virt
from virtwho.config import VirtConfigSection, str_to_bool
from virtwho.virt.kubevirt.client import KubeClient


class KubevirtConfigSection(VirtConfigSection):

    VIRT_TYPE = 'kubevirt'
    HYPERVISOR_ID = ('uuid', 'hostname')

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(KubevirtConfigSection, self).__init__(section_name,
                                                    wrapper,
                                                    *args,
                                                    **kwargs)
        self.add_key('kubeconfig',
                     validation_method=self._validate_path,
                     default=os.environ.get('KUBECONFIG', '~/.kube/config'),
                     required=False)
        self.add_key('kubeversion',
                     validation_method=self._validate_version,
                     default="",
                     required=False)
        self.add_key('insecure',
                     validation_method=self._validate_str_to_bool,
                     default=False,
                     required=False)

    def _validate_path(self, key='kubeconfig'):
        """
        Do validation of kubernetes config file location
        return: Return None or info/warning/error
        """
        path = self._values[key]
        if not os.path.isfile(path):
            return [(
                'warning',
                "Kubeconfig file was not found at %s" % path
            )]
        return None

    def _validate_version(self, key):
        result = None
        try:
            value = self._values[key]
        except KeyError:
            if not self.has_default(key):
                result = ('warning', 'Value for %s not set' % key)
        else:
            if not isinstance(value, str):
                result = ('warning', '%s is not set to a valid string, using default' % key)
            elif len(value) == 0:
                result = ('warning', '%s cannot be empty, using default' % key)
        return result


class Kubevirt(virt.Virt):

    CONFIG_TYPE = "kubevirt"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False, status=False):
        super(Kubevirt, self).__init__(logger, config, dest,
                                       terminate_event=terminate_event,
                                       interval=interval,
                                       oneshot=oneshot,
                                       status=status)
        self._path = self.config['kubeconfig']
        self._version = self.config['kubeversion']
        self._insecure = str_to_bool(self.config['insecure'])

    def prepare(self):
        self._client = KubeClient(self._path, self._version, self._insecure)

    def parse_cpu(self, cpu):
        if cpu.endswith('m'):
            cpu = int(math.floor(int(cpu[:-1]) / 1000))
        return str(cpu)

    def getHostGuestMapping(self):
        """
        Returns dictionary containing a list of virt.Hypervisors
        Each virt.Hypervisor contains the hypervisor ID as well as a list of
        virt.Guest

        {'hypervisors': [Hypervisor1, ...]
        }
        """
        hosts = {}

        nodes = self._client.get_nodes()
        vms = self._client.get_vms()

        for node in nodes['items']:
            status = node['status']
            version = status['nodeInfo']['kubeletVersion']
            name = node['metadata']['name']

            uuid = status['nodeInfo']['machineID']
            if self.config['hypervisor_id'] == 'uuid':
                host_id = uuid
            elif self.config['hypervisor_id'] == 'hostname':
                # set to uuid if hostname not available
                host_id = uuid
                for addr in status['addresses']:
                    if addr['type'] == 'Hostname':
                        host_id = addr['address']

            facts = {
                virt.Hypervisor.CPU_SOCKET_FACT: self.parse_cpu(status['allocatable']["cpu"]),
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                # this should be hardware uniqe identifier but k8s api gives us only machineID
                virt.Hypervisor.SYSTEM_UUID_FACT: status['nodeInfo']['machineID'],
                virt.Hypervisor.HYPERVISOR_VERSION_FACT: version
            }
            hosts[name] = virt.Hypervisor(hypervisorId=host_id, name=name, facts=facts)

        for vm in vms['items']:
            spec = vm['spec']
            host_name = vm['status'].get('nodeName')

            # a vm is not scheduled on any hosts
            if host_name is None:
                continue

            guest_id = spec['domain']['firmware']['uuid']
            # a vm is always in running state
            status = virt.Guest.STATE_RUNNING
            hosts[host_name].guestIds.append(virt.Guest(guest_id, self.CONFIG_TYPE, status))

        return {'hypervisors': list(hosts.values())}

    def statusConfirmConnection(self):
        '''
        This single call will confirm the credentials. The result outside
        of that is not important in the status scenario.
        '''
        try:
            self._client.get_nodes()
        finally:
            if 'server' not in self.config:
                self.config['server'] = self._client.host

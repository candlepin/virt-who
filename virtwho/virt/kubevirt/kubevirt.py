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

import os.path

from virtwho import virt
from virtwho.config import VirtConfigSection
from virtwho.virt.kubevirt.client import KubeClient


class KubevirtConfigSection(VirtConfigSection):

    VIRT_TYPE = 'kubevirt'

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(KubevirtConfigSection, self).__init__(section_name,
                                                    wrapper,
                                                    *args,
                                                    **kwargs)
        self.add_key('kubeconfig', validation_method=self._validate_path, required=True)

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


class Kubevirt(virt.Virt):

    CONFIG_TYPE = "kubevirt"

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(Kubevirt, self).__init__(logger, config, dest,
                                       terminate_event=terminate_event,
                                       interval=interval,
                                       oneshot=oneshot)
        self._path = self.config['kubeconfig']

    def prepare(self):
        self._client = KubeClient(self._path)

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
            host_id = status['nodeInfo']['machineID']
            address = status['addresses'][0]['address']
            facts = {
                virt.Hypervisor.CPU_SOCKET_FACT: status['allocatable']["cpu"],
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                virt.Hypervisor.HYPERVISOR_VERSION_FACT: version
            }
            hosts[name] = virt.Hypervisor(hypervisorId=host_id, name=address, facts=facts)

        for vm in vms['items']:
            metadata = vm['metadata']
            host_name = vm['status']['nodeName']

            # a vm is not scheduled on any hosts
            if host_name is None:
                continue

            guest_id = metadata['namespace'] + '/' + metadata['name']
            # a vm is always in running state
            status = virt.Guest.STATE_RUNNING
            hosts[host_name].guestIds.append(virt.Guest(guest_id, self.CONFIG_TYPE, status))

        return {'hypervisors': list(hosts.values())}

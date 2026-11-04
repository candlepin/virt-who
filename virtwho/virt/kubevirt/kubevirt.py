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

import os
import os.path

from virtwho import virt
from virtwho.config import VirtConfigSection
from virtwho.virt.kubevirt.client import ApiException, KubeClient


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
                 interval=None, oneshot=False):
        super(Kubevirt, self).__init__(logger, config, dest,
                                       terminate_event=terminate_event,
                                       interval=interval,
                                       oneshot=oneshot)
        self._path = self.config['kubeconfig']
        self._version = self.config['kubeversion']

    def prepare(self):
        self._client = KubeClient(self._path, self._version)

    def get_node_cpu_sockets(self, node_name):
        """
        Get the physical CPU socket count of a node from the cAdvisor
        metrics exposed through the node proxy.

        The nodes API only provides the logical CPU count, so the
        machine_cpu_sockets metric is the only source of the physical
        socket count. Returns the socket count as a string, or None when
        the metric is not available (e.g. on older clusters or when the
        node proxy call is not permitted); in that case the
        cpu.cpu_socket(s) fact is omitted instead of reporting the
        logical CPU count as sockets.
        """
        try:
            metrics = self._client.get_node_metrics(node_name)
        except ApiException as e:
            self.logger.warning(
                "Unable to get cAdvisor metrics of node %s (%s), "
                "the cpu.cpu_socket(s) fact will be omitted for this "
                "node" % (node_name, e.status)
            )
            return None

        # metrics is the raw Prometheus output, and will look something like:
        #
        # machine_cpu_cores{boot_id="...",machine_id="...",system_uuid="..."} 8
        # machine_cpu_physical_cores{boot_id="...",machine_id="...",system_uuid="..."} 1
        # machine_cpu_sockets{boot_id="...",machine_id="...",system_uuid="..."} 8
        # machine_memory_bytes{boot_id="...",machine_id="...",system_uuid="..."} 1.6758284288e+10
        # machine_nvm_avg_power_budget_watts{boot_id="...",machine_id="...",system_uuid="..."} 0
        # machine_nvm_capacity{boot_id="...",machine_id="...",mode="app_direct_mode",system_uuid="..."} 0
        # machine_nvm_capacity{boot_id="...",machine_id="...",mode="memory_mode",system_uuid="..."} 0
        # machine_scrape_error 0
        # machine_swap_bytes{boot_id="...",machine_id="...",system_uuid="..."} 0
        for line in metrics.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].split('{')[0] == 'machine_cpu_sockets':
                try:
                    # This value is technically a float according to the Prometheus format,
                    # hence this parsing method
                    sockets = str(int(float(parts[1])))
                except (ValueError, OverflowError):
                    self.logger.warning(
                        "Unable to parse the machine_cpu_sockets metric of "
                        "node %s (unexpected value '%s'), the "
                        "cpu.cpu_socket(s) fact will be omitted for this "
                        "node" % (node_name, parts[1])
                    )
                    return None
                self.logger.debug(
                    "Node %s reports %s physical CPU socket(s)"
                    % (node_name, parts[1])
                )
                return sockets

        self.logger.warning(
            "The machine_cpu_sockets metric was not found in the cAdvisor "
            "metrics of node %s, the cpu.cpu_socket(s) fact will be "
            "omitted for this node" % node_name
        )
        return None

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
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                # this should be hardware uniqe identifier but k8s api gives us only machineID
                virt.Hypervisor.SYSTEM_UUID_FACT: status['nodeInfo']['machineID'],
                virt.Hypervisor.HYPERVISOR_VERSION_FACT: version
            }
            # The nodes API exposes only the logical CPU count, which
            # must not be reported as physical sockets. Read the socket
            # count from the node's cAdvisor metrics instead and omit
            # the fact when the metric is not available.
            sockets = self.get_node_cpu_sockets(name)
            if sockets is not None:
                facts[virt.Hypervisor.CPU_SOCKET_FACT] = sockets
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

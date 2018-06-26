from __future__ import print_function
#
# Copyright 2018 Red Hat, Inc.
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
from mock import patch, Mock

from base import TestBase

from virtwho.virt import Virt, Guest, Hypervisor
from virtwho.virt.kubevirt.kubevirt import KubevirtConfigSection
from virtwho.datastore import Datastore


class TestKubevirt(TestBase):

    @staticmethod
    def create_config(name, wrapper, **kwargs):
        config = KubevirtConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self):
        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', env='env')
        with patch.dict('os.environ', {'KUBECONFIG':'/dev/null'}):
            self.kubevirt = Virt.from_config(self.logger, config, Datastore())

    def nodes(self):
        metadata = Mock()
        metadata.name = "master"

        node_info = Mock()
        node_info.machine_id = "52c01ad890e84b15a1be4be18bd64ecd"
        node_info.kubelet_version = "v1.9.1+a0ce1bc657"

        address = Mock()
        address.address = "master"

        status = Mock()
        status.node_info = node_info
        status.addresses = [address]
        status.allocatable = {"cpu": "2"}

        node = Mock()
        node.metadata = metadata
        node.status = status

        nodes = Mock()
        nodes.items = [node]

        return nodes

    def vms(self):
        metadata = Mock()
        metadata.name = "win-2016"
        metadata.namespace = "default"

        status = Mock()
        status.node_name = "master"

        vm = Mock()
        vm.metadata = metadata
        vm.status = status

        vms = Mock()
        vms.items = [vm]

        return vms

    def test_getHostGuestMapping(self):
        kube_api = Mock()
        kube_api.list_node.return_value = self.nodes()

        kubevirt_api = Mock()
        kubevirt_api.list_virtual_machine_instance_for_all_namespaces.return_value = self.vms()

        self.kubevirt.kube_api = kube_api
        self.kubevirt.kubevirt_api = kubevirt_api

        expected_result = Hypervisor(
            hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
            name='master',
            guestIds=[
                Guest(
                    'default/win-2016',
                    self.kubevirt.CONFIG_TYPE,
                    Guest.STATE_RUNNING,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '2',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
            }
        )
        result = self.kubevirt.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

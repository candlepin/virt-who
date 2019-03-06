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
                                    owner='owner', env='env', kubeconfig='/etc/hosts')
        with patch.dict('os.environ', {'KUBECONFIG':'/dev/null'}):
            self.kubevirt = Virt.from_config(self.logger, config, Datastore())

    def nodes(self):
        node = {
            'metadata': {
                'name': 'master'
            },
            'status': {
                'nodeInfo': {
                    'machineID': '52c01ad890e84b15a1be4be18bd64ecd',
                    'kubeletVersion': 'v1.9.1+a0ce1bc657'
                },
                'addresses': [
                    {'address': 'master'}
                ],
                'allocatable' : {
                    'cpu': '2'
                }
            }
        }

        return {'items': [node]}

    def vms(self):
        vm = {
            'metadata': {
                'name': 'win-2016',
                'namespace': 'default',
            },
            'status': {
                'nodeName': 'master',
            }
        }

        return {'items': [vm]}

    def test_getHostGuestMapping(self):
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.vms()

        self.kubevirt._client = client

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

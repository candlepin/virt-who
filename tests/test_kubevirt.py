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
                    {'address': '192.168.122.140',
                     'type': 'InternalIP'},
                    {'address': 'minikube',
                     'type': 'Hostname'}
                ],
                'allocatable' : {
                    'cpu': '2'
                }
            }
        }

        return {'items': [node]}

    def new_nodes(self):
        node = {
            'metadata': {
                'name': 'master'
            },
            'status': {
                'nodeInfo': {
                    'machineID': '52c01ad890e84b15a1be4be18bd64ecd',
                    'kubeletVersion': 'v1.18.0-rc.1'
                },
                'addresses': [
                    {'address': '192.168.122.140',
                     'type': 'InternalIP'},
                    {'address': 'minikube',
                     'type': 'Hostname'}
                ],
                'allocatable' : {
                    'cpu': '7500m'
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
            'spec': {
                'domain': {
                    'devices': {
                        'disks': [
                            {'disk': {'bus': 'virtio'}, 'name': 'containerdisk'}
                        ],
                        'interfaces': [
                            {'bridge': {}, 'name': 'default'}
                        ],
                    },
                    'features': {
                        'acpi': {
                            'enabled': 'true'
                        }
                    },
                    'firmware': {
                        'uuid': 'f83c5f73-5244-4bd1-90cf-02bac2dda608'
                    },
                    'machine': {
                        'type': 'q35'
                    }
                }
            },
            'status': {
                'nodeName': 'master',
                'phase': 'Running',
            }
        }

        return {'items': [vm]}
    
    def pending_vms(self):
        vm = {
            'metadata': {
                'name': 'win-2016',
                'namespace': 'default',
            },
            'spec': {
                'domain': {
                    'devices': {
                        'disks': [
                            {'disk': {'bus': 'virtio'}, 'name': 'containerdisk'}
                        ],
                        'interfaces': [
                            {'bridge': {}, 'name': 'default'}
                        ],
                    },
                    'features': {
                        'acpi': {
                            'enabled': 'true'
                        }
                    },
                    'firmware': {
                        'uuid': 'f83c5f73-5244-4bd1-90cf-02bac2dda608'
                    },
                    'machine': {
                        'type': 'q35'
                    }
                }
            },
            'status': {
                'phase': 'Pending',
            }
        }

        return {'items': [vm]}

    def test_pending_vm(self):
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.pending_vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG':'/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='master',
                guestIds=[],
                facts={
                    Hypervisor.CPU_SOCKET_FACT: '2',
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
                }
            )
            result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())

    def test_getHostGuestMapping(self):
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG':'/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='master',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.CPU_SOCKET_FACT: '2',
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
                }
            )
            result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())

    def test_getHostGuestMapping_with_hm(self):
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    hypervisor_id='hostname')

        with patch.dict('os.environ', {'KUBECONFIG':'/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='minikube',
                name='master',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.CPU_SOCKET_FACT: '2',
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
                }
            )
            result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())

    def test_milicpu(self):
        client = Mock()
        client.get_nodes.return_value = self.new_nodes()
        client.get_vms.return_value = self.vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG':'/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())
            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='master',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.CPU_SOCKET_FACT: '7',
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.18.0-rc.1',
                }
            )
            result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())


    def test_empty_kubeconfig(self):
        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner')

        kubevirt = Virt.from_config(self.logger, config, Datastore())
        self.assertEqual("~/.kube/config", kubevirt._path)

    @patch("virtwho.virt.kubevirt.config._get_kube_config_loader_for_yaml_file",
           return_value=Mock())
    @patch("virtwho.virt.kubevirt.config.Configuration")
    def test_version_override(self, cfg, _):
        version='v1alpha3'
        cfg.return_value = Config()
        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    kubeversion=version, hypervisor_id='hostname')

        kubevirt = Virt.from_config(self.logger, config, Datastore())
        kubevirt.prepare()
        self.assertEqual(version, kubevirt._version)

    @patch("virtwho.virt.kubevirt.config._get_kube_config_loader_for_yaml_file",
           return_value=Mock())
    @patch("virtwho.virt.kubevirt.config.Configuration")
    def test_insecure(self, cfg, _):
        cfg.return_value = Config()
        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    kubeversion='v1alpha3', hypervisor_id='hostname',
                                    insecure='')      

        kubevirt = Virt.from_config(self.logger, config, Datastore())
        kubevirt.prepare()
        self.assertFalse(kubevirt._insecure)

class Config(object):

    ssl_ca_cert = "file"
    cert_file = "file"
    key_file = "file"
    host = "localhost"
    token = "token"

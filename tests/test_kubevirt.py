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
from mock import patch, Mock, ANY, call

from base import TestBase
from threading import Event

from virtwho.virt import Virt, Guest, Hypervisor, StatusReport, VirtError
from virtwho.virt.kubevirt.client import ApiException
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
                'name': 'main'
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
                'allocatable': {
                    'cpu': '2'
                }
            }
        }

        return {'items': [node]}

    def new_nodes(self):
        node = {
            'metadata': {
                'name': 'main'
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
                'allocatable': {
                    'cpu': '7500m'
                }
            }
        }
        return {'items': [node]}

    def cadvisor_metrics(self, sockets=2):
        # Sample of the Prometheus text format served by
        # /api/v1/nodes/{node}/proxy/metrics/cadvisor
        return (
            '# HELP machine_cpu_physical_cores Number of physical cores\n'
            '# TYPE machine_cpu_physical_cores gauge\n'
            'machine_cpu_physical_cores{boot_id="b",machine_id="m",'
            'system_uuid="s"} 32\n'
            '# HELP machine_cpu_sockets Number of CPU sockets\n'
            '# TYPE machine_cpu_sockets gauge\n'
            'machine_cpu_sockets{boot_id="b",machine_id="m",'
            'system_uuid="s"} %d\n' % sockets
        )

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
                'nodeName': 'main',
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
        client.get_node_metrics.return_value = self.cadvisor_metrics()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='main',
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
        client.get_node_metrics.return_value = self.cadvisor_metrics()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='main',
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
        client.get_node_metrics.return_value = self.cadvisor_metrics()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    hypervisor_id='hostname')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='minikube',
                name='main',
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

    def test_getHostGuestMapping_multiple_nodes(self):
        # In a cluster with several nodes, every node must be reported
        # with the socket count read from its own cAdvisor metrics
        # endpoint. A node whose metrics cannot be retrieved omits the
        # cpu.cpu_socket(s) fact without affecting the other nodes.
        def node(name, machine_id):
            return {
                'metadata': {'name': name},
                'status': {
                    'nodeInfo': {
                        'machineID': machine_id,
                        'kubeletVersion': 'v1.9.1+a0ce1bc657'
                    },
                    'addresses': [
                        {'address': '192.168.122.140',
                         'type': 'InternalIP'},
                        {'address': name,
                         'type': 'Hostname'}
                    ],
                    'allocatable': {
                        'cpu': '16'
                    }
                }
            }

        nodes = {'items': [
            node('node-a', 'a' * 32),
            node('node-b', 'b' * 32),
            node('node-c', 'c' * 32),
        ]}

        def vm(node_name, uuid):
            return {
                'metadata': {
                    'name': 'vm-on-' + node_name,
                    'namespace': 'default',
                },
                'spec': {
                    'domain': {
                        'firmware': {
                            'uuid': uuid
                        }
                    }
                },
                'status': {
                    'nodeName': node_name,
                    'phase': 'Running',
                }
            }

        vms = {'items': [
            vm('node-a', 'f83c5f73-5244-4bd1-90cf-02bac2dda60a'),
            vm('node-c', 'f83c5f73-5244-4bd1-90cf-02bac2dda60c'),
        ]}

        client = Mock()
        client.get_nodes.return_value = nodes
        client.get_vms.return_value = vms

        def metrics_for(node_name):
            if node_name == 'node-b':
                raise ApiException(status=403, reason='Forbidden')
            elif node_name == 'node-a':
                return self.cadvisor_metrics(sockets=2)
            else:
                return self.cadvisor_metrics(sockets=4)

        client.get_node_metrics.side_effect = metrics_for

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            with self.assertLogs(level='WARNING') as logged:
                result = kubevirt.getHostGuestMapping()

            by_name = {h.name: h for h in result['hypervisors']}
            self.assertEqual({'node-a', 'node-b', 'node-c'}, set(by_name))

            # each node reports its own socket count
            self.assertEqual('2',
                             by_name['node-a'].facts[Hypervisor.CPU_SOCKET_FACT])
            self.assertNotIn(Hypervisor.CPU_SOCKET_FACT,
                             by_name['node-b'].facts)
            self.assertEqual('4',
                             by_name['node-c'].facts[Hypervisor.CPU_SOCKET_FACT])

            # each node was queried for its own metrics exactly once
            self.assertEqual(
                [call('node-a'), call('node-b'), call('node-c')],
                client.get_node_metrics.call_args_list)

            # guests stay associated with their own nodes
            self.assertEqual(
                ['f83c5f73-5244-4bd1-90cf-02bac2dda60a'],
                [guest.uuid for guest in by_name['node-a'].guestIds])
            self.assertEqual([], by_name['node-b'].guestIds)
            self.assertEqual(
                ['f83c5f73-5244-4bd1-90cf-02bac2dda60c'],
                [guest.uuid for guest in by_name['node-c'].guestIds])

            # the failing node is named in the logged warning
            self.assertTrue(
                any('node-b' in output for output in logged.output))

    def test_cpu_sockets_metric_api_error(self):
        # When the cAdvisor metrics of a node cannot be retrieved, the
        # cpu.cpu_socket(s) fact is omitted and a warning is logged
        # instead of falling back to the logical CPU count.
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.vms()
        client.get_node_metrics.side_effect = ApiException(
            status=403, reason='Forbidden')

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='main',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
                }
            )
            with self.assertLogs(level='WARNING') as logged:
                result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())
            self.assertTrue(
                any('cpu.cpu_socket(s)' in output for output in logged.output))

    def test_cpu_sockets_metric_missing(self):
        # The metrics endpoint answered but does not expose the
        # machine_cpu_sockets metric: omit the cpu.cpu_socket(s) fact
        # and log a warning.
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.vms()
        client.get_node_metrics.return_value = (
            '# HELP machine_cpu_physical_cores Number of physical cores\n'
            '# TYPE machine_cpu_physical_cores gauge\n'
            'machine_cpu_physical_cores{boot_id="b",machine_id="m",'
            'system_uuid="s"} 32\n'
        )

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='main',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
                }
            )
            with self.assertLogs(level='WARNING') as logged:
                result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())
            self.assertTrue(
                any('machine_cpu_sockets' in output for output in logged.output))

    def test_cpu_sockets_metric_malformed(self):
        # A machine_cpu_sockets value that cannot be parsed (here NaN,
        # which int() rejects) must not abort the host-guest mapping:
        # the fact is omitted for that node and a warning is logged.
        client = Mock()
        client.get_nodes.return_value = self.nodes()
        client.get_vms.return_value = self.vms()
        client.get_node_metrics.return_value = (
            '# HELP machine_cpu_sockets Number of CPU sockets\n'
            '# TYPE machine_cpu_sockets gauge\n'
            'machine_cpu_sockets{boot_id="b",machine_id="m",'
            'system_uuid="s"} NaN\n'
        )

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='main',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                    Hypervisor.SYSTEM_UUID_FACT: '52c01ad890e84b15a1be4be18bd64ecd',
                    Hypervisor.HYPERVISOR_VERSION_FACT: 'v1.9.1+a0ce1bc657',
                }
            )
            with self.assertLogs(level='WARNING') as logged:
                result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())
            self.assertTrue(
                any('machine_cpu_sockets' in output for output in logged.output))

    def test_getHostGuestMapping_nodes_forbidden(self):
        client = Mock()
        client.get_nodes.side_effect = ApiException(status=403, reason='Forbidden')
        client.get_vms.return_value = self.vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    namespace='default',
                                    hypervisor_id_fallback=True)

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='main',
                name='main',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                }
            )
            result = kubevirt.getHostGuestMapping()['hypervisors'][0]
            self.assertEqual(expected_result.toDict(), result.toDict())

    def test_getHostGuestMapping_nodes_forbidden_without_fallback_raises(self):
        client = Mock()
        client.get_nodes.side_effect = ApiException(status=403, reason='Forbidden')
        client.get_vms.return_value = self.vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    namespace='default')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            self.assertRaises(ApiException, kubevirt.getHostGuestMapping)

    def test_getHostGuestMapping_nodes_other_error_raises(self):
        client = Mock()
        client.get_nodes.side_effect = ApiException(status=401, reason='Unauthorized')
        client.get_vms.return_value = self.vms()

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            self.assertRaises(ApiException, kubevirt.getHostGuestMapping)

    def test_statusConfirmConnection_nodes_forbidden_falls_back_to_vms(self):
        client = Mock()
        client.get_nodes.side_effect = ApiException(status=403, reason='Forbidden')
        client.host = 'kubeserver'

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    namespace='default',
                                    hypervisor_id_fallback=True)

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            kubevirt.statusConfirmConnection()

            client.get_vms.assert_called_once_with()
            self.assertEqual('kubeserver', kubevirt.config['server'])

    def test_statusConfirmConnection_nodes_forbidden_without_fallback_raises(self):
        client = Mock()
        client.get_nodes.side_effect = ApiException(status=403, reason='Forbidden')
        client.host = 'kubeserver'

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    namespace='default')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            self.assertRaises(ApiException, kubevirt.statusConfirmConnection)
            client.get_vms.assert_not_called()

    def test_statusConfirmConnection_other_error_raises(self):
        client = Mock()
        client.get_nodes.side_effect = ApiException(status=401, reason='Unauthorized')
        client.host = 'kubeserver'

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())

            kubevirt._client = client

            self.assertRaises(ApiException, kubevirt.statusConfirmConnection)
            client.get_vms.assert_not_called()

    def test_millicpu_allocatable_not_reported_as_sockets(self):
        # The node reports 7500m (7.5) allocatable CPUs; this logical
        # CPU count must not be reported as the socket count, which
        # comes from the cAdvisor metrics instead (RHEL-261147).
        client = Mock()
        client.get_nodes.return_value = self.new_nodes()
        client.get_vms.return_value = self.vms()
        client.get_node_metrics.return_value = self.cadvisor_metrics(sockets=1)

        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts')

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, config, Datastore())
            kubevirt._client = client

            expected_result = Hypervisor(
                hypervisorId='52c01ad890e84b15a1be4be18bd64ecd',
                name='main',
                guestIds=[
                    Guest(
                        'f83c5f73-5244-4bd1-90cf-02bac2dda608',
                        kubevirt.CONFIG_TYPE,
                        Guest.STATE_RUNNING,
                    )
                ],
                facts={
                    Hypervisor.CPU_SOCKET_FACT: '1',
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

    def test_empty_namespace(self):
        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner')

        kubevirt = Virt.from_config(self.logger, config, Datastore())
        self.assertEqual("", kubevirt._namespace)

    @patch("virtwho.virt.kubevirt.kubevirt.KubeClient")
    def test_namespace(self, kube_client):
        config = self.create_config(name='test', wrapper=None, type='kubevirt',
                                    owner='owner', kubeconfig='/etc/hosts',
                                    namespace='my-namespace')

        kubevirt = Virt.from_config(self.logger, config, Datastore())
        self.assertEqual("my-namespace", kubevirt._namespace)

        kubevirt.prepare()
        kube_client.assert_called_once_with('my-namespace', '/etc/hosts', '', False)

    @patch("virtwho.virt.kubevirt.config._get_kube_config_loader_for_yaml_file",
           return_value=Mock())
    @patch("virtwho.virt.kubevirt.config.Configuration")
    def test_version_override(self, cfg, _):
        version = 'v1alpha3'
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
        config = self.create_config(
            name='test', wrapper=None, type='kubevirt',
            owner='owner', kubeconfig='/etc/hosts',
            kubeversion='v1alpha3', hypervisor_id='hostname',
            insecure=''
        )

        kubevirt = Virt.from_config(self.logger, config, Datastore())
        kubevirt.prepare()
        self.assertFalse(kubevirt._insecure)

    @patch("virtwho.virt.kubevirt.kubevirt.KubeClient")
    @patch("virtwho.virt.kubevirt.config._get_kube_config_loader_for_yaml_file",
           return_value=Mock())
    @patch("virtwho.virt.kubevirt.config.Configuration")
    def test_status(self, cfg, _, kube_client):
        cfg.return_value = Config()
        kube_client.get_nodes = Mock(return_value=self.nodes())
        kube_client.get_vms.return_value = Mock(return_value=self.vms())

        self.config = self.create_config(
            name='test', wrapper=None, type='kubevirt',
            owner='owner', kubeconfig='/etc/hosts',
            kubeversion='version', hypervisor_id='hostname'
        )
        self.config['server'] = 'kubeserver'

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, self.config, Datastore())
            kubevirt.status = True
            kubevirt._send_data = Mock()
            self.run_once(kubevirt)

            kubevirt._send_data.assert_called_once_with(data_to_send=ANY)
            self.assertTrue(isinstance(kubevirt._send_data.mock_calls[0].kwargs['data_to_send'], StatusReport))
            self.assertEqual(
                kubevirt._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['server'],
                self.config['server']
            )

    @patch("virtwho.virt.kubevirt.kubevirt.KubeClient")
    @patch("virtwho.virt.kubevirt.config._get_kube_config_loader_for_yaml_file",
           return_value=Mock())
    @patch("virtwho.virt.kubevirt.config.Configuration")
    def test_status_config_file_host(self, cfg, _, kube_client):
        cfg.return_value = Config()
        kube_client.client.get_nodes = Mock(return_value=self.nodes())
        kube_client.client.get_vms.return_value = Mock(return_value=self.vms())
        kube_client.return_value.host = 'kubeserver'
        cfg.return_value.host = None

        self.config = self.create_config(
            name='test', wrapper=None, type='kubevirt',
            owner='owner', kubeconfig='/etc/hosts',
            kubeversion='version', hypervisor_id='hostname'
        )

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, self.config, Datastore())
            kubevirt.status = True
            kubevirt._send_data = Mock()
            self.run_once(kubevirt)

            kubevirt._send_data.assert_called_once_with(data_to_send=ANY)
            self.assertTrue(isinstance(kubevirt._send_data.mock_calls[0].kwargs['data_to_send'], StatusReport))
            self.assertEqual(
                kubevirt._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['server'],
                'kubeserver'
            )

    @patch("virtwho.virt.kubevirt.kubevirt.KubeClient")
    @patch("virtwho.virt.kubevirt.config._get_kube_config_loader_for_yaml_file",
           return_value=Mock())
    @patch("virtwho.virt.kubevirt.config.Configuration")
    def test_status_bad_source_credentials(self, cfg, _, kube_client):
        cfg.return_value = Config()
        kube_client.get_nodes = Mock(return_value=self.nodes())
        kube_client.get_vms.return_value = Mock(return_value=self.vms())

        self.config = self.create_config(
            name='test', wrapper=None, type='kubevirt',
            owner='owner', kubeconfig='/etc/hosts',
            kubeversion='version', hypervisor_id='hostname'
        )
        self.config['server'] = 'kubeserver'

        with patch.dict('os.environ', {'KUBECONFIG': '/dev/null'}):
            kubevirt = Virt.from_config(self.logger, self.config, Datastore())
            kubevirt.status = True
            kubevirt._send_data = Mock()
            kubevirt.statusConfirmConnection = Mock()
            kubevirt.statusConfirmConnection.side_effect = VirtError("Incorrect domain/username/password")
            kubevirt.dest = Mock(spec=Datastore())
            kubevirt._terminate_event = Event()
            kubevirt._oneshot = True
            kubevirt._interval = 0
            kubevirt.run()

            kubevirt._send_data.assert_called_once_with(data_to_send=ANY)
            self.assertTrue(isinstance(kubevirt._send_data.mock_calls[0].kwargs['data_to_send'], StatusReport))
            self.assertEqual(
                kubevirt._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['server'],
                self.config['server']
            )
            self.assertEqual(
                kubevirt._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['message'],
                "Incorrect domain/username/password."
            )

    def run_once(self, kubevirt, datastore=None):
        ''' Run kubevirt in oneshot mode '''
        if datastore is None:
            datastore = Mock(spec=Datastore())

        kubevirt.dest = datastore
        kubevirt._terminate_event = Event()
        kubevirt._oneshot = True
        kubevirt._interval = 0
        kubevirt._run()


class Config(object):

    ssl_ca_cert = "file"
    cert_file = "file"
    key_file = "file"
    host = "localhost"
    token = "token"

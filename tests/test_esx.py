# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Test of ESX virtualization backend.

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

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

import os
import requests
import suds
from mock import patch, ANY, MagicMock, Mock
from threading import Event

from base import TestBase
from virtwho import DefaultInterval
from virtwho.datastore import Datastore
from virtwho.virt.esx import Esx
from virtwho.virt import VirtError, Guest, Hypervisor, HostGuestAssociationReport
from proxy import Proxy

from virtwho.virt.esx.esx import EsxConfigSection


class TestEsx(TestBase):
    def setUp(self):
        config_values = {
            'type': 'esx',
            'server': 'localhost',
            'username': 'username',
            'password': 'password',
            'owner': 'owner',
            'env': 'env',
        }
        config = EsxConfigSection('test', None)
        config.update(**config_values)
        config.validate()
        self.esx = Esx(self.logger, config, None, interval=DefaultInterval)  #  No dest given here

    def run_once(self, datastore=None):
        ''' Run ESX in oneshot mode '''
        self.esx._oneshot = True
        if datastore is None:
            datastore = Mock(spec=Datastore())

        self.esx.dest = datastore
        self.esx._terminate_event = Event()
        self.esx._oneshot = True
        self.esx._interval = 0
        self.esx._run()

    @patch('suds.client.Client')
    def test_connect(self, mock_client):
        mock_client.return_value.service.WaitForUpdatesEx.return_value = None
        self.run_once()

        self.assertTrue(mock_client.called)
        mock_client.assert_called_with(ANY, location="https://localhost/sdk", cache=None, transport=ANY)
        mock_client.return_value.service.RetrieveServiceContent.assert_called_once_with(_this=ANY)
        mock_client.return_value.service.Login.assert_called_once_with(_this=ANY, userName='username', password='password')

    @patch('suds.client.Client')
    def test_connect_utf_password(self, mock_client):
        mock_client.return_value.service.WaitForUpdatesEx.return_value = None
        # Change password to include some UTF character
        self.esx.password = 'Žluťoučký_kůň'
        self.run_once()

        self.assertTrue(mock_client.called)
        mock_client.assert_called_with(ANY, location="https://localhost/sdk", cache=None, transport=ANY)
        mock_client.return_value.service.RetrieveServiceContent.assert_called_once_with(_this=ANY)
        mock_client.return_value.service.Login.assert_called_once_with(
            _this=ANY, userName='username', password=u'Žluťoučký_kůň'
        )

    @patch('suds.client.Client')
    def test_connection_timeout(self, mock_client):
        mock_client.side_effect = requests.Timeout('timed out')
        self.assertRaises(VirtError, self.run_once)

    @patch('suds.client.Client')
    def test_invalid_login(self, mock_client):
        mock_client.return_value.service.Login.side_effect = suds.WebFault('Permission to perform this operation was denied.', '')
        self.assertRaises(VirtError, self.run_once)

    @patch('suds.client.Client')
    def test_disable_simplified_vim(self, mock_client):
        self.esx.config.simplified_vim = False
        mock_client.return_value.service.RetrievePropertiesEx.return_value = None
        mock_client.return_value.service.WaitForUpdatesEx.return_value.truncated = False
        self.run_once()

        self.assertTrue(mock_client.called)
        mock_client.assert_called_with(ANY, location="https://localhost/sdk", transport=ANY,
                                       cache=None)
        mock_client.return_value.service.RetrieveServiceContent.assert_called_once_with(_this=ANY)
        mock_client.return_value.service.Login.assert_called_once_with(_this=ANY, userName='username', password='password')

    @patch('suds.client.Client')
    def test_getHostGuestMapping(self, mock_client):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = 'Fake_uuid'
        expected_guestId = 'guest1UUID'
        expected_guest_state = Guest.STATE_RUNNING

        fake_parent = MagicMock()
        fake_parent.value = 'fake_parent_id'
        fake_parent._type = 'ClusterComputeResource'

        fake_vm_id = MagicMock()
        fake_vm_id.value = 'guest1'

        fake_vm = MagicMock()
        fake_vm.ManagedObjectReference = [fake_vm_id]
        fake_vms = {'guest1': {'runtime.powerState': 'poweredOn',
                               'config.uuid': expected_guestId}}
        self.esx.vms = fake_vms

        fake_host = {'hardware.systemInfo.uuid': expected_hypervisorId,
                     'config.network.dnsConfig.hostName': 'hostname',
                     'config.network.dnsConfig.domainName': 'domainname',
                     'config.product.version': '1.2.3',
                     'hardware.cpuInfo.numCpuPackages': '1',
                     'name': expected_hostname,
                     'parent': fake_parent,
                     'vm': fake_vm,
                     }
        fake_hosts = {'random-host-id': fake_host}
        self.esx.hosts = fake_hosts

        fake_cluster = {'name': 'Fake_cluster_name'}
        self.esx.clusters = {'fake_parent_id': fake_cluster}

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.esx.CONFIG_TYPE,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'vmware',
                Hypervisor.HYPERVISOR_VERSION_FACT: '1.2.3',
                Hypervisor.HYPERVISOR_CLUSTER: 'Fake_cluster_name',
            }
        )
        result = self.esx.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

    @patch('suds.client.Client')
    def test_getHostGuestMapping_incomplete_data(self, mock_client):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = 'Fake_uuid'
        expected_guestId = 'guest1UUID'
        expected_guest_state = Guest.STATE_UNKNOWN

        fake_parent = MagicMock()
        fake_parent.value = 'fake_parent_id'
        fake_parent._type = 'ClusterComputeResource'

        fake_vm_id = MagicMock()
        fake_vm_id.value = 'guest1'

        fake_vm = MagicMock()
        fake_vm.ManagedObjectReference = [fake_vm_id]
        fake_vms = {'guest1': {'runtime.powerState': 'BOGUS_STATE',
                               'config.uuid': expected_guestId}}
        self.esx.vms = fake_vms

        fake_host = {'hardware.systemInfo.uuid': expected_hypervisorId,
                     'config.network.dnsConfig.hostName': 'hostname',
                     'config.network.dnsConfig.domainName': 'domainname',
                     'config.product.version': '1.2.3',
                     'hardware.cpuInfo.numCpuPackages': '1',
                     'parent': fake_parent,
                     'vm': fake_vm
                     }
        fake_hosts = {'random-host-id': fake_host}
        self.esx.hosts = fake_hosts

        fake_cluster = {'name': 'Fake_cluster_name'}
        self.esx.clusters = {'fake_parent_id': fake_cluster}

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.esx.CONFIG_TYPE,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'vmware',
                Hypervisor.HYPERVISOR_VERSION_FACT: '1.2.3',
                Hypervisor.HYPERVISOR_CLUSTER: 'Fake_cluster_name'
            }
        )
        result = self.esx.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

    @patch('suds.client.Client')
    def test_oneshot(self, mock_client):
        expected_assoc = '"well formed HostGuestMapping"'
        expected_report = HostGuestAssociationReport(self.esx.config, expected_assoc)
        updateSet = Mock()
        updateSet.version = 'some_new_version_string'
        updateSet.truncated = False
        mock_client.return_value.service.WaitForUpdatesEx.return_value = updateSet
        datastore = Datastore()
        self.esx.applyUpdates = Mock()
        getHostGuestMappingMock = Mock()
        getHostGuestMappingMock.return_value = expected_assoc
        self.esx.getHostGuestMapping = getHostGuestMappingMock
        self.run_once(datastore)
        result_report = datastore.get(self.esx.config.name)
        self.assertEqual(expected_report.config.name, result_report.config.name)
        self.assertEqual(expected_report.config._values, result_report.config._values)
        self.assertEqual(expected_report._assoc, result_report._assoc)

    def test_proxy(self):
        self.esx.config['simplified_vim'] = True
        proxy = Proxy()
        self.addCleanup(proxy.terminate)
        proxy.start()
        oldenv = os.environ.copy()
        self.addCleanup(lambda: setattr(os, 'environ', oldenv))
        os.environ['https_proxy'] = proxy.address

        self.assertRaises(VirtError, self.run_once)
        self.assertIsNotNone(proxy.last_path, "Proxy was not called")
        self.assertEqual(proxy.last_path, 'localhost:443')

    def test_applyHostSystemUpdate_AttributeError(self):
        change = Mock(spec=['op', 'name'])
        change.op = 'assign'
        change.name = 'test.guest.name'

        objectSet = Mock()
        objectSet.kind = 'modify'
        objectSet.obj.value = 'test.host.name'
        objectSet.changeSet = [change]

        self.esx.hosts = dict()
        self.esx.hosts[objectSet.obj.value] = dict()

        try:
            self.esx.applyHostSystemUpdate(objectSet)
        except AttributeError:
            self.fail('applyHostSystemUpdate raised AttributeError unexpectedly')
        self.assertDictEqual(self.esx.hosts[objectSet.obj.value], dict())


    def test_applyHostSystemUpdate_leave(self):
        objectSet = Mock()
        objectSet.kind = 'leave'
        objectSet.obj.value = 'test.host.name'

        self.esx.hosts = dict()
        self.esx.hosts[objectSet.obj.value] = dict()

        self.esx.applyHostSystemUpdate(objectSet)
        self.assertDictEqual(self.esx.hosts, dict())

    def test_applyHostSystemUpdate_modify(self):
        change = Mock(spec=['op', 'name', 'val'])
        change.op = 'assign'
        change.name = 'test.guest.name'
        change.val = 'test'

        objectSet = Mock()
        objectSet.kind = 'modify'
        objectSet.obj.value = 'test.host.name'
        objectSet.changeSet = [change]

        self.esx.hosts = dict()
        self.esx.hosts[objectSet.obj.value] = dict()

        self.esx.applyHostSystemUpdate(objectSet)

        expected = dict()
        expected[change.name] = change.val
        self.assertDictEqual(self.esx.hosts[objectSet.obj.value], expected)

    def test_applyVirtualMachineUpdate_AttributeError(self):
        change = Mock(spec=['op', 'name'])
        change.op = 'assign'
        change.name = 'test.guest.name'

        objectSet = Mock()
        objectSet.kind = 'modify'
        objectSet.obj.value = 'test.host.name'
        objectSet.changeSet = [change]

        self.esx.vms = dict()
        self.esx.vms[objectSet.obj.value] = dict()

        try:
            self.esx.applyVirtualMachineUpdate(objectSet)
        except AttributeError:
            self.fail('applyHostSystemUpdate raised AttributeError unexpectedly')
        self.assertDictEqual(self.esx.vms[objectSet.obj.value], dict())

    def test_applyVirtualMachineUpdate_leave(self):
        objectSet = Mock()
        objectSet.kind = 'leave'
        objectSet.obj.value = 'test.host.name'

        self.esx.vms = dict()
        self.esx.vms[objectSet.obj.value] = dict()

        self.esx.applyVirtualMachineUpdate(objectSet)
        self.assertDictEqual(self.esx.vms, dict())

    def test_applyVirtualMachineUpdate_modify(self):
        change = Mock(spec=['op', 'name', 'val'])
        change.op = 'assign'
        change.name = 'test.guest.name'
        change.val = 'test'

        objectSet = Mock()
        objectSet.kind = 'modify'
        objectSet.obj.value = 'test.host.name'
        objectSet.changeSet = [change]

        self.esx.vms = dict()
        self.esx.vms[objectSet.obj.value] = dict()

        self.esx.applyVirtualMachineUpdate(objectSet)

        expected = dict()
        expected[change.name] = change.val
        self.assertDictEqual(self.esx.vms[objectSet.obj.value], expected)

    def test_applyVirtualMachineUpdate_add(self):
        change = Mock(spec=['op', 'name', 'val'])
        change.op = 'add'
        change.name = 'test.guest.name'
        change.val = 'test'

        objectSet = Mock()
        objectSet.kind = 'modify'
        objectSet.obj.value = 'test.host.name'
        objectSet.changeSet = [change]

        self.esx.vms = dict()
        self.esx.vms[objectSet.obj.value] = dict()
        self.esx.vms[objectSet.obj.value][change.name] = []

        self.esx.applyVirtualMachineUpdate(objectSet)

        expected = dict()
        expected[change.name] = [change.val]
        self.assertDictEqual(self.esx.vms[objectSet.obj.value], expected)

    def test_applyVirtualMachineUpdate_remove(self):
        change = Mock(spec=['op', 'name', 'val'])
        change.op = 'remove'
        change.name = 'test.guest.name'
        change.val = 'test'

        objectSet = Mock()
        objectSet.kind = 'modify'
        objectSet.obj.value = 'test.host.name'
        objectSet.changeSet = [change]

        self.esx.vms = dict()
        self.esx.vms[objectSet.obj.value] = dict()
        self.esx.vms[objectSet.obj.value][change.name] = 'test'

        self.esx.applyVirtualMachineUpdate(objectSet)

        expected = dict()
        self.assertDictEqual(self.esx.vms[objectSet.obj.value], expected)

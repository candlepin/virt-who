# -*- coding: utf-8 -*-

from __future__ import print_function
"""
Test of RHEV-M virtualization backend.

Copyright (C) 2016 Radek Novacek <rnovacek@redhat.com>

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
from mock import patch, call, ANY, MagicMock
from threading import Event
from six.moves.queue import Queue

from base import TestBase
from proxy import Proxy

from virtwho.virt import Virt, VirtError, Guest, Hypervisor
from virtwho.virt.rhevm.rhevm import RhevmConfigSection
from virtwho.datastore import Datastore


uuids = {
    'cluster': '00000000-0000-0000-0000-000000000001',
    'host': '00000000-0000-0000-0000-000000000002',
    'vm': '00000000-0000-0000-0000-000000000003',
}


CLUSTERS_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<clusters>
    <cluster href="/api/clusters/{cluster}" id="{cluster}">
        <name>Cetus</name>
        <virt_service>true</virt_service>
    </cluster>
</clusters>
'''.format(**uuids)


HOSTS_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hosts>
    <host href="/api/hosts/{host}" id="{host}">
        <name>hostname.domainname</name>
        <address>hostname.domainname</address>
        <cluster href="/api/clusters/{cluster}" id="{cluster}"/>
        <cpu>
            <topology sockets="1" cores="6" threads="2"/>
        </cpu>
        <version full_version="1.2.3" />
        <hardware_information>
            <uuid>db5a7a9f-6e33-3bfd-8129-c8010e4e1497</uuid>
        </hardware_information>
    </host>
</hosts>
'''.format(**uuids)


VMS_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<vms>
    <vm href="/api/vms/{vm}" id="{vm}">
        <name>atomic1</name>
        <status>
            <state>down</state>
        </status>
        <host href="/api/hosts/{host}" id="{host}"/>
        <cluster href="/api/clusters/{cluster}" id="{cluster}"/>
    </vm>
</vms>
'''.format(**uuids)


VMS_XML_STATUS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<vms>
    <vm href="/api/vms/{vm}" id="{vm}">
        <name>atomic1</name>
        <status>up</status>
        <host href="/api/hosts/{host}" id="{host}"/>
        <cluster href="/api/clusters/{cluster}" id="{cluster}"/>
    </vm>
</vms>
'''.format(**uuids)


class TestRhevM(TestBase):
    @staticmethod
    def create_config(name, wrapper, **kwargs):
        config = RhevmConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self):
        config = self.create_config(name='test', wrapper=None, type='rhevm', server='localhost', username='username',
                        password=u'1€345678', owner='owner', env='env')
        self.rhevm = Virt.from_config(self.logger, config, Datastore())
        self.rhevm.major_version = '3'
        self.rhevm.build_urls()

    def run_once(self, queue=None):
        """Run RHEV-M in oneshot mode"""
        self.rhevm._oneshot = True
        self.rhevm.dest = queue or Queue()
        self.rhevm._terminate_event = Event()
        self.rhevm._oneshot = True
        self.rhevm._interval = 0
        self.rhevm._run()

    @patch('requests.get')
    def test_connect(self, get):
        get.return_value.content = '<xml></xml>'
        get.return_value.status_code = 200
        self.run_once()

        self.assertEqual(get.call_count, 3)
        get.assert_has_calls([
            call('https://localhost:8443/api/clusters', auth=ANY, verify=ANY),
            call().raise_for_status(),
            call('https://localhost:8443/api/hosts', auth=ANY, verify=ANY),
            call().raise_for_status(),
            call('https://localhost:8443/api/vms', auth=ANY, verify=ANY),
            call().raise_for_status(),
        ])
        self.assertEqual(get.call_args[1]['auth'].username, u'username'.encode('utf-8'))
        self.assertEqual(get.call_args[1]['auth'].password, u'1€345678'.encode('utf-8'))

    @patch('requests.get')
    def test_connection_refused(self, get):
        get.return_value.post.side_effect = requests.ConnectionError
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_invalid_login(self, get):
        get.return_value.status_code = 401
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_404(self, get):
        get.return_value.content = ''
        get.return_value.status_code = 404
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_500(self, get):
        get.return_value.content = ''
        get.return_value.status_code = 500
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_getHostGuestMapping(self, get):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = uuids['host']
        expected_guestId = uuids['vm']
        expected_guest_state = Guest.STATE_SHUTOFF

        get.side_effect = [
            MagicMock(content=CLUSTERS_XML),
            MagicMock(content=HOSTS_XML),
            MagicMock(content=VMS_XML),
        ]

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.rhevm.CONFIG_TYPE,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                Hypervisor.HYPERVISOR_VERSION_FACT: '1.2.3',
                Hypervisor.HYPERVISOR_CLUSTER: 'Cetus',
                Hypervisor.SYSTEM_UUID_FACT: 'db5a7a9f-6e33-3bfd-8129-c8010e4e1497',
            }
        )
        result = self.rhevm.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

    def test_proxy(self):
        proxy = Proxy()
        self.addCleanup(proxy.terminate)
        proxy.start()
        oldenv = os.environ.copy()
        self.addCleanup(lambda: setattr(os, 'environ', oldenv))
        os.environ['https_proxy'] = proxy.address

        self.assertRaises(VirtError, self.run_once)
        self.assertIsNotNone(proxy.last_path, "Proxy was not called")
        self.assertEqual(proxy.last_path, 'localhost:8443')

    @patch('requests.get')
    def test_new_status(self, get):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = uuids['host']
        expected_guestId = uuids['vm']
        expected_guest_state = Guest.STATE_RUNNING

        get.side_effect = [
            MagicMock(content=CLUSTERS_XML),
            MagicMock(content=HOSTS_XML),
            MagicMock(content=VMS_XML_STATUS),
        ]

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.rhevm.CONFIG_TYPE,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'qemu',
                Hypervisor.HYPERVISOR_VERSION_FACT: '1.2.3',
                Hypervisor.HYPERVISOR_CLUSTER: 'Cetus',
                Hypervisor.SYSTEM_UUID_FACT: 'db5a7a9f-6e33-3bfd-8129-c8010e4e1497',
            }
        )
        result = self.rhevm.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

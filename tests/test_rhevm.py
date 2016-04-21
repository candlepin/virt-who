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
from multiprocessing import Queue, Event

from base import TestBase
from config import Config
from virt.rhevm import RhevM
from virt import VirtError, Guest, Hypervisor
from proxy import Proxy


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
        <cluster href="/api/clusters/{cluster}" id="{cluster}"/>
        <cpu>
            <topology sockets="1" cores="6" threads="2"/>
        </cpu>
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


class TestRhevM(TestBase):
    def setUp(self):
        config = Config('test', 'rhevm', server='localhost', username='username',
                        password='password', owner='owner', env='env')
        self.rhevm = RhevM(self.logger, config)

    def run_once(self, queue=None):
        ''' Run RHEV-M in oneshot mode '''
        self.rhevm._oneshot = True
        self.rhevm._queue = queue or Queue()
        self.rhevm._terminate_event = Event()
        self.rhevm._oneshot = True
        self.rhevm._interval = 0
        self.rhevm._run()

    @patch('requests.get')
    def test_connect(self, get):
        get.return_value.text = '<xml></xml>'
        self.run_once()

        self.assertEqual(get.call_count, 3)
        get.assert_has_calls([
            call('https://localhost:8443/api/clusters', auth=ANY, verify=ANY),
            call('https://localhost:8443/api/hosts', auth=ANY, verify=ANY),
            call('https://localhost:8443/api/vms', auth=ANY, verify=ANY),
        ])
        self.assertEqual(get.call_args[1]['auth'].username, 'username')
        self.assertEqual(get.call_args[1]['auth'].password, 'password')

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
        get.return_value.text = ''
        get.return_value.status_code = 404
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_500(self, get):
        get.return_value.text = ''
        get.return_value.status_code = 500
        self.assertRaises(VirtError, self.run_once)

    @patch('requests.get')
    def test_getHostGuestMapping(self, get):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = uuids['host']
        expected_guestId = uuids['vm']
        expected_guest_state = Guest.STATE_SHUTOFF

        get.side_effect = [
            MagicMock(text=CLUSTERS_XML),
            MagicMock(text=HOSTS_XML),
            MagicMock(text=VMS_XML),
        ]

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.rhevm,
                    expected_guest_state,
                    hypervisorType='qemu',
                    hypervisorVersion='',
                )
            ],
            facts={
                'cpu.cpu_socket(s)': '1',
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

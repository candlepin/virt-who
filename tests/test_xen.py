"""
Test of XenServer virtualization backend.

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
import urllib2
from mock import patch, call, ANY
from threading import Event
from Queue import Queue

from base import TestBase
from proxy import Proxy

from virtwho.config import Config
from virtwho.virt.xen import Xen
from virtwho.virt.xen.XenAPI import NewMaster, Failure
from virtwho.virt import VirtError, Guest, Hypervisor


class TestXen(TestBase):
    def setUp(self):
        config = Config('test', 'xen', server='localhost', username='username',
                        password='password', owner='owner', env='env')
        self.xen = Xen(self.logger, config)

    def run_once(self, queue=None):
        ''' Run XEN in oneshot mode '''
        self.xen._oneshot = True
        self.xen._queue = queue or Queue()
        self.xen._terminate_event = Event()
        self.xen._oneshot = True
        self.xen._interval = 0
        self.xen._run()

    @patch('virtwho.virt.xen.XenAPI.Session')
    def test_connect(self, session):
        session.return_value.xenapi.login_with_password.return_value = None
        session.return_value.xenapi.event_from.return_value = {}
        self.run_once()

        session.assert_called_with('https://localhost', transport=ANY)
        self.assertTrue(session.return_value.xenapi.login_with_password.called)
        session.return_value.xenapi.login_with_password.assert_called_with('username', 'password')

    @patch('virtwho.virt.xen.XenAPI.Session')
    def test_connection_timeout(self, session):
        session.side_effect = urllib2.URLError('timed out')
        self.assertRaises(VirtError, self.run_once)

    @patch('virtwho.virt.xen.XenAPI.Session')
    def test_invalid_login(self, session):
        session.return_value.xenapi.login_with_password.side_effect = Failure('details')
        self.assertRaises(VirtError, self.run_once)

    @patch('virtwho.virt.xen.XenAPI.Session')
    def test_getHostGuestMapping(self, session):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = 'Fake_uuid'
        expected_guestId = 'guest1UUID'
        expected_guest_state = Guest.STATE_UNKNOWN

        xenapi = session.return_value.xenapi

        host = {
            'uuid': expected_hypervisorId,
            'hostname': expected_hostname,
            'cpu_info': {
                'socket_count': '1'
            },
            'software_version': {
                'product_brand': 'XenServer',
                'product_version': '1.2.3',
            },
        }
        xenapi.host.get_all.return_value = [
            host
        ]
        xenapi.host.get_record.return_value = host
        control_domain = {
            'uuid': '0',
            'is_control_domain': True,
        }
        guest = {
            'uuid': expected_guestId,
            'power_state': 'unknown',
        }
        snapshot = {
            'uuid': '12345678-90AB-CDEF-1234-567890ABCDEF',
            'is_a_snapshot': True,
            'power_state': 'unknown',
        }

        xenapi.host.get_resident_VMs.return_value = [
            control_domain,
            snapshot,
            guest,
        ]
        xenapi.VM.get_record = lambda x: x

        expected_result = Hypervisor(
            hypervisorId=expected_hypervisorId,
            name=expected_hostname,
            guestIds=[
                Guest(
                    expected_guestId,
                    self.xen,
                    expected_guest_state,
                )
            ],
            facts={
                Hypervisor.CPU_SOCKET_FACT: '1',
                Hypervisor.HYPERVISOR_TYPE_FACT: 'XenServer',
                Hypervisor.HYPERVISOR_VERSION_FACT: '1.2.3',
            }
        )
        self.xen._prepare()
        result = self.xen.getHostGuestMapping()['hypervisors'][0]
        self.assertEqual(expected_result.toDict(), result.toDict())

    @patch('virtwho.virt.xen.XenAPI.Session')
    def test_multiple_hosts(self, session):
        expected_hostname = 'hostname.domainname'
        expected_hypervisorId = 'Fake_uuid'
        expected_guestId = 'guest1UUID'
        expected_guest_state = Guest.STATE_UNKNOWN

        xenapi = session.return_value.xenapi

        hosts = []
        for i in range(3):
            hosts.append({
                'uuid': expected_hypervisorId + str(i),
                'hostname': expected_hostname + str(i),
                'cpu_info': {
                    'socket_count': '1'
                },
                'software_version': {
                    'product_brand': 'XenServer',
                    'product_version': '1.2.3',
                },
            })

        guest = {
            'uuid': expected_guestId,
            'power_state': 'unknown',
        }

        xenapi.host.get_all.return_value = hosts
        xenapi.host.get_resident_VMs.return_value = [
            guest,
        ]
        xenapi.host.get_record = lambda x: x
        xenapi.VM.get_record = lambda x: x

        expected_result = [
            Hypervisor(
                hypervisorId=expected_hypervisorId + str(i),
                name=expected_hostname + str(i),
                guestIds=[
                    Guest(
                        expected_guestId,
                        self.xen,
                        expected_guest_state,
                    )
                ],
                facts={
                    Hypervisor.CPU_SOCKET_FACT: '1',
                    Hypervisor.HYPERVISOR_TYPE_FACT: 'XenServer',
                    Hypervisor.HYPERVISOR_VERSION_FACT: '1.2.3',
                }
            ) for i in range(3)]
        self.xen._prepare()
        result = self.xen.getHostGuestMapping()['hypervisors']
        self.assertEqual(len(result), 3, "3 hosts should be reported")
        self.assertEqual([x.toDict() for x in expected_result], [x.toDict() for x in result])

    @patch('virtwho.virt.xen.XenAPI.Session')
    def test_new_master(self, session):
        session.return_value.xenapi.event_from.return_value = {}
        session.return_value.xenapi.login_with_password.side_effect = [
            NewMaster('details', 'new.master.xxx'),
            NewMaster('details', 'http://new2.master.xxx'),
            None]
        self.run_once()
        session.assert_has_calls([
            call('https://localhost', transport=ANY),
            call('https://new.master.xxx', transport=ANY),
            call('http://new2.master.xxx', transport=ANY)
        ], any_order=True)

    def test_proxy(self):
        proxy = Proxy()
        self.addCleanup(proxy.terminate)
        proxy.start()
        oldenv = os.environ.copy()
        self.addCleanup(lambda: setattr(os, 'environ', oldenv))
        os.environ['https_proxy'] = proxy.address

        self.assertRaises(VirtError, self.run_once)
        self.assertIsNotNone(proxy.last_path, "Proxy was not called")
        self.assertEqual(proxy.last_path, 'localhost:443')

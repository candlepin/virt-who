from __future__ import print_function
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
import six
from six.moves import urllib
from mock import patch, call, ANY
from threading import Event
from six.moves.queue import Queue

from base import TestBase
from proxy import Proxy

from virtwho.virt.xen.xen import XenConfigSection
from virtwho.virt.xen.XenAPI import NewMaster, Failure
from virtwho.virt import Virt, VirtError, Guest, Hypervisor
from virtwho.datastore import Datastore
from virtwho import DefaultInterval


MY_SECTION_NAME = 'test-xen'

# Values used for testing XenConfigSection
XEN_SECTION_VALUES = {
    'type': 'xen',
    'server': 'https://10.0.0.101',
    'username': 'root',
    'password': 'secret_password',
    'env': '123456',
    'owner': '123456',
    'hypervisor_id': 'uuid',
    'is_hypervisor': 'true'
}


class TestXenConfigSection(TestBase):
    """
    Test base for testing class LibvirtdConfigSection
    """

    def __init__(self, *args, **kwargs):
        super(TestXenConfigSection, self).__init__(*args, **kwargs)
        self.xen_config = None

    def init_virt_config_section(self):
        """
        Method executed before each unit test
        """
        self.xen_config = XenConfigSection(MY_SECTION_NAME, None)
        # We need to set values using this way, because we need
        # to trigger __setitem__ of virt_config
        for key, value in XEN_SECTION_VALUES.items():
            self.xen_config[key] = value

    def test_validate_xen_section(self):
        """
        Test validation of xen section
        """
        self.init_virt_config_section()
        result = self.xen_config.validate()
        self.assertEqual(len(result), 0)

    def test_validate_xen_section_incomplete_server_url(self):
        """
        Test validation of xen section. Incomplete server URL (missing https://)
        """
        self.init_virt_config_section()
        self.xen_config['server'] = '10.0.0.101'
        result = self.xen_config.validate()
        expected_result = [
            (
                'info',
                'The original server URL was incomplete. It has been enhanced to https://10.0.0.101'
            )
        ]
        six.assertCountEqual(self, expected_result, result)

    def test_validate_xen_section_missing_username_password(self):
        """
        Test validation of xen section. Username and password is required.
        """
        self.init_virt_config_section()
        del self.xen_config['username']
        del self.xen_config['password']
        result = self.xen_config.validate()
        expected_result = [
            ('error', 'Required option: "username" not set.'),
            ('error', 'Required option: "password" not set.')
        ]
        six.assertCountEqual(self, expected_result, result)

    def test_validate_xen_section_unsupported_filters(self):
        """
        Test validation of xen section. Filters: filter_host_parents and exclude_host_parents
        are not supported on Xen mode. It is supported only on ESX mode.
        """
        self.init_virt_config_section()
        # Supported filter
        self.xen_config['filter_hosts'] = '*.company.com, *.company.net'
        self.xen_config['filter_type'] = 'wildcards'
        # Unsupported filters
        self.xen_config['filter_host_parents'] = 'host_parents'
        self.xen_config['exclude_host_parents'] = 'host_parents'
        result = self.xen_config.validate()
        expected_result = [
            ('warning', 'Ignoring unknown configuration option "filter_host_parents"'),
            ('warning', 'Ignoring unknown configuration option "exclude_host_parents"')
        ]
        six.assertCountEqual(self, expected_result, result)


class TestXen(TestBase):

    @staticmethod
    def create_config(name, wrapper, **kwargs):
        config = XenConfigSection(name, wrapper)
        config.update(**kwargs)
        config.validate()
        return config

    def setUp(self):
        config = self.create_config(name='test', wrapper=None, type='xen', server='localhost', username='username',
                        password='password', owner='owner', env='env')
        self.xen = Virt.from_config(self.logger, config, Datastore(), interval=DefaultInterval)

    def run_once(self, queue=None):
        """Run XEN in oneshot mode"""
        self.xen._oneshot = True
        self.xen.dest = queue or Queue()
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
        session.side_effect = urllib.error.URLError('timed out')
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
                    self.xen.CONFIG_TYPE,
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
                        self.xen.CONFIG_TYPE,
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

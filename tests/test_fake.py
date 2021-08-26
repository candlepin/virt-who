from __future__ import print_function
"""
Test of Fake virtualization backend.

Copyright (C) 2015 Radek Novacek <rnovacek@redhat.com>

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
import logging
from tempfile import mkdtemp
import shutil

from base import TestBase
from mock import Mock, ANY
from virtwho.config import DestinationToSourceMapper, init_config
from virtwho.virt import Virt, Hypervisor, StatusReport
from virtwho.virt.fakevirt import FakeVirt
from threading import Event
from six.moves.queue import Queue


HYPERVISOR_JSON = """
{
    "hypervisors": [
        {
            "hypervisorId": {
                "hypervisorId": "60527517-6284-7593-6AAB-75BF2A6375EF"
            },
            "guestIds": [
                {
                    "guestId": "07ED8178-95D5-4244-BC7D-582A54A48FF8",
                    "state": 1,
                    "attributes": {
                        "active": 1,
                        "virtWhoType": "hyperv"
                    }
                }
            ]
        }
    ]
}"""

NON_HYPERVISOR_JSON = """
{
    "hypervisors": [
        {
            "guestIds": [
                {
                    "guestId": "9f06a84d-5f56-4e7e-be0c-937b3c1924d7",
                    "state": 1,
                    "attributes": {
                        "active": 1,
                        "virtWhoType": "libvirt"
                    }
                }
            ]
        }
    ]
}
"""


class TestFakeRead(TestBase):
    def setUp(self):
        self.config_dir = mkdtemp()
        self.addCleanup(shutil.rmtree, self.config_dir)
        self.logger = logging.getLogger("virtwho.test")
        self.hypervisor_file = os.path.join(self.config_dir, "hypervisor.json")
        self.config_file = os.path.join(self.config_dir, "test.conf")

    def test_read_hypervisor(self):
        with open(self.hypervisor_file, "w") as f:
            f.write(HYPERVISOR_JSON)

        with open(self.config_file, "w") as f:
            f.write("""
[test]
type=fake
is_hypervisor=true
owner=taylor
file=%s
""" % self.hypervisor_file)
        effective_config = init_config({}, config_dir=self.config_dir)
        manager = DestinationToSourceMapper(effective_config)
        self.assertEqual(len(manager.configs), 1)
        virt = Virt.from_config(self.logger, manager.configs[0][1], None)
        self.assertEqual(type(virt), FakeVirt)
        mapping = virt.getHostGuestMapping()
        self.assertTrue("hypervisors" in mapping)
        hypervisors = mapping["hypervisors"]
        self.assertEqual(len(hypervisors), 1)
        hypervisor = hypervisors[0]
        self.assertEqual(type(hypervisor), Hypervisor)
        self.assertEqual(hypervisor.hypervisorId, "60527517-6284-7593-6AAB-75BF2A6375EF")
        self.assertEqual(len(hypervisor.guestIds), 1)
        guest = hypervisor.guestIds[0]
        self.assertEqual(guest.uuid, "07ED8178-95D5-4244-BC7D-582A54A48FF8")
        self.assertEqual(guest.state, 1)

    def test_read_hypervisor_from_non_hypervisor(self):
        with open(self.hypervisor_file, "w") as f:
            f.write(NON_HYPERVISOR_JSON)

        with open(self.config_file, "w") as f:
            f.write("""
[test]
type=fake
is_hypervisor=true
owner=covfefe
file=%s
""" % self.hypervisor_file)
        effective_config = init_config({}, config_dir=self.config_dir)
        DestinationToSourceMapper(effective_config)
        # The 'test' section is not valid here (as the json provided will not work with
        # the is_hypervisor value set to true)
        self.assertNotIn('test', effective_config)

    def test_read_non_hypervisor(self):
        with open(self.hypervisor_file, "w") as f:
            f.write(NON_HYPERVISOR_JSON)

        with open(self.config_file, "w") as f:
            f.write("""
[test]
type=fake
is_hypervisor=false
file=%s
""" % self.hypervisor_file)

        effective_config = init_config({}, config_dir=self.config_dir)
        manager = DestinationToSourceMapper(effective_config)
        self.assertEqual(len(manager.configs), 1)
        virt = Virt.from_config(self.logger, manager.configs[0][1], None)
        self.assertEqual(type(virt), FakeVirt)
        guests = virt.listDomains()
        self.assertEqual(len(guests), 1)
        guest = guests[0]
        self.assertEqual(guest.uuid, "9f06a84d-5f56-4e7e-be0c-937b3c1924d7")
        self.assertEqual(guest.state, 1)

    def test_read_non_hypervisor_from_hypervisor(self):
        with open(self.hypervisor_file, "w") as f:
            f.write(HYPERVISOR_JSON)

        with open(self.config_file, "w") as f:
            f.write("""
[test]
type=fake
is_hypervisor=false
file=%s
""" % self.hypervisor_file)

        effective_config = init_config({}, config_dir=self.config_dir)
        # This is an invalid case, the config section that is invalid should have been dropped
        self.assertNotIn('test', effective_config)

    def test_staus(self):
        with open(self.hypervisor_file, "w") as f:
            f.write(NON_HYPERVISOR_JSON)

        with open(self.config_file, "w") as f:
            f.write(f"""
[test]
type=fake
is_hypervisor=false
file={self.hypervisor_file}""")

        effective_config = init_config({}, config_dir=self.config_dir)
        manager = DestinationToSourceMapper(effective_config)
        self.assertEqual(len(manager.configs), 1)
        self.fake = Virt.from_config(self.logger, manager.configs[0][1], None)

        self.fake.status = True
        self.fake._send_data = Mock()
        self.run_once()

        self.fake._send_data.assert_called_once_with(data_to_send=ANY)
        self.assertTrue(isinstance(self.fake._send_data.mock_calls[0].kwargs['data_to_send'], StatusReport))
        self.assertEqual(self.fake._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['server'], None)

    def run_once(self, queue=None):
        """Run fake in oneshot mode"""
        self.fake._oneshot = True
        self.fake.dest = queue or Queue()
        self.fake._terminate_event = Event()
        self.fake._oneshot = True
        self.fake._interval = 0
        self.fake._run()

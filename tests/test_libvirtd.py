"""
Test for libvirt virtualization backend.

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

from threading import Event
from Queue import Queue
from base import TestBase
from mock import patch, ANY, Mock

from config import Config
from virt import Virt, VirtError


def raiseLibvirtError(*args, **kwargs):
    import libvirt
    raise libvirt.libvirtError('')


LIBVIRT_CAPABILITIES_XML = '<capabilities><host><name>this-my-name</name><uuid>this-is-uuid</uuid></host></capabilities>'
LIBVIRT_CAPABILITIES_NO_HOSTNAME_XML = '<capabilities><host><uuid>this-is-uuid</uuid></host></capabilities>'

class TestLibvirtd(TestBase):
    def setUp(self):
        pass

    def run_virt(self, config, in_queue=None):
        v = Virt.fromConfig(self.logger, config)
        v._queue = in_queue or Queue()
        v._terminate_event = Event()
        v._interval = 3600
        v._oneshot = True
        v._createEventLoop = Mock()
        v._run()

    @patch('libvirt.openReadOnly')
    def test_read(self, libvirt):
        config = Config('test', 'libvirt')
        libvirtd = Virt.fromConfig(self.logger, config)
        self.run_virt(config)
        libvirt.assert_called_with("")

    @patch('libvirt.openReadOnly')
    def test_read_fail(self, virt):
        config = Config('test', 'libvirt')
        virt.side_effect = raiseLibvirtError
        self.assertRaises(VirtError, self.run_virt, config)

    @patch('libvirt.openReadOnly')
    def test_remote_hostname(self, virt):
        config = Config('test', 'libvirt', server='server')
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config)
        virt.assert_called_with('qemu+ssh://server/system?no_tty=1')

    @patch('libvirt.openReadOnly')
    def test_remote_url(self, virt):
        config = Config('test', 'libvirt', server='abc://server/test')
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config)
        virt.assert_called_with('abc://server/test?no_tty=1')

    @patch('libvirt.openReadOnly')
    def test_remote_hostname_with_username(self, virt):
        config = Config('test', 'libvirt', server='server', username='user')
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config)
        virt.assert_called_with('qemu+ssh://user@server/system?no_tty=1')

    @patch('libvirt.openReadOnly')
    def test_remote_url_with_username(self, virt):
        config = Config('test', 'libvirt', server='abc://server/test',
                        username='user')
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config)
        virt.assert_called_with('abc://user@server/test?no_tty=1')

    @patch('libvirt.openAuth')
    def test_remote_hostname_with_username_and_password(self, virt):
        config = Config('test', 'libvirt', server='server',
                        username='user', password='pass')
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config)
        virt.assert_called_with('qemu+ssh://user@server/system?no_tty=1', ANY, ANY)

    @patch('libvirt.openAuth')
    def test_remote_url_with_username_and_password(self, virt):
        config = Config('test', 'libvirt', server='abc://server/test',
                        username='user', password='pass')
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config)
        virt.assert_called_with('abc://user@server/test?no_tty=1', ANY, ANY)

    @patch('libvirt.openReadOnly')
    def test_mapping_has_hostname_when_availible(self, virt):
        config = Config('test', 'libvirt', server='abc://server/test')
        queue = Queue()
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_XML
        self.run_virt(config, queue)
        result = queue.get(True)
        for host in result.association['hypervisors']:
            self.assertTrue(host.name is not None)

    @patch('libvirt.openReadOnly')
    def test_mapping_has_no_hostname_when_unavailible(self, virt):
        config = Config('test', 'libvirt', server='abc://server/test')
        queue = Queue()
        virt.return_value.getCapabilities.return_value = LIBVIRT_CAPABILITIES_NO_HOSTNAME_XML
        self.run_virt(config, queue)
        result = queue.get(True)
        for host in result.association['hypervisors']:
            self.assertTrue(host.name is None)

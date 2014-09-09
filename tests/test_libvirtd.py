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

import threading
from base import TestBase
from mock import patch, Mock
import logging

from config import Config
from virt import Virt, Domain, VirtError
from virt.libvirtd.libvirtd import LibvirtMonitor, VirEventLoopThread
import virt.libvirtd.libvirtd


def raiseLibvirtError(*args, **kwargs):
    import libvirt
    raise libvirt.libvirtError('')


class TestLibvirtd(TestBase):
    def setUp(self):
        pass

    @patch('libvirt.openReadOnly')
    def test_read(self, libvirt):
        config = Config('test', 'libvirt')
        libvirtd = Virt.fromConfig(self.logger, config)
        domains = libvirtd.listDomains()
        libvirt.assert_called_with("")

    @patch('libvirt.openReadOnly')
    def test_read_fail(self, virt):
        config = Config('test', 'libvirt')
        libvirtd = Virt.fromConfig(self.logger, config)
        virt.side_effect = raiseLibvirtError
        self.assertRaises(VirtError, libvirtd.listDomains)

    @patch('libvirt.openReadOnly')
    @patch('virt.libvirtd.libvirtd.VirEventLoopThread')
    def test_monitoring(self, thread, virt):
        event = threading.Event()
        LibvirtMonitor().set_event(event)
        LibvirtMonitor().check()

        thread.assert_called()

        virt.assert_called_with('')
        virt.return_value.domainEventRegister.assert_called()
        virt.return_value.setKeepAlive.assert_called()
        self.assertFalse(event.is_set())

        LibvirtMonitor()._callback()
        LibvirtMonitor().check()
        self.assertTrue(event.is_set())
        event.clear()

        LibvirtMonitor().check()
        self.assertFalse(event.is_set())
        event.clear()

        LibvirtMonitor()._callback()
        self.assertTrue(event.is_set())
        event.clear()

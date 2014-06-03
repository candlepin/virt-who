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
from base import unittest
from mock import patch, Mock
import logging

from config import Config
from virt import Virt, Domain, VirtError
from virt.libvirtd.libvirtd import LibvirtMonitor


def raiseLibvirtError(*args, **kwargs):
    import libvirt
    raise libvirt.libvirtError('')


class TestLibvirtd(unittest.TestCase):
    def setUp(self):
        pass

    @patch('libvirt.openReadOnly')
    def test_read(self, libvirt):
        logger = logging.getLogger()
        config = Config('test', 'libvirt')
        libvirtd = Virt.fromConfig(logger, config)
        domains = libvirtd.listDomains()
        libvirt.assert_called_with("")

    @patch('libvirt.openReadOnly')
    def test_read_fail(self, virt):
        logger = logging.getLogger()
        config = Config('test', 'libvirt')
        libvirtd = Virt.fromConfig(logger, config)
        virt.side_effect = raiseLibvirtError
        self.assertRaises(VirtError, libvirtd.listDomains)

    @patch('libvirt.openReadOnly')
    def test_monitoring(self, virt):
        event = threading.Event()
        LibvirtMonitor().set_event(event)
        LibvirtMonitor()._prepare()
        LibvirtMonitor()._checkChange()

        virt.assert_called_with('')
        virt.return_value.listDomainsID.assert_called()
        virt.return_value.listDefinedDomains.assert_called()
        virt.return_value.closed.assert_called()
        self.assertFalse(event.is_set())

        virt.return_value.listDomainsID.return_value = [1]
        LibvirtMonitor()._checkChange()
        self.assertTrue(event.is_set())
        event.clear()

        virt.return_value.listDomainsID.return_value = []
        LibvirtMonitor()._checkChange()
        self.assertTrue(event.is_set())
        event.clear()

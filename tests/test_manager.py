"""
Test of subscription managers.

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
import shutil
import tempfile
from mock import patch, MagicMock, ANY

from base import TestBase
from manager import Manager, ManagerError

from virt import Guest, Virt

import rhsm.config as rhsm_config
import rhsm.certificate
import rhsm.connection

import xmlrpclib


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestManager(TestBase):
    """ Test of all available subscription managers. """
    guest1 = Guest('9c927368-e888-43b4-9cdb-91b10431b258', xvirt, Guest.STATE_RUNNING, hypervisorType='QEMU')
    guest2 = Guest('d5ffceb5-f79d-41be-a4c1-204f836e144a', xvirt, Guest.STATE_SHUTOFF, hypervisorType='QEMU')
    guestInfo = [guest1]

    mapping = {
        '9c927368-e888-43b4-9cdb-91b10431b258': [],
        'ad58b739-5288-4cbc-a984-bd771612d670': [
            guest1,
            guest2
        ]
    }


class TestSubscriptionManager(TestManager):
    smType = "sam"

    def prepare(self, create_from_file, connection):
        self.options = MagicMock()
        self.options.smType = self.smType

        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)

        config_file = os.path.join(tempdir, "config")
        with open(config_file, "w") as f:
            f.write("[rhsm]\nconsumerCertDir=%s\n" % tempdir)

        cert_file = os.path.join(tempdir, "cert.pem")
        with open(cert_file, "w") as f:
            f.write("\n")

        rhsm_config.DEFAULT_CONFIG_PATH = config_file

        create_from_file.return_value.cert_uuid = {'CN': 'Test'}
        connection.return_value = MagicMock()

    @patch("rhsm.certificate.create_from_file")
    @patch("rhsm.connection.UEPConnection")
    def test_sendVirtGuests(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        manager = Manager.fromOptions(self.logger, self.options)
        manager.sendVirtGuests(self.guestInfo)
        manager.connection.updateConsumer.assert_called_with(
                ANY,
                guest_uuids=[guest.toDict() for guest in self.guestInfo])

    @patch("rhsm.certificate.create_from_file")
    @patch("rhsm.connection.UEPConnection")
    def test_hypervisorCheckIn(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        manager = Manager.fromOptions(self.logger, self.options)
        self.options.env = "ENV"
        self.options.owner = "OWNER"
        manager.hypervisorCheckIn(self.options, self.mapping)
        manager.connection.hypervisorCheckIn.assert_called_with(
                self.options.owner,
                self.options.env,
                dict((host, [guest.toDict() for guest in guests]) for host, guests in self.mapping.items()))


class TestSatellite(TestManager):
    smType = "satellite"

    def test_sendVirtGuests(self):
        options = MagicMock()
        options.smType = self.smType

        manager = Manager.fromOptions(self.logger, options)
        self.assertRaises(ManagerError, manager.sendVirtGuests, self.guestInfo)

    @patch("xmlrpclib.Server")
    def test_hypervisorCheckIn(self, server):
        options = MagicMock()
        options.smType = self.smType

        manager = Manager.fromOptions(self.logger, options)
        options.env = "ENV"
        options.owner = "OWNER"
        manager.hypervisorCheckIn(options, self.mapping, 'ABC')
        manager.server.registration.virt_notify.assert_called_with(ANY, [
            [0, "exists", "system", {"identity": "host", "uuid": "0000000000000000"}],
            [0, "crawl_began", "system", {}],
            [0, "exists", "domain", {
                "memory_size": 0,
                "name": "VM from ABC hypervisor ad58b739-5288-4cbc-a984-bd771612d670",
                "running": "running",
                "uuid": "9c927368e88843b49cdb91b10431b258",
                "vcpus": 1,
                "virt_type": "fully_virtualized"
            }],
            [0, "exists", "domain", {
                "memory_size": 0,
                "name": "VM from ABC hypervisor ad58b739-5288-4cbc-a984-bd771612d670",
                "running": "shutoff",
                "uuid": "d5ffceb5f79d41bea4c1204f836e144a",
                "vcpus": 1,
                "virt_type": "fully_virtualized"
            }],
            [0, "crawl_ended", "system", {}]
        ])

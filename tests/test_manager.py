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
import logging
import tempfile
import subprocess
from mock import patch, MagicMock, ANY

from base import TestBase
from config import Config
from manager import Manager, ManagerError

import rhsm.config as rhsm_config
import rhsm.certificate
import rhsm.connection

import xmlrpclib


class TestManager(TestBase):
    """ Test of all available subscription managers. """

    guestInfo = [
        {
            'guestId': '9c927368-e888-43b4-9cdb-91b10431b258',
            'attributes': {
                'hypervisorType': 'QEMU',
                'virtWhoType': 'libvirt',
                'active': 1
            }
        }
    ]

    mapping = {
        '9c927368-e888-43b4-9cdb-91b10431b258': [
            ''
        ],
        'ad58b739-5288-4cbc-a984-bd771612d670': [
            '2147647e-6f06-4ac0-982d-6902c259f9d6',
            'd5ffceb5-f79d-41be-a4c1-204f836e144a'
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
        manager.connection.updateConsumer.assert_called_with(ANY, guest_uuids=self.guestInfo)

    @patch("rhsm.certificate.create_from_file")
    @patch("rhsm.connection.UEPConnection")
    def test_hypervisorCheckIn(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        manager = Manager.fromOptions(self.logger, self.options)
        self.options.env = "ENV"
        self.options.owner = "OWNER"
        manager.hypervisorCheckIn(self.options, self.mapping)
        manager.connection.hypervisorCheckIn.assert_called_with(self.options.owner, self.options.env, self.mapping)


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
        manager.hypervisorCheckIn(options, self.mapping)
        manager.server.registration.virt_notify.assert_called_with(ANY, [
            [
                0, 'exists', 'system', {'uuid': '0000000000000000', 'identity': 'host'}
            ], [
                0, 'crawl_began', 'system', {}
            ], [
                0, 'exists', 'domain', {
                    'state': 'running',
                    'memory_size': 0,
                    'name': 'VM from None hypervisor ad58b739-5288-4cbc-a984-bd771612d670',
                    'virt_type': 'fully_virtualized',
                    'vcpus': 1,
                    'uuid': '2147647e6f064ac0982d6902c259f9d6'
                }
            ], [
                0, 'exists', 'domain', {
                    'state': 'running',
                    'memory_size': 0,
                    'name': 'VM from None hypervisor ad58b739-5288-4cbc-a984-bd771612d670',
                    'virt_type': 'fully_virtualized',
                    'vcpus': 1,
                    'uuid': 'd5ffceb5f79d41bea4c1204f836e144a'
                }
            ], [
                0, 'crawl_ended', 'system', {}
            ]
        ])


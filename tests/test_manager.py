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
from config import Config
from manager import Manager, ManagerError

from virt import Guest, Hypervisor, HostGuestAssociationReport, DomainListReport

import rhsm.config as rhsm_config


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestManager(TestBase):
    """ Test of all available subscription managers. """
    guest1 = Guest('9c927368-e888-43b4-9cdb-91b10431b258', xvirt, Guest.STATE_RUNNING)
    guest2 = Guest('d5ffceb5-f79d-41be-a4c1-204f836e144a', xvirt, Guest.STATE_SHUTOFF)
    guestInfo = [guest1]
    hypervisor_id = "HYPERVISOR_ID"

    config = Config('test', 'libvirt', owner='OWNER', env='ENV')
    host_guest_report = HostGuestAssociationReport(config, {
        'hypervisors': [
            Hypervisor('9c927368-e888-43b4-9cdb-91b10431b258', []),
            Hypervisor('ad58b739-5288-4cbc-a984-bd771612d670', [guest1, guest2])
        ]
    })
    domain_report = DomainListReport(config, [guest1], hypervisor_id)


class TestSubscriptionManager(TestManager):
    smType = "sam"

    def prepare(self, create_from_file, connection):
        self.options = MagicMock()

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
        connection.return_value.has_capability = MagicMock(return_value=False)

    @patch("rhsm.connection.UEPConnection")
    @patch("rhsm.certificate.create_from_file")
    def test_sendVirtGuests(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        config = Config('test', 'libvirt')
        config.smType = 'sam'
        manager = Manager.fromOptions(self.logger, self.options, config)
        manager.sendVirtGuests(self.domain_report, self.options)
        manager.connection.updateConsumer.assert_called_with(
            ANY,
            guest_uuids=[guest.toDict() for guest in self.guestInfo],
            hypervisor_id=self.hypervisor_id)

    @patch("rhsm.connection.UEPConnection")
    @patch("rhsm.certificate.create_from_file")
    def test_hypervisorCheckIn(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        config = Config('test', 'libvirt')
        config.smType = 'sam'
        manager = Manager.fromOptions(self.logger, self.options, config)
        self.options.env = "ENV"
        self.options.owner = "OWNER"
        manager.hypervisorCheckIn(self.host_guest_report, self.options)
        manager.connection.hypervisorCheckIn.assert_called_with(
            self.options.owner,
            self.options.env,
            dict(
                (
                    host.hypervisorId,
                    [
                        guest.toDict()
                        for guest in host.guestIds
                    ]
                )
                for host in self.host_guest_report.association['hypervisors']),
            options=self.options)


class TestSatellite(TestManager):
    smType = "satellite"

    def test_sendVirtGuests(self):
        options = MagicMock()
        config = Config('test', 'libvirt', sat_server='localhost')
        manager = Manager.fromOptions(self.logger, options, config)
        self.assertRaises(ManagerError, manager.sendVirtGuests, self.domain_report)

    @patch("xmlrpclib.ServerProxy")
    def test_hypervisorCheckIn(self, server):
        options = MagicMock()
        server.return_value.registration.new_system_user_pass.return_value = {
            'system_id': '123'
        }

        config = Config('test', 'libvirt', sat_server='localhost')
        manager = Manager.fromOptions(self.logger, options, config)
        options.env = "ENV"
        options.owner = "OWNER"
        manager.hypervisorCheckIn(self.host_guest_report, options)
        manager.server.registration.virt_notify.assert_called_with(ANY, [
            [0, "exists", "system", {"identity": "host", "uuid": "0000000000000000"}],
            [0, "crawl_began", "system", {}],
            [0, "exists", "domain", {
                "memory_size": 0,
                "name": "VM 9c927368-e888-43b4-9cdb-91b10431b258 from libvirt hypervisor ad58b739-5288-4cbc-a984-bd771612d670",
                "state": "running",
                "uuid": "9c927368e88843b49cdb91b10431b258",
                "vcpus": 1,
                "virt_type": "fully_virtualized"
            }],
            [0, "exists", "domain", {
                "memory_size": 0,
                "name": "VM d5ffceb5-f79d-41be-a4c1-204f836e144a from libvirt hypervisor ad58b739-5288-4cbc-a984-bd771612d670",
                "state": "shutoff",
                "uuid": "d5ffceb5f79d41bea4c1204f836e144a",
                "vcpus": 1,
                "virt_type": "fully_virtualized"
            }],
            [0, "crawl_ended", "system", {}]
        ])

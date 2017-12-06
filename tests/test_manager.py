from __future__ import print_function
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

from base import TestBase, unittest

from virtwho.config import VirtConfigSection
from virtwho.manager import Manager, ManagerError
from virtwho.virt import Guest, Hypervisor, HostGuestAssociationReport, DomainListReport

import rhsm.config as rhsm_config


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestManager(TestBase):
    """ Test of all available subscription managers. """
    guest1 = Guest('9c927368-e888-43b4-9cdb-91b10431b258', xvirt.CONFIG_TYPE, Guest.STATE_RUNNING)
    guest2 = Guest('d5ffceb5-f79d-41be-a4c1-204f836e144a', xvirt.CONFIG_TYPE, Guest.STATE_SHUTOFF)
    guestInfo = [guest1]
    hypervisor_id = "HYPERVISOR_ID"

    config = VirtConfigSection.from_dict({'type': 'libvirt', 'owner': 'OWNER', 'env': 'ENV'}, 'test', None)
    host_guest_report = HostGuestAssociationReport(config, {
        'hypervisors': [
            Hypervisor('9c927368-e888-43b4-9cdb-91b10431b258', []),
            Hypervisor('ad58b739-5288-4cbc-a984-bd771612d670', [guest1, guest2])
        ]
    })
    domain_report = DomainListReport(config, [guest1], hypervisor_id)


class TestSubscriptionManager(TestManager):
    smType = "sam"

    default_config_args = {
        'type': 'libvirt',
        'hypervisor_id': 'uuid',

    }

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
        connection.return_value.getConsumer = MagicMock(return_value={'environment': {'name': 'ENV'}})
        connection.return_value.getOwner = MagicMock(return_value={'key': 'OWNER'})

    @patch("rhsm.connection.UEPConnection")
    @patch("rhsm.certificate.create_from_file")
    def test_sendVirtGuests(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        config = VirtConfigSection.from_dict({'type': 'libvirt', 'sm_type': 'sam'}, 'test', None)
        manager = Manager.from_config(self.logger, config)
        manager.sendVirtGuests(self.domain_report, self.options)
        manager.connection.updateConsumer.assert_called_with(
            ANY,
            guest_uuids=[guest.toDict() for guest in self.guestInfo],
            hypervisor_id=self.hypervisor_id)

    @patch("rhsm.connection.UEPConnection")
    @patch("rhsm.certificate.create_from_file")
    def test_hypervisorCheckIn(self, create_from_file, connection):
        self.prepare(create_from_file, connection)
        config, d = self.create_fake_config('test', **self.default_config_args)
        d['env'] = 'ENV'
        d['owner'] = 'OWNER'
        manager = Manager.from_config(self.logger, config)
        # TODO additional mocking. Specifically, mock out the host_guest_report and config...
        self.host_guest_report._config = config
        manager.hypervisorCheckIn(self.host_guest_report)
        manager.connection.hypervisorCheckIn.assert_called_with(
            d['owner'],
            d['env'],
            dict(
                (
                    host.hypervisorId,
                    [
                        guest.toDict()
                        for guest in host.guestIds
                    ]
                )
                for host in self.host_guest_report.association['hypervisors']),
            options=ANY)


class TestSatellite(TestManager):
    smType = "satellite"

    default_config_args = {
        'type': 'libvirt',
        'sm_type': 'satellite',
        'hypervisor_id': 'uuid',
        'sat_server': 'localhost',
        'sat_username': 'username',
        'sat_password': 'password',
    }

    @unittest.skip("skip until config section for satellite is implemented")
    def test_sendVirtGuests(self):
        config = VirtConfigSection.from_dict({'type': 'libvirt', 'sat_server': 'localhost'}, 'test', None)
        manager = Manager.from_config(self.logger, config)
        self.assertRaises(ManagerError, manager.sendVirtGuests, self.domain_report)

    @patch("six.moves.xmlrpc_client.ServerProxy")
    def test_hypervisorCheckIn(self, server):
        options = MagicMock()
        server.return_value.registration.new_system_user_pass.return_value = {
            'system_id': '123'
        }
        config, d = self.create_fake_config('test', **self.default_config_args)
        manager = Manager.from_config(self.logger, config)
        self.host_guest_report._config = config
        manager.hypervisorCheckIn(self.host_guest_report, options)
        manager.server_xmlrpc.registration.virt_notify.assert_called_with(ANY, [
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

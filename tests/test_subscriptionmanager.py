import os

import shutil
import logging
import tempfile

from mock import patch, Mock, DEFAULT

from base import TestBase

from config import Config
from manager.subscriptionmanager import SubscriptionManager
from virt import Guest, Hypervisor

import rhsm.config
import rhsm.certificate
import rhsm.connection


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestSubscriptionManager(TestBase):
    guestList = [
        Guest('222', xvirt, Guest.STATE_RUNNING),
        Guest('111', xvirt, Guest.STATE_RUNNING),
        Guest('333', xvirt, Guest.STATE_RUNNING),
    ]
    mapping = {
        'hypervisors': [Hypervisor('123', guestList, name='TEST_HYPERVISOR')]
    }

    @classmethod
    @patch('rhsm.config.initConfig')
    @patch('rhsm.certificate.create_from_file')
    def setUpClass(cls, rhsmcert, rhsmconfig):
        super(TestSubscriptionManager, cls).setUpClass()
        config = Config('test', 'libvirt')
        cls.tempdir = tempfile.mkdtemp()
        with open(os.path.join(cls.tempdir, 'cert.pem'), 'w') as f:
            f.write("\n")

        rhsmcert.return_value.subject = {'CN': 123}
        rhsmconfig.return_value.get.side_effect = lambda group, key: {'consumerCertDir': cls.tempdir}.get(key, DEFAULT)
        cls.sm = SubscriptionManager(cls.logger, config)
        cls.sm.cert_uuid = 123

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tempdir)

    @patch('rhsm.connection.UEPConnection')
    def test_sendVirtGuests(self, rhsmconnection):
        self.sm.sendVirtGuests(self.guestList)
        self.sm.connection.updateConsumer.assert_called_with(123, guest_uuids=[g.toDict() for g in self.guestList])

    @patch('rhsm.connection.UEPConnection')
    def test_hypervisorCheckIn(self, rhsmconnection):
        owner = "owner"
        env = "env"
        config = Config("test", "esx", owner=owner, env=env)
        # Ensure the data takes the proper for for the old API
        rhsmconnection.return_value.has_capability.return_value = False
        self.sm.hypervisorCheckIn(config, self.mapping)

        self.sm.connection.hypervisorCheckIn.assert_called_with(
            owner,
            env,
            dict((host.hypervisorId, [g.toDict() for g in host.guestIds]) for host in self.mapping['hypervisors']), options=None)

    @patch('rhsm.connection.UEPConnection')
    def test_hypervisorCheckInAsync(self, rhsmconnection):
        owner = 'owner'
        env = 'env'
        config = Config("test", "esx", owner=owner, env=env)
        # Ensure we try out the new API
        rhsmconnection.return_value.has_capability.return_value = True
        self.sm.hypervisorCheckIn(config, self.mapping)
        expected = {'hypervisors': [h.toDict() for h in self.mapping['hypervisors']]}
        self.sm.connection.hypervisorCheckIn.assert_called_with(
            owner,
            env,
            expected,
            options=None
        )

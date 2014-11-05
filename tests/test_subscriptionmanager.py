import os

import shutil
import logging
import tempfile

from mock import patch, Mock, DEFAULT

from base import TestBase

from config import Config
from manager.subscriptionmanager import SubscriptionManager
from virt import Virt

import rhsm.config
import rhsm.certificate
import rhsm.connection


class TestSubscriptionManager(TestBase):
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

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tempdir)

    @patch('rhsm.connection.UEPConnection')
    def test_sendVirtGuestsList(self, rhsmconnection):
        guestList = ['222', '111', '333']
        self.sm.sendVirtGuests(guestList)
        self.sm.connection.updateConsumer.assert_called_with(123, guest_uuids=guestList)

    @patch('rhsm.connection.UEPConnection')
    def test_sendVirtGuestsDict(self, rhsmconnection):
        guestList = [
            {
                'guestId': '222',
                'attributes': {
                    'hypervisorType': 'qemu',
                    'virtWhoType': 'libvirt',
                    'active': 1
                }
            }, {
                'guestId': '111',
                'attributes': {
                    'hypervisorType': 'qemu',
                    'virtWhoType': 'libvirt',
                    'active': 1
                }
            }, {
                'guestId': '333',
                'attributes': {
                    'hypervisorType': 'qemu',
                    'virtWhoType': 'libvirt',
                    'active': 1
                }
            }
        ]
        self.sm.sendVirtGuests(guestList)
        self.sm.connection.updateConsumer.assert_called_with(123, guest_uuids=guestList)

    @patch('rhsm.connection.UEPConnection')
    def test_hypervisorCheckIn(self, rhsmconnection):
        owner = "owner"
        env = "env"
        config = Config("test", "esx", owner=owner, env=env)
        mapping = {'ABC': ['222', '111', '333'], 'BCD': []}
        self.sm.hypervisorCheckIn(config, mapping)
        self.sm.connection.hypervisorCheckIn.assert_called_with(owner, env, mapping)

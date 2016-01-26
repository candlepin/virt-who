import os
import sys
import shutil
import logging
import tempfile

from mock import patch, Mock, DEFAULT

from base import TestBase

from config import Config, ConfigManager
from manager import Manager
from manager.subscriptionmanager import SubscriptionManager
from virt import Guest, Hypervisor, HostGuestAssociationReport, DomainListReport
from virtwho import parseOptions

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
        config = Config('test', 'libvirt')
        report = DomainListReport(config, self.guestList)
        self.sm.sendVirtGuests(report)
        self.sm.connection.updateConsumer.assert_called_with(123, guest_uuids=[g.toDict() for g in self.guestList])

    @patch('rhsm.connection.UEPConnection')
    def test_hypervisorCheckIn(self, rhsmconnection):
        owner = "owner"
        env = "env"
        config = Config("test", "esx", owner=owner, env=env)
        # Ensure the data takes the proper for for the old API
        rhsmconnection.return_value.has_capability.return_value = False
        report = HostGuestAssociationReport(config, self.mapping)
        self.sm.hypervisorCheckIn(report)

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
        report = HostGuestAssociationReport(config, self.mapping)
        self.sm.hypervisorCheckIn(report)
        expected = {'hypervisors': [h.toDict() for h in self.mapping['hypervisors']]}
        self.sm.connection.hypervisorCheckIn.assert_called_with(
            owner,
            env,
            expected,
            options=None
        )


class TestSubscriptionManagerConfig(TestBase):
    def test_sm_config_env(self):
        os.environ = {
            "VIRTWHO_SAM": '1',
            "VIRTWHO_LIBVIRT": '1'
        }
        sys.argv = ["virt-who"]
        logger, options = parseOptions()
        config = Config("env/cmdline", options.virtType, defaults={}, **options)
        config.checkOptions(logger)
        manager = Manager.fromOptions(logger, options, config)
        self.assertTrue(isinstance(manager, SubscriptionManager))

    def test_sm_config_cmd(self):
        os.environ = {}
        sys.argv = ["virt-who", "--sam", "--libvirt"]
        logger, options = parseOptions()
        config = Config("env/cmdline", options.virtType, defaults={}, **options)
        config.checkOptions(logger)
        manager = Manager.fromOptions(logger, options, config)
        self.assertTrue(isinstance(manager, SubscriptionManager))

    def test_sm_config_file(self):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=libvirt
rhsm_hostname=host
""")

        config_manager = ConfigManager(self.logger, config_dir)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0]
        manager = Manager.fromOptions(self.logger, Mock(), config)
        self.assertTrue(isinstance(manager, SubscriptionManager))
        self.assertEqual(config.rhsm_hostname, 'host')

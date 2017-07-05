import os
import sys
import shutil
import tempfile

from mock import patch, Mock, DEFAULT, MagicMock, ANY

from base import TestBase, unittest

from virtwho.config import Config, ConfigManager, VIRTWHO_ENV_CLI_SECTION_NAME
from virtwho.manager import Manager
from virtwho.manager.subscriptionmanager import SubscriptionManager
from virtwho.virt import Guest, Hypervisor, HostGuestAssociationReport, DomainListReport, AbstractVirtReport
from virtwho.parser import parse_options


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
    hypervisor_id = "HYPERVISOR_ID"

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
        report = DomainListReport(config, self.guestList, self.hypervisor_id)
        self.sm.sendVirtGuests(report)
        self.sm.connection.updateConsumer.assert_called_with(
            123,
            guest_uuids=[g.toDict() for g in self.guestList],
            hypervisor_id=self.hypervisor_id)

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

    @patch('rhsm.connection.UEPConnection')
    def test_job_status(self, rhsmconnection):
        rhsmconnection.return_value.has_capability.return_value = True
        config = Config("test", "esx", owner='owner', env='env')
        report = HostGuestAssociationReport(config, self.mapping)
        self.sm.hypervisorCheckIn(report)
        rhsmconnection.return_value.getJob.return_value = {
            'state': 'RUNNING',
        }
        self.sm.check_report_state(report)
        self.assertEqual(report.state, AbstractVirtReport.STATE_PROCESSING)

        def host(host):
            return {
                'uuid': host
            }
        rhsmconnection.return_value.getJob.return_value = {
            'state': 'FINISHED',
            'resultData': {
                'failedUpdate': ["failed"],
                'updated': [
                    host('123')
                ],
                'created': [
                    host('456')
                ],
                'unchanged': [
                    host('789')
                ]
            }
        }
        self.sm.logger = MagicMock()
        self.sm.check_report_state(report)
        # calls: authenticating + checking job status + 1 line about the number of unchanged
        self.assertEqual(self.sm.logger.debug.call_count, 3)
        self.assertEqual(report.state, AbstractVirtReport.STATE_FINISHED)


class TestSubscriptionManagerConfig(TestBase):
    def test_sm_config_env(self):
        os.environ = {
            "VIRTWHO_SAM": '1',
            "VIRTWHO_LIBVIRT": '1'
        }
        sys.argv = ["virt-who"]
        logger, options = parse_options()
        env_cli_section = options.get_section(VIRTWHO_ENV_CLI_SECTION_NAME)
        config = Config("env/cmdline", env_cli_section['virttype'], defaults={}, **env_cli_section)
        config.checkOptions(logger)
        manager = Manager.fromOptions(logger, options, config)
        self.assertTrue(isinstance(manager, SubscriptionManager))

    def test_sm_config_cmd(self):
        os.environ = {}
        sys.argv = ["virt-who", "--sam", "--libvirt"]
        logger, options = parse_options()
        env_cli_section = options.get_section(VIRTWHO_ENV_CLI_SECTION_NAME)
        config = Config("env/cmdline", env_cli_section['virttype'], defaults={}, **env_cli_section)
        config.checkOptions(logger)
        manager = Manager.fromOptions(logger, options, config)
        self.assertTrue(isinstance(manager, SubscriptionManager))

    @patch('rhsm.connection.UEPConnection')
    def test_sm_config_file(self, rhsmconnection):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=libvirt
rhsm_hostname=host
rhsm_port=8080
rhsm_prefix=prefix
rhsm_proxy_hostname=proxy_host
rhsm_proxy_port=9090
rhsm_proxy_user=proxy_user
rhsm_proxy_password=proxy_password
rhsm_insecure=1
rhsm_username=user
rhsm_password=passwd
""")

        config_manager = ConfigManager(self.logger, config_dir)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0]
        manager = Manager.fromOptions(self.logger, Mock(), config)
        self.assertTrue(isinstance(manager, SubscriptionManager))
        self.assertEqual(config.rhsm_hostname, 'host')
        self.assertEqual(config.rhsm_port, '8080')

        manager._connect(config)
        rhsmconnection.assert_called_with(
            username='user',
            password='passwd',
            host='host',
            ssl_port=8080,
            handler='prefix',
            proxy_hostname='proxy_host',
            proxy_port='9090',
            proxy_user='proxy_user',
            proxy_password='proxy_password',
            insecure='1')

    @unittest.skip("skip until rhsm is fixed")
    @patch('rhsm.connection.RhsmProxyHTTPSConnection')
    @patch('M2Crypto.httpslib.HTTPSConnection')
    @patch('rhsm.config.initConfig')
    def test_sm_config_override(self, initConfig, HTTPSConnection, RhsmProxyHTTPSConnection):
        '''Test if overriding options from rhsm.conf works.'''

        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.read.return_value = '{"result": "ok"}'
        HTTPSConnection.return_value = conn
        RhsmProxyHTTPSConnection.return_value = conn

        def config_get(section, key):
            return {
                'server/proxy_hostname': 'proxy.server.test',
                'rhsm/consumerCertDir': '',
                'server/hostname': 'server.test',
                'server/port': '8081',
                'server/prefix': 'old_prefix',
            }.get('%s/%s' % (section, key), None)
        initConfig.return_value.get.side_effect = config_get
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=libvirt
rhsm_hostname=host
rhsm_port=8080
rhsm_prefix=/prefix
rhsm_proxy_hostname=
rhsm_proxy_port=8443
rhsm_insecure=1
rhsm_username=user
rhsm_password=passwd
""")

        config_manager = ConfigManager(self.logger, config_dir)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0]
        manager = Manager.fromOptions(self.logger, Mock(), config)
        self.assertTrue(isinstance(manager, SubscriptionManager))
        self.assertEqual(config.rhsm_hostname, 'host')
        self.assertEqual(config.rhsm_port, '8080')

        manager._connect(config)
        self.assertFalse(RhsmProxyHTTPSConnection.called, "It shouldn't use proxy")
        self.assertTrue(HTTPSConnection.called)
        conn.request.assert_called_with(
            'GET',
            '/prefix/status/',
            body=ANY,
            headers=ANY)

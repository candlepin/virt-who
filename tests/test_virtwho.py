"""
Test for basic virt-who operations.

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

import sys
import os
from Queue import Empty, Queue
from mock import patch, Mock, sentinel, ANY, call

from base import TestBase

from virtwho import util
from virtwho.config import Config
from virtwho.manager import ManagerThrottleError, ManagerFatalError
from virtwho.virt import (
    HostGuestAssociationReport, Hypervisor, Guest,
    DomainListReport, AbstractVirtReport)
from virtwho.parser import parseOptions, OptionError
from virtwho.executor import Executor, ReloadRequest
from virtwho.main import _main


class TestOptions(TestBase):
    NO_GENERAL_CONF = {'global': {}}

    def setUp(self):
        self.clearEnv()

    def clearEnv(self):
        for key in os.environ.keys():
            if key.startswith("VIRTWHO"):
                del os.environ[key]

    def setUpParseFile(self, parseFileMock):
        parseFileMock.return_value = TestOptions.NO_GENERAL_CONF

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_default_cmdline_options(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py"]
        _, options = parseOptions()
        self.assertFalse(options.debug)
        self.assertFalse(options.background)
        self.assertFalse(options.oneshot)
        self.assertEqual(options.interval, 3600)
        self.assertEqual(options.smType, 'sam')
        self.assertEqual(options.virtType, None)
        self.assertEqual(options.reporter_id, util.generateReporterId())

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_minimum_interval_options(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py", "--interval=5"]
        _, options = parseOptions()
        self.assertEqual(options.interval, 60)

        sys.argv = ["virtwho.py"]
        os.environ["VIRTWHO_INTERVAL"] = '1'

        _, options = parseOptions()
        self.assertEqual(options.interval, 60)

        self.clearEnv()
        bad_conf = {'global': {'interval': 1}}
        parseFile.return_value = bad_conf

        _, options = parseOptions()
        self.assertEqual(options.interval, 60)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_options_hierarchy_for_reporter_id(self, parseFile, getLogger):
        # Set the value in all three possible locations
        # Mock /etc/virt-who.conf file
        global_conf_dict = {
            'global': {
                'reporter_id': "/etc/virt-who.conf"
            }
        }
        parseFile.return_value = global_conf_dict
        # cli option
        sys.argv = ["virtwho.py", "--reporter-id=cli"]
        # environment var
        os.environ["VIRTWHO_REPORTER_ID"] = "env"
        _, options = parseOptions()
        # cli option should beat environment vars and virt-who.conf
        self.assertEqual(options.reporter_id, "cli")

        sys.argv = ["virtwho.py"]

        _, options = parseOptions()
        self.assertEqual(options.reporter_id, "env")

        self.clearEnv()

        _, options = parseOptions()
        self.assertEqual(options.reporter_id, "/etc/virt-who.conf")

        parseFile.return_value = {'global': {}}

        _, options = parseOptions()
        self.assertEqual(options.reporter_id, util.generateReporterId())

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_options_debug(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py", "-d"]
        _, options = parseOptions()
        self.assertTrue(options.debug)

        sys.argv = ["virtwho.py"]
        os.environ["VIRTWHO_DEBUG"] = "1"
        _, options = parseOptions()
        self.assertTrue(options.debug)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_options_virt(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        for virt in ['esx', 'hyperv', 'rhevm']:
            self.clearEnv()
            sys.argv = ["virtwho.py", "--%s" % virt, "--%s-owner=owner" % virt,
                        "--%s-env=env" % virt, "--%s-server=localhost" % virt,
                        "--%s-username=username" % virt,
                        "--%s-password=password" % virt]
            _, options = parseOptions()
            self.assertEqual(options.virtType, virt)
            self.assertEqual(options.owner, 'owner')
            self.assertEqual(options.env, 'env')
            self.assertEqual(options.server, 'localhost')
            self.assertEqual(options.username, 'username')
            self.assertEqual(options.password, 'password')

            sys.argv = ["virtwho.py"]
            virt_up = virt.upper()
            os.environ["VIRTWHO_%s" % virt_up] = "1"
            os.environ["VIRTWHO_%s_OWNER" % virt_up] = "xowner"
            os.environ["VIRTWHO_%s_ENV" % virt_up] = "xenv"
            os.environ["VIRTWHO_%s_SERVER" % virt_up] = "xlocalhost"
            os.environ["VIRTWHO_%s_USERNAME" % virt_up] = "xusername"
            os.environ["VIRTWHO_%s_PASSWORD" % virt_up] = "xpassword"
            _, options = parseOptions()
            self.assertEqual(options.virtType, virt)
            self.assertEqual(options.owner, 'xowner')
            self.assertEqual(options.env, 'xenv')
            self.assertEqual(options.server, 'xlocalhost')
            self.assertEqual(options.username, 'xusername')
            self.assertEqual(options.password, 'xpassword')

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_options_virt_satellite(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        for virt in ['esx', 'hyperv', 'rhevm']:
            self.clearEnv()
            sys.argv = ["virtwho.py",
                        "--satellite",
                        "--satellite-server=localhost",
                        "--satellite-username=username",
                        "--satellite-password=password",
                        "--%s" % virt,
                        "--%s-server=localhost" % virt,
                        "--%s-username=username" % virt,
                        "--%s-password=password" % virt]
            _, options = parseOptions()
            self.assertEqual(options.virtType, virt)
            self.assertEqual(options.owner, '')
            self.assertEqual(options.env, '')
            self.assertEqual(options.server, 'localhost')
            self.assertEqual(options.username, 'username')
            self.assertEqual(options.password, 'password')

            sys.argv = ["virtwho.py"]
            virt_up = virt.upper()
            os.environ["VIRTWHO_SATELLITE"] = "1"
            os.environ["VIRTWHO_SATELLITE_SERVER"] = "xlocalhost"
            os.environ["VIRTWHO_SATELLITE_USERNAME"] = "xusername"
            os.environ["VIRTWHO_SATELLITE_PASSWORD"] = "xpassword"
            os.environ["VIRTWHO_%s" % virt_up] = "1"
            os.environ["VIRTWHO_%s_SERVER" % virt_up] = "xlocalhost"
            os.environ["VIRTWHO_%s_USERNAME" % virt_up] = "xusername"
            os.environ["VIRTWHO_%s_PASSWORD" % virt_up] = "xpassword"
            _, options = parseOptions()
            self.assertEqual(options.virtType, virt)
            self.assertEqual(options.owner, '')
            self.assertEqual(options.env, '')
            self.assertEqual(options.server, 'xlocalhost')
            self.assertEqual(options.username, 'xusername')
            self.assertEqual(options.password, 'xpassword')

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parseFile')
    def test_missing_option(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        for smType in ['satellite', 'sam']:
            for virt in ['libvirt', 'vdsm', 'esx', 'hyperv', 'rhevm']:
                for missing in ['server', 'username', 'password', 'env', 'owner']:
                    self.clearEnv()
                    sys.argv = ["virtwho.py", "--%s" % virt]
                    if virt in ['libvirt', 'esx', 'hyperv', 'rhevm']:
                        if missing != 'server':
                            sys.argv.append("--%s-server=localhost" % virt)
                        if missing != 'username':
                            sys.argv.append("--%s-username=username" % virt)
                        if missing != 'password':
                            sys.argv.append("--%s-password=password" % virt)
                        if missing != 'env':
                            sys.argv.append("--%s-env=env" % virt)
                        if missing != 'owner':
                            sys.argv.append("--%s-owner=owner" % virt)

                    if virt not in ('libvirt', 'vdsm') and missing != 'password':
                        if smType == 'satellite' and missing in ['env', 'owner']:
                            continue
                        self.assertRaises(OptionError, parseOptions)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.virt.Virt.fromConfig')
    @patch('virtwho.manager.Manager.fromOptions')
    @patch('virtwho.config.parseFile')
    def test_sending_guests(self, parseFile, fromOptions, fromConfig, getLogger):
        self.setUpParseFile(parseFile)
        options = Mock()
        options.oneshot = True
        options.interval = 0
        options.print_ = False
        fake_virt = Mock()
        fake_virt.CONFIG_TYPE = 'esx'
        test_hypervisor = Hypervisor('test', guestIds=[Guest('guest1', fake_virt, 1)])
        association = {'hypervisors': [test_hypervisor]}
        options.log_dir = ''
        options.log_file = ''
        getLogger.return_value = sentinel.logger
        fromConfig.return_value.config.name = 'test'
        virtwho = Executor(self.logger, options, config_dir="/nonexistant")
        config = Config("test", "esx", server="localhost", username="username",
                        password="password", owner="owner", env="env")
        virtwho.configManager.addConfig(config)
        virtwho.queue = Queue()
        virtwho.queue.put(HostGuestAssociationReport(config, association))
        virtwho.run()

        fromConfig.assert_called_with(sentinel.logger, config)
        self.assertTrue(fromConfig.return_value.start.called)
        fromOptions.assert_called_with(self.logger, options, ANY)


class TestSend(TestBase):
    def setUp(self):
        self.config = Config('config', 'esx', server='localhost',
                             username='username', password='password',
                             owner='owner', env='env', log_dir='', log_file='')
        self.second_config = Config('second_config', 'esx', server='localhost',
                                    username='username', password='password',
                                    owner='owner', env='env', log_dir='',
                                    log_file='')
        fake_virt = Mock()
        fake_virt.CONFIG_TYPE = 'esx'
        guests = [Guest('guest1', fake_virt, 1)]
        test_hypervisor = Hypervisor('test', guestIds=[Guest('guest1', fake_virt, 1)])
        assoc = {'hypervisors': [test_hypervisor]}
        self.fake_domain_list = DomainListReport(self.second_config, guests)
        self.fake_report = HostGuestAssociationReport(self.config, assoc)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.manager.Manager.fromOptions')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_report_hash_added_after_send(self, fromConfig, fromOptions, getLogger):
        # Side effect for fromConfig
        def fake_virts(logger, config):
            new_fake_virt = Mock()
            new_fake_virt.config.name = config.name
            return new_fake_virt

        fromConfig.side_effect = fake_virts
        options = Mock()
        options.interval = 0
        options.oneshot = True
        options.print_ = False
        options.log_file = ''
        options.log_dir = ''
        virtwho = Executor(self.logger, options, config_dir="/nonexistant")

        def send(report):
            report.state = AbstractVirtReport.STATE_FINISHED
            return True
        virtwho.send = Mock(side_effect=send)
        queue = Queue()
        virtwho.queue = queue
        virtwho.retry_after = 1
        virtwho.configManager.addConfig(self.config)
        virtwho.configManager.addConfig(self.second_config)
        queue.put(self.fake_report)
        queue.put(self.fake_domain_list)
        virtwho.run()

        self.assertEquals(virtwho.send.call_count, 2)
        self.assertEqual(virtwho.last_reports_hash[self.config.name], self.fake_report.hash)
        self.assertEqual(virtwho.last_reports_hash[self.second_config.name], self.fake_domain_list.hash)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.manager.Manager.fromOptions')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_same_report_filtering(self, fromConfig, fromOptions, getLogger):
        def fake_virts(logger, config):
            new_fake_virt = Mock()
            new_fake_virt.config.name = config.name
            return new_fake_virt

        fromConfig.side_effect = fake_virts
        options = Mock()
        options.interval = 0
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = Executor(self.logger, options, config_dir="/nonexistant")

        queue = Queue()
        # Create another report with same hash
        report2 = HostGuestAssociationReport(self.config, self.fake_report.association)
        self.assertEqual(self.fake_report.hash, report2.hash)

        def send(report):
            report.state = AbstractVirtReport.STATE_FINISHED
            # Put second report when the first is done
            queue.put(report2)
            return True
        virtwho.send = Mock(side_effect=send)
        virtwho.queue = queue
        virtwho.retry_after = 1
        virtwho.configManager.addConfig(self.config)
        queue.put(self.fake_report)
        virtwho.run()

        self.assertEquals(virtwho.send.call_count, 1)

    @patch('time.time')
    @patch('virtwho.log.getLogger')
    @patch('virtwho.manager.Manager.fromOptions')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_send_current_report(self, fromConfig, fromOptions, getLogger, time):
        initial = 10
        time.side_effect = [initial, initial]

        fromOptions.return_value = Mock()
        options = Mock()
        options.interval = 6
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = Executor(Mock(), options, config_dir="/nonexistant")
        virtwho.oneshot_remaining = ['config_name']

        config = Mock()
        config.hash = "config_hash"
        config.name = "config_name"

        virtwho.send = Mock()
        virtwho.send.return_value = True
        report = HostGuestAssociationReport(config, {'hypervisors': {}})
        report.state = AbstractVirtReport.STATE_PROCESSING
        virtwho.queued_reports[config.name] = report

        virtwho.send_current_report()

        def check_report_state(report):
            report.state = AbstractVirtReport.STATE_FINISHED
        virtwho.check_report_state = Mock(side_effect=check_report_state)
        virtwho.check_reports_state()

        virtwho.send.assert_called_with(report)
        self.assertEquals(virtwho.send_after, initial + options.interval)

    @patch('time.time')
    @patch('virtwho.log.getLogger')
    @patch('virtwho.manager.Manager.fromOptions')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_send_current_report_with_429(self, fromConfig, fromOptions, getLogger, time):
        initial = 10
        retry_after = 2
        time.return_value = initial

        fromOptions.return_value = Mock()
        options = Mock()
        options.interval = 6
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = Executor(Mock(), options, config_dir="/nonexistant")

        config = Mock()
        config.hash = "config_hash"
        config.name = "config_name"

        report = HostGuestAssociationReport(config, {'hypervisors': []})
        report.state = AbstractVirtReport.STATE_PROCESSING
        virtwho.queued_reports[config.name] = report

        virtwho.send = Mock()
        virtwho.send.return_value = False
        virtwho.send.side_effect = ManagerThrottleError(retry_after)

        virtwho.send_current_report()

        virtwho.send.assert_called_with(report)
        self.assertEquals(virtwho.send_after, initial + 60)
        self.assertEquals(len(virtwho.queued_reports), 1)

        retry_after = 120
        virtwho.send.side_effect = ManagerThrottleError(retry_after)
        virtwho.send_current_report()
        virtwho.send.assert_called_with(report)
        self.assertEquals(virtwho.send_after, initial + retry_after * 2)
        self.assertEquals(len(virtwho.queued_reports), 1)

        def finish(x):
            report.state = AbstractVirtReport.STATE_FINISHED
            return True
        virtwho.send.side_effect = finish
        virtwho.send_current_report()
        retry_after = 60
        self.assertEquals(virtwho.retry_after, retry_after)
        self.assertEquals(virtwho.send_after, initial + options.interval)
        self.assertEquals(len(virtwho.queued_reports), 0)


class TestReload(TestBase):
    def mock_virtwho(self):
        options = Mock()
        options.interval = 6
        options.oneshot = False
        options.print_ = False
        virtwho = Executor(Mock(), options, config_dir="/nonexistant")
        config = Config("env/cmdline", 'libvirt')
        virtwho.configManager.addConfig(config)
        virtwho.queue = Mock()
        virtwho.send = Mock()
        return virtwho

    def assertStartStop(self, fromConfig):
        ''' Make sure that Virt was started and stopped. '''
        self.assertTrue(fromConfig.return_value.start.called)
        self.assertTrue(fromConfig.return_value.stop.called)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_start_unregistered(self, fromConfig, getLogger):
        virtwho = self.mock_virtwho()
        virtwho.queue.get.side_effect = [DomainListReport(virtwho.configManager.configs[0], []), Empty, 'reload']
        virtwho.send.side_effect = ManagerFatalError
        # When not registered, it should throw ReloadRequest
        self.assertRaises(ReloadRequest, _main, virtwho)
        # queue.get should be called 3 times: report, nonblocking reading
        # of remaining reports and after ManagerFatalError wait indefinately
        self.assertEqual(virtwho.queue.get.call_count, 3)
        # It should wait blocking for the reload
        virtwho.queue.get.assert_has_calls([call(block=True)])
        self.assertStartStop(fromConfig)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_exit_after_unregister(self, fromConfig, getLogger):
        virtwho = self.mock_virtwho()
        report = DomainListReport(virtwho.configManager.configs[0], [])
        # Send two reports and then 'exit'
        virtwho.queue.get.side_effect = [report, Empty, report, Empty, 'exit']
        # First report will be successful, second one will throw ManagerFatalError
        virtwho.send.side_effect = [True, ManagerFatalError]
        # _main should exit normally
        _main(virtwho)
        self.assertStartStop(fromConfig)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_reload_after_unregister(self, fromConfig, getLogger):
        virtwho = self.mock_virtwho()
        report = DomainListReport(virtwho.configManager.configs[0], [])
        # Send two reports and then 'reload'
        virtwho.queue.get.side_effect = [report, Empty, report, Empty, 'reload']
        # First report will be successful, second one will throw ManagerFatalError
        virtwho.send.side_effect = [True, ManagerFatalError]
        # _main should throw ReloadRequest
        self.assertRaises(ReloadRequest, _main, virtwho)
        self.assertStartStop(fromConfig)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.virt.Virt.fromConfig')
    def test_reload_after_register(self, fromConfig, getLogger):
        virtwho = self.mock_virtwho()
        report = DomainListReport(virtwho.configManager.configs[0], [])
        # Send report and then 'reload'
        virtwho.queue.get.side_effect = [report, Empty, 'reload']
        # First report will be successful, second one will throw ManagerFatalError
        virtwho.send.side_effect = [ManagerFatalError, True]
        # _main should throw ReloadRequest
        self.assertRaises(ReloadRequest, _main, virtwho)

        self.assertEqual(virtwho.queue.get.call_count, 3)
        # It should wait blocking for the reload
        virtwho.queue.get.assert_has_calls([call(block=True)])
        self.assertStartStop(fromConfig)

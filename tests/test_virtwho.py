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
from base import TestBase, unittest
import logging
from rhsm.connection import RestlibException

from mock import patch, Mock, sentinel, ANY

from virtwho import parseOptions, VirtWho, OptionError, Queue, Job
from config import Config
import util
from virt import HostGuestAssociationReport, Hypervisor, Guest, DomainListReport
from multiprocessing import Queue


class TestOptions(TestBase):
    NO_GENERAL_CONF = {'global':{}}

    def setUp(self):
        self.clearEnv()

    def clearEnv(self):
        for key in os.environ.keys():
            if key.startswith("VIRTWHO"):
                del os.environ[key]

    def setUpParseFile(self, parseFileMock):
        parseFileMock.return_value = TestOptions.NO_GENERAL_CONF

    @patch('log.getLogger')
    @patch('config.parseFile')
    def test_default_cmdline_options(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py"]
        _, options = parseOptions()
        self.assertFalse(options.debug)
        self.assertFalse(options.background)
        self.assertFalse(options.oneshot)
        self.assertEqual(options.interval, 60)
        self.assertEqual(options.smType, 'sam')
        self.assertEqual(options.virtType, None)
        self.assertEqual(options.reporter_id, util.generateReporterId())

    @patch('log.getLogger')
    @patch('config.parseFile')
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

    @patch('log.getLogger')
    @patch('config.parseFile')
    def test_options_hierarchy_for_reporter_id(self, parseFile, getLogger):
        # Set the value in all three possible locations
        # Mock /etc/virt-who.conf file
        global_conf_dict = {
            'global':{
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

        parseFile.return_value = {'global':{}}

        _, options = parseOptions()
        self.assertEqual(options.reporter_id, util.generateReporterId())

    @patch('log.getLogger')
    @patch('config.parseFile')
    def test_options_debug(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py", "-d"]
        _, options = parseOptions()
        self.assertTrue(options.debug)

        sys.argv = ["virtwho.py"]
        os.environ["VIRTWHO_DEBUG"] = "1"
        _, options = parseOptions()
        self.assertTrue(options.debug)

    @patch('log.getLogger')
    @patch('config.parseFile')
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

    @patch('log.getLogger')
    @patch('config.parseFile')
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

    @patch('log.getLogger')
    @patch('config.parseFile')
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
                        print(smType, virt, missing)
                        self.assertRaises(OptionError, parseOptions)

    @patch('log.getLogger')
    @patch('virt.Virt.fromConfig')
    @patch('manager.Manager.fromOptions')
    @patch('config.parseFile')
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
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        config = Config("test", "esx", server="localhost", username="username",
                        password="password", owner="owner", env="env")
        virtwho.configManager.addConfig(config)
        virtwho.queue = Queue()
        virtwho.queue.put(HostGuestAssociationReport(config, association))
        virtwho.run()

        fromConfig.assert_called_with(sentinel.logger, config)
        self.assertTrue(fromConfig.return_value.start.called)
        fromOptions.assert_called_with(self.logger, options, ANY)


class TestJobs(TestBase):
    def setupVirtWho(self, oneshot=True):
        options = Mock()
        options.oneshot = oneshot
        options.interval = 0
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        config = Config("test", "esx", server="localhost", username="username",
                        password="password", owner="owner", env="env")
        virtwho.configManager.addConfig(config)
        return virtwho

    @patch('log.getLogger')
    def test_adding_job(self, getLogger):
        virtwho = self.setupVirtWho()
        # Mock out a method we want to call
        virtwho.send = Mock()
        fake_report = 'fake_report'
        # Add an actual job to be executed immediately
        test_job = Job('send', [fake_report])
        virtwho.addJob(test_job)
        virtwho.run()
        virtwho.send.assert_called_with(fake_report)

    @patch('log.getLogger')
    def test_adding_tuple_of_job(self, getLogger):
        # We should be able to pass in tuples like below and achieve the same
        # result as if we passed in a Job object

        # (target, [args], executeInSeconds, executeAfter)
        fake_report = 'fakereport'
        test_job_tuple = ('send', [fake_report])
        virtwho = self.setupVirtWho()
        virtwho.send = Mock()
        virtwho.addJob(test_job_tuple)
        virtwho.run()
        virtwho.send.assert_called_with(fake_report)


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

    @patch('log.getLogger')
    @patch('manager.Manager.fromOptions')
    @patch('virt.Virt.fromConfig')
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
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        virtwho.send = Mock(wraps=virtwho.send)
        queue = Queue()
        virtwho.queue = queue
        virtwho.configManager.addConfig(self.config)
        virtwho.configManager.addConfig(self.second_config)
        queue.put(self.fake_report)
        queue.put(self.fake_domain_list)
        virtwho.run()

        self.assertEquals(virtwho.send.call_count, 2)
        self.assertTrue(virtwho.reports[self.config.hash] == self.fake_report.hash)
        self.assertTrue(virtwho.reports[self.second_config.hash] == self.fake_domain_list.hash)

    @patch('log.getLogger')
    @patch('manager.Manager.fromOptions')
    @patch('virt.Virt.fromConfig')
    def test_update_report_to_send(self, fromConfig, fromOptions, getLogger):
        options = Mock()
        options.interval = 0
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        report = Mock()
        report.hash.return_value = "hash"
        config = Mock()
        report.config = config
        config.hash.return_value = "config_hash"
        config.name.return_value = "config_name"
        self.assertTrue(virtwho.update_report_to_send(report))
        self.assertTrue(len(virtwho.configs_ready) == 1 and
                        config in virtwho.configs_ready)
        self.assertTrue(virtwho.reports_to_send[config.hash].hash == report.hash)
        # Pretend we sent the report for that config
        virtwho.configs_ready = []
        virtwho.reports[config.hash] = report.hash
        del virtwho.reports_to_send[config.hash]

        # if we receive the same report twice we should not send it
        self.assertFalse(virtwho.update_report_to_send(report))
        self.assertFalse(virtwho.configs_ready)
        self.assertFalse(virtwho.reports_to_send)

    @patch('time.time')
    @patch('log.getLogger')
    @patch('manager.Manager.fromOptions')
    @patch('virt.Virt.fromConfig')
    def test_send_current_report(self, fromConfig, fromOptions, getLogger, time):
        initial = 0
        start_time = 0
        end_time = 2
        send_after_start_time = 0
        expected_delta = end_time - start_time
        time.side_effect = [initial, start_time, end_time, send_after_start_time]

        fromOptions.return_value = Mock()
        options = Mock()
        options.interval = 6
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = VirtWho(Mock(), options, config_dir="/nonexistant")

        expected_queue_timeout = max(0, options.interval - expected_delta)
        expected_send_after = expected_queue_timeout + send_after_start_time

        config = Mock()
        config.hash = "config_hash"
        config.name = "config_name"

        virtwho.send = Mock()
        virtwho.send.return_value = True
        virtwho.reports_to_send[config.hash] = sentinel.report
        virtwho.configs_ready.append(config)

        result_config, result_report = virtwho.send_current_report()

        self.assertEquals(expected_queue_timeout, virtwho.queue_timeout)
        self.assertEquals(expected_send_after, virtwho.send_after)
        self.assertEquals(config, result_config)
        self.assertEquals(sentinel.report, result_report)
        self.assertTrue(not virtwho.reports_to_send)

    @patch('time.time')
    @patch('log.getLogger')
    @patch('manager.Manager.fromOptions')
    @patch('virt.Virt.fromConfig')
    def test_send_current_report_with_429(self, fromConfig, fromOptions, getLogger, time):
        initial = 0
        start_time = 0
        end_time = 2
        send_after_start_time = 0
        retry_after = 2
        expected_429_count = 1
        time.side_effect = [initial, initial, start_time,  send_after_start_time]

        fromOptions.return_value = Mock()
        options = Mock()
        options.interval = 6
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = VirtWho(Mock(), options, config_dir="/nonexistant")

        expected_queue_timeout = retry_after ** expected_429_count
        expected_send_after = expected_queue_timeout + send_after_start_time

        config = Mock()
        config.hash = "config_hash"
        config.name = "config_name"
        virtwho.configs_ready.append(config)
        virtwho.reports_to_send[config.hash] = sentinel.report

        virtwho.send = Mock()
        virtwho.send.return_value = False
        virtwho.send.side_effect = RestlibException("429", "429", {"Retry-After": retry_after})

        result_config, result_report = virtwho.send_current_report()

        self.assertEquals(expected_queue_timeout, virtwho.queue_timeout)
        self.assertEquals(expected_send_after, virtwho.send_after)
        self.assertEquals(result_config, config)
        self.assertEquals(None, result_report)
        self.assertEquals(len(virtwho.reports_to_send), 1)
        self.assertTrue(config in virtwho.configs_ready)

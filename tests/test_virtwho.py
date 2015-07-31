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

from mock import patch, Mock, sentinel

from virtwho import parseOptions, VirtWho, OptionError, Queue, Job
from config import Config
from virt import HostGuestAssociationReport, Hypervisor, Guest, DomainListReport
from multiprocessing import Queue


class TestOptions(TestBase):
    def setUp(self):
        self.clearEnv()

    def clearEnv(self):
        for key in os.environ.keys():
            if key.startswith("VIRTWHO"):
                del os.environ[key]

    def test_default_cmdline_options(self):
        sys.argv = ["virtwho.py"]
        _, options = parseOptions()
        self.assertFalse(options.debug)
        self.assertFalse(options.background)
        self.assertFalse(options.oneshot)
        self.assertEqual(options.interval, 600)
        self.assertEqual(options.smType, 'sam')
        self.assertEqual(options.virtType, None)

    def test_minimum_interval_options(self):
        sys.argv = ["virtwho.py", "--interval=5"]
        _, options = parseOptions()
        self.assertEqual(options.interval, 600)

    def test_options_debug(self):
        sys.argv = ["virtwho.py", "-d"]
        _, options = parseOptions()
        self.assertTrue(options.debug)

        sys.argv = ["virtwho.py"]
        os.environ["VIRTWHO_DEBUG"] = "1"
        _, options = parseOptions()
        self.assertTrue(options.debug)

    def test_options_virt(self):
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

    def test_options_virt_satellite(self):
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

    def test_missing_option(self):
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
    def test_sending_guests(self, fromOptions, fromConfig, getLogger):
        options = Mock()
        options.oneshot = True
        options.interval = 0
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        getLogger.return_value = sentinel.logger
        fromConfig.return_value.config.name = 'test'
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        config = Config("test", "esx", "localhost", "username", "password", "owner", "env")
        virtwho.configManager.addConfig(config)
        virtwho.queue = Queue()
        virtwho.queue.put(HostGuestAssociationReport(config, {'a': ['b']}))
        virtwho.run()

        fromConfig.assert_called_with(sentinel.logger, config)
        self.assertTrue(fromConfig.return_value.start.called)
        fromOptions.assert_called_with(self.logger, options)


class TestJobs(TestBase):
    def setupVirtWho(self, oneshot=True):
        options = Mock()
        options.oneshot = oneshot
        options.interval = 0
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        config = Config("test", "esx", "localhost", "username", "password", "owner", "env")
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
        self.config = Config('config', 'esx', 'localhost', 'username', 'password', 'owner','env', log_dir='', log_file='')
        self.second_config = Config('second_config', 'esx', 'localhost', 'username', 'password', 'owner','env', log_dir='', log_file='')
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
    def test_refusal_to_send_same_hash(self, fromConfig, fromOptions, getLogger):
        options = Mock()
        options.interval = 0
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        virtwho.send = Mock(wraps=virtwho.send)
        queue = Queue()
        virtwho.queue = queue
        virtwho.configManager.addConfig(self.config)
        fromConfig.return_value.config.name = self.config.name
        virtwho.reports[self.config.hash] = self.fake_report.hash
        queue.put(self.fake_report)
        virtwho.run()
        # if we already have sent the report we should not try to send it again
        self.assertEquals(virtwho.send.call_count, 0)

    @patch('log.getLogger')
    @patch('manager.Manager.fromOptions')
    @patch('virt.Virt.fromConfig')
    def test_reports_unchanged_on_exception(self, fromConfig, fromOptions, getLogger):
        options = Mock()
        options.interval = 0
        options.oneshot = True
        options.print_ = False
        options.log_dir = ''
        options.log_file = ''
        def raiseException():
            raise Exception

        virtwho = VirtWho(self.logger, options, config_dir="/nonexistant")
        virtwho.send = Mock(wraps=virtwho.send)
        virtwho._sendGuestAssociation = Mock(wraps=virtwho._sendGuestAssociation,
                                             side_effect=raiseException)
        virtwho._sendGuestList = Mock(wraps=virtwho._sendGuestList,
                                      side_effect=raiseException)
        queue = Queue()
        virtwho.queue = queue
        queue.put(self.fake_report)
        virtwho.configManager.addConfig(self.config)
        fromConfig.return_value.config.name = self.config.name
        virtwho.run()
        self.assertFalse(virtwho.reports)



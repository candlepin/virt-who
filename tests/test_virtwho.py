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

from mock import patch, Mock

from virtwho import parseOptions, VirtWho, OptionError
from config import Config
from virt import VirtError, HostGuestAssociationReport
from manager import ManagerError


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
        self.assertEqual(options.interval, 3600)
        self.assertEqual(options.smType, 'sam')
        self.assertEqual(options.virtType, None)

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

    @patch('virt.Virt.fromConfig')
    @patch('manager.Manager.fromOptions')
    def test_sending_guests(self, fromOptions, fromConfig):
        options = Mock()
        options.oneshot = True
        options.interval = 0
        options.print_ = False
        virtwho = VirtWho(self.logger, options)
        config = Config("test", "esx", "localhost", "username", "password", "owner", "env")
        virtwho.configManager.addConfig(config)
        virtwho.queue.put(HostGuestAssociationReport(config, {'a': ['b']}))
        virtwho.run()

        fromConfig.assert_called_with(self.logger, config)
        self.assertTrue(fromConfig.return_value.start.called)
        fromOptions.assert_called_with(self.logger, options)

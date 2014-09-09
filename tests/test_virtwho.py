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
from base import TestBase
import logging

from mock import patch, Mock

from virtwho import parseOptions, VirtWho
from config import Config
from virt import VirtError
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

    @patch('virt.Virt.fromConfig')
    @patch('manager.Manager.fromOptions')
    def test_sending_guests(self, fromOptions, fromConfig):
        options = Mock()
        options.oneshot = True
        virtwho = VirtWho(self.logger, options)
        config = Config("test", "esx", "localhost", "username", "password", "owner", "env")
        virtwho.configManager.addConfig(config)
        self.assertTrue(virtwho.send())

        fromConfig.assert_called_with(self.logger, config)
        self.assertTrue(fromConfig.return_value.getHostGuestMapping.called)
        fromOptions.assert_called_with(self.logger, options)

    @patch('virt.Virt.fromConfig')
    @patch('manager.Manager.fromOptions')
    def test_sending_guests_errors(self, fromOptions, fromConfig):
        options = Mock()
        options.oneshot = True
        virtwho = VirtWho(self.logger, options)
        config = Config("test", "esx", "localhost", "username", "password", "owner", "env")
        virtwho.configManager.addConfig(config)
        fromConfig.return_value.getHostGuestMapping.side_effect = VirtError
        self.assertFalse(virtwho.send())

        fromConfig.assert_called_with(self.logger, config)
        self.assertTrue(fromConfig.return_value.getHostGuestMapping.called)
        fromOptions.assert_not_called()

        fromConfig.return_value.getHostGuestMapping.side_effect = None
        fromOptions.return_value.hypervisorCheckIn.side_effect = ManagerError
        self.assertFalse(virtwho.send())
        fromConfig.assert_called_with(self.logger, config)
        self.assertTrue(fromConfig.return_value.getHostGuestMapping.called)
        fromOptions.assert_called()
        self.assertTrue(fromOptions.return_value.hypervisorCheckIn.called)

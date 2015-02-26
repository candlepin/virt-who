"""
Test reading and writing configuration files.

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
from config import ConfigManager, InvalidOption
from tempfile import mkdtemp
from base import TestBase, unittest
from binascii import hexlify
from mock import patch


class TestReadingConfigs(TestBase):
    def setUp(self):
        self.config_dir = mkdtemp()
        self.addCleanup(shutil.rmtree, self.config_dir)

    def testEmptyConfig(self):
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 0)

    def testBasicConfig(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
rhsm_username=admin
rhsm_password=password
""")

        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0]
        self.assertEqual(config.name, "test")
        self.assertEqual(config.type, "esx")
        self.assertEqual(config.server, "1.2.3.4")
        self.assertEqual(config.username, "admin")
        self.assertEqual(config.password, "password")
        self.assertEqual(config.owner, "root")
        self.assertEqual(config.env, "staging")
        self.assertEqual(config.rhsm_username, 'admin')
        self.assertEqual(config.rhsm_password, 'password')
        self.assertEqual(config.esx_simplified_vim, True)

    def testInvalidConfig(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
Malformed configuration file
""")
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 0)

    def testInvalidType(self):
        filename = os.path.join(self.config_dir, "test.conf")
        with open(filename, "w") as f:
            f.write("""
[test]
type=invalid
server=1.2.3.4
username=test
""")
        self.assertRaises(InvalidOption, ConfigManager, self.config_dir)

    @unittest.skipIf(os.getuid() == 0, "Can't create unreadable file when running as root")
    def testUnreadableConfig(self):
        filename = os.path.join(self.config_dir, "test.conf")
        with open(filename, "w") as f:
            f.write("""
[test]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
""")
        os.chmod(filename, 0)
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 0)

    @patch('password.Password._read_key_iv')
    def testCryptedPassword(self, password):
        from password import Password
        password.return_value = (hexlify(Password._generate_key()), hexlify(Password._generate_key()))
        passwd = "TestSecretPassword!"
        crypted = hexlify(Password.encrypt(passwd))

        filename = os.path.join(self.config_dir, "test.conf")
        with open(filename, "w") as f:
            f.write("""
[test]
type=esx
server=1.2.3.4
username=admin
encrypted_password=%s
owner=root
env=staging
""" % crypted)
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0].password, passwd)

    def testNoOptionsConfig(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=esx
""")
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 0)

    def testMultipleConfigsInFile(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging

[test2]
type=hyperv
server=1.2.3.5
username=admin
password=password
owner=root
env=staging
""")

        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 2)
        config = manager.configs[0]
        self.assertEqual(config.name, "test1")
        self.assertEqual(config.type, "esx")
        self.assertEqual(config.server, "1.2.3.4")
        self.assertEqual(config.username, "admin")
        self.assertEqual(config.password, "password")
        self.assertEqual(config.owner, "root")
        self.assertEqual(config.env, "staging")
        config = manager.configs[1]
        self.assertEqual(config.name, "test2")
        self.assertEqual(config.type, "hyperv")
        self.assertEqual(config.username, "admin")
        self.assertEqual(config.server, "1.2.3.5")
        self.assertEqual(config.password, "password")
        self.assertEqual(config.owner, "root")
        self.assertEqual(config.env, "staging")

    def testMultipleConfigFiles(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
""")
        with open(os.path.join(self.config_dir, "test2.conf"), "w") as f:
            f.write("""
[test2]
type=hyperv
server=1.2.3.5
username=admin
password=password
owner=root
env=staging
""")

        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 2)

        config2, config1 = manager.configs

        self.assertIn(config1.name, ("test1", "test2"))
        if config1.name == "test2":
            config2, config1 = config1, config2

        self.assertEqual(config1.name, "test1")
        self.assertEqual(config1.type, "esx")
        self.assertEqual(config1.server, "1.2.3.4")
        self.assertEqual(config1.username, "admin")
        self.assertEqual(config1.password, "password")
        self.assertEqual(config1.owner, "root")
        self.assertEqual(config1.env, "staging")

        self.assertEqual(config2.name, "test2")
        self.assertEqual(config2.type, "hyperv")
        self.assertEqual(config2.server, "1.2.3.5")
        self.assertEqual(config2.username, "admin")
        self.assertEqual(config2.password, "password")
        self.assertEqual(config2.owner, "root")
        self.assertEqual(config2.env, "staging")

    def testLibvirtConfig(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=libvirt
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
""")
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0]
        self.assertEqual(config.name, "test1")
        self.assertEqual(config.type, "libvirt")
        self.assertEqual(config.server, "1.2.3.4")
        self.assertEqual(config.username, "admin")
        self.assertEqual(config.password, "password")
        self.assertEqual(config.owner, "root")
        self.assertEqual(config.env, "staging")

    def testEsxDisableSimplifiedVim(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
simplified_vim=false
""")
        manager = ConfigManager(self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0]
        self.assertFalse(config.esx_simplified_vim)

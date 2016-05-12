"""
Test reading and writing configuration files as well as configuration objects.

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
import sys
import shutil
from tempfile import mkdtemp
from binascii import hexlify, unhexlify
from mock import patch
import logging
import random

from base import TestBase, unittest

from virtwho.config import ConfigManager, InvalidOption, GeneralConfig, NotSetSentinel, GlobalConfig, parse_list
from virtwho.password import Password, InvalidKeyFile


class TestReadingConfigs(TestBase):
    def setUp(self):
        self.config_dir = mkdtemp()
        self.addCleanup(shutil.rmtree, self.config_dir)
        self.logger = logging.getLogger("virtwho.main")

    def testEmptyConfig(self):
        manager = ConfigManager(self.logger, self.config_dir)
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
rhsm_hostname=host
rhsm_port=1234
rhsm_prefix=prefix
rhsm_proxy_hostname=proxy host
rhsm_proxy_port=4321
rhsm_proxy_user=proxyuser
rhsm_proxy_password=proxypass
rhsm_insecure=1
""")

        manager = ConfigManager(self.logger, self.config_dir)
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
        self.assertEqual(config.rhsm_hostname, 'host')
        self.assertEqual(config.rhsm_port, '1234')
        self.assertEqual(config.rhsm_prefix, 'prefix')
        self.assertEqual(config.rhsm_proxy_hostname, 'proxy host')
        self.assertEqual(config.rhsm_proxy_port, '4321')
        self.assertEqual(config.rhsm_proxy_user, 'proxyuser')
        self.assertEqual(config.rhsm_proxy_password, 'proxypass')
        self.assertEqual(config.rhsm_insecure, '1')
        self.assertEqual(config.simplified_vim, True)

    def testInvalidConfig(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
Malformed configuration file
""")
        manager = ConfigManager(self.logger, self.config_dir)
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
        self.assertRaises(InvalidOption, ConfigManager, self.logger, self.config_dir)

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
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 0)

    @patch('virtwho.password.Password._read_key_iv')
    def testCryptedPassword(self, password):
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
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0].password, passwd)

    @patch('virtwho.password.Password._read_key_iv')
    def testCryptedRHSMPassword(self, password):
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
password=bacon
rhsm_username=admin
rhsm_encrypted_password=%s
owner=root
env=staging
""" % crypted)
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0].rhsm_password, passwd)

    @patch('virtwho.password.Password._read_key_iv')
    def testCryptedRHSMProxyPassword(self, password):
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
password=bacon
rhsm_encrypted_proxy_password=%s
owner=root
env=staging
""" % crypted)
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0].rhsm_proxy_password, passwd)

    def testCryptedPasswordWithoutKey(self):
        Password.KEYFILE = "/some/nonexistant/file"
        # passwd = "TestSecretPassword!"
        with self.assertRaises(InvalidKeyFile):
            Password.decrypt(unhexlify("06a9214036b8a15b512e03d534120006"))

    def testNoOptionsConfig(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=esx
""")
        self.assertRaises(InvalidOption, ConfigManager, self.logger, self.config_dir)

    def testMultipleConfigsInFile(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root1
env=staging1
rhsm_username=rhsm_admin1
rhsm_password=rhsm_password1
rhsm_hostname=host1
rhsm_port=12341
rhsm_prefix=prefix1
rhsm_proxy_hostname=proxyhost1
rhsm_proxy_port=43211
rhsm_proxy_user=proxyuser1
rhsm_proxy_password=proxypass1
rhsm_insecure=1

[test2]
type=hyperv
server=1.2.3.5
username=admin
password=password
owner=root2
env=staging2
rhsm_username=rhsm_admin2
rhsm_password=rhsm_password2
rhsm_hostname=host2
rhsm_port=12342
rhsm_prefix=prefix2
rhsm_proxy_hostname=proxyhost2
rhsm_proxy_port=43212
rhsm_proxy_user=proxyuser2
rhsm_proxy_password=proxypass2
rhsm_insecure=2
""")

        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 2)
        config = manager.configs[0]
        self.assertEqual(config.name, "test1")
        self.assertEqual(config.type, "esx")
        self.assertEqual(config.server, "1.2.3.4")
        self.assertEqual(config.username, "admin")
        self.assertEqual(config.password, "password")
        self.assertEqual(config.owner, "root1")
        self.assertEqual(config.env, "staging1")
        self.assertEqual(config.rhsm_username, 'rhsm_admin1')
        self.assertEqual(config.rhsm_password, 'rhsm_password1')
        self.assertEqual(config.rhsm_hostname, 'host1')
        self.assertEqual(config.rhsm_port, '12341')
        self.assertEqual(config.rhsm_prefix, 'prefix1')
        self.assertEqual(config.rhsm_proxy_hostname, 'proxyhost1')
        self.assertEqual(config.rhsm_proxy_port, '43211')
        self.assertEqual(config.rhsm_proxy_user, 'proxyuser1')
        self.assertEqual(config.rhsm_proxy_password, 'proxypass1')
        self.assertEqual(config.rhsm_insecure, '1')
        config = manager.configs[1]
        self.assertEqual(config.name, "test2")
        self.assertEqual(config.type, "hyperv")
        self.assertEqual(config.username, "admin")
        self.assertEqual(config.server, "1.2.3.5")
        self.assertEqual(config.password, "password")
        self.assertEqual(config.owner, "root2")
        self.assertEqual(config.env, "staging2")
        self.assertEqual(config.rhsm_username, 'rhsm_admin2')
        self.assertEqual(config.rhsm_password, 'rhsm_password2')
        self.assertEqual(config.rhsm_hostname, 'host2')
        self.assertEqual(config.rhsm_port, '12342')
        self.assertEqual(config.rhsm_prefix, 'prefix2')
        self.assertEqual(config.rhsm_proxy_hostname, 'proxyhost2')
        self.assertEqual(config.rhsm_proxy_port, '43212')
        self.assertEqual(config.rhsm_proxy_user, 'proxyuser2')
        self.assertEqual(config.rhsm_proxy_password, 'proxypass2')
        self.assertEqual(config.rhsm_insecure, '2')

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
rhsm_username=rhsm_admin1
rhsm_password=rhsm_password1
rhsm_hostname=host1
rhsm_port=12341
rhsm_prefix=prefix1
rhsm_proxy_hostname=proxyhost1
rhsm_proxy_port=43211
rhsm_proxy_user=proxyuser1
rhsm_proxy_password=proxypass1
rhsm_insecure=1
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
rhsm_username=rhsm_admin2
rhsm_password=rhsm_password2
rhsm_hostname=host2
rhsm_port=12342
rhsm_prefix=prefix2
rhsm_proxy_hostname=proxyhost2
rhsm_proxy_port=43212
rhsm_proxy_user=proxyuser2
rhsm_proxy_password=proxypass2
rhsm_insecure=2
""")

        manager = ConfigManager(self.logger, self.config_dir)
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
        self.assertEqual(config1.rhsm_username, 'rhsm_admin1')
        self.assertEqual(config1.rhsm_password, 'rhsm_password1')
        self.assertEqual(config1.rhsm_hostname, 'host1')
        self.assertEqual(config1.rhsm_port, '12341')
        self.assertEqual(config1.rhsm_prefix, 'prefix1')
        self.assertEqual(config1.rhsm_proxy_hostname, 'proxyhost1')
        self.assertEqual(config1.rhsm_proxy_port, '43211')
        self.assertEqual(config1.rhsm_proxy_user, 'proxyuser1')
        self.assertEqual(config1.rhsm_proxy_password, 'proxypass1')
        self.assertEqual(config1.rhsm_insecure, '1')

        self.assertEqual(config2.name, "test2")
        self.assertEqual(config2.type, "hyperv")
        self.assertEqual(config2.server, "1.2.3.5")
        self.assertEqual(config2.username, "admin")
        self.assertEqual(config2.password, "password")
        self.assertEqual(config2.owner, "root")
        self.assertEqual(config2.env, "staging")
        self.assertEqual(config2.rhsm_username, 'rhsm_admin2')
        self.assertEqual(config2.rhsm_password, 'rhsm_password2')
        self.assertEqual(config2.rhsm_hostname, 'host2')
        self.assertEqual(config2.rhsm_port, '12342')
        self.assertEqual(config2.rhsm_prefix, 'prefix2')
        self.assertEqual(config2.rhsm_proxy_hostname, 'proxyhost2')
        self.assertEqual(config2.rhsm_proxy_port, '43212')
        self.assertEqual(config2.rhsm_proxy_user, 'proxyuser2')
        self.assertEqual(config2.rhsm_proxy_password, 'proxypass2')
        self.assertEqual(config2.rhsm_insecure, '2')

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
        manager = ConfigManager(self.logger, self.config_dir)
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
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0]
        self.assertFalse(config.simplified_vim)

    def testMissingEnvOption(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
rhsm_hostname=abc
""")
        self.assertRaises(InvalidOption, ConfigManager, self.logger, self.config_dir)

    def testMissingOwnerOption(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
env=env
rhsm_hostname=abc
""")
        self.assertRaises(InvalidOption, ConfigManager, self.logger, self.config_dir)

    def testInvisibleConfigFile(self):
        with open(os.path.join(self.config_dir, ".test1.conf"), "w") as f:
            f.write("""
[test1]
type=libvirt
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
""")
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 0, "Hidden config file shouldn't be read")

    def testFilterHostOld(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
filter_host_uuids=12345
""")
        manager = ConfigManager(self.logger, self.config_dir)
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0].filter_hosts, ['12345'])

    def testFilterHostNew(self):
            with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
                f.write("""
[test1]
type=esx
server=1.2.3.4
username=admin
password=password
owner=root
env=staging
filter_hosts=12345
""")
            manager = ConfigManager(self.logger, self.config_dir)
            self.assertEqual(len(manager.configs), 1)
            self.assertEqual(manager.configs[0].filter_hosts, ['12345'])


class TestGeneralConfig(TestBase):
    """
    A group of unittests to ensure correct functionality of GeneralConfig
    """
    def setUp(self):
        self.config = GeneralConfig()

    def test___init__(self):
        defaults = {
            'test': '1',
            'override_me': 'wrong_value'
        }
        arg_dict = {
            'arg_dict': 'some_value',
            'override_me': 'expected_value'
        }
        general_config = GeneralConfig(defaults=defaults, **arg_dict)

        self.assertEqual(getattr(general_config, 'test'), '1')
        self.assertEqual(getattr(general_config, 'arg_dict'), 'some_value')
        self.assertEqual(getattr(general_config, 'override_me'), 'expected_value')

    def test___getattr__(self):
        self.config.test = 1
        self.assertTrue(self.config.test, 1)

    def test___setattr__(self):
        self.config.test = 1
        self.assertEqual(self.config.test, 1)

    def test___setattr___Not_Set_Sentinel(self):
        # The general config class should refuse
        # to set attributes to an instance of NotSetSentinel
        self.config.test = NotSetSentinel()
        self.assertEqual(self.config.test, None)

    def test_update(self):
        # The function should perform similarly to a dict's update method
        test_dict = {
            'cool_attribute': 'cool_value',
            'not_set': NotSetSentinel()
        }
        self.config.update(**test_dict)
        self.assertEquals(self.config.cool_attribute, 'cool_value')
        self.assertEquals(self.config.not_set, None)

    def test___getitem__(self):
        self.config.test = 1
        self.assertEqual(self.config['test'], 1)

    def test___setitem__(self):
        self.config['test'] = 1
        self.assertEqual(self.config['test'], 1)

    def test___delitem__(self):
        self.config['test'] = 1
        self.assertEqual(self.config['test'], 1)
        del self.config['test']
        self.assertRaises(KeyError, self.config.__getitem__, 'test')

    def test___contains__(self):
        self.config['test'] = 1
        self.assertTrue('test' in self.config)
        self.assertFalse('not_here' in self.config)


class TestGlobalConfig(TestBase):

    def setUp(self):
        self.config = GlobalConfig()

    def test___getattr__INT(self):
        int_option = random.choice(GlobalConfig.INT_OPTIONS)
        test_int = random.randint(-sys.maxint, sys.maxint)
        # set to a random int
        setattr(self.config, int_option, test_int)
        self.assertEqual(getattr(self.config, int_option), test_int)

        # set to a string of an int
        setattr(self.config, int_option, str(test_int))
        self.assertEqual(getattr(self.config, int_option), test_int)

    def test___getattr__BOOL(self):
        bool_option = random.choice(GlobalConfig.BOOL_OPTIONS)
        test_bool = False
        test_false_strings = ['0', 'no', 'false']

        setattr(self.config, bool_option, test_bool)
        self.assertEqual(getattr(self.config, bool_option), test_bool)

        for false_string in test_false_strings:
            setattr(self.config, bool_option, false_string)
            self.assertEqual(getattr(self.config, bool_option), False)


class TestParseList(TestBase):
    def test_unquoted(self):
        self.assertEqual(
            parse_list('abc,def,ghi'),
            ['abc', 'def', 'ghi']
        )
        self.assertEqual(
            parse_list(' abc, def ,ghi, jkl '),
            ['abc', 'def', 'ghi', 'jkl']
        )
        self.assertEqual(
            parse_list(' abc, def ,ghi, jkl,'),
            ['abc', 'def', 'ghi', 'jkl']
        )

    def test_doublequoted(self):
        self.assertEqual(
            parse_list('"abc","def","ghi"'),
            ['abc', 'def', 'ghi']
        )
        self.assertEqual(
            parse_list('"abc", "def" ,"ghi" , "jkl"'),
            ['abc', 'def', 'ghi', 'jkl']
        )
        self.assertEqual(
            parse_list('"abc ", " def" ,"g h i" , " j,l "'),
            ['abc ', ' def', 'g h i', ' j,l ']
        )
        self.assertRaises(ValueError, parse_list, 'abc"def')
        self.assertEqual(
            parse_list('"abc\\"", "\\"def"'),
            ['abc"', '"def']
        )

    def test_singlequoted(self):
        self.assertEqual(
            parse_list("'abc','def','ghi'"),
            ['abc', 'def', 'ghi']
        )
        self.assertEqual(
            parse_list("'abc', 'def' ,'ghi' , 'jkl'"),
            ['abc', 'def', 'ghi', 'jkl']
        )
        self.assertEqual(
            parse_list("'abc ', ' def' ,'g h i' , ' j,l '"),
            ['abc ', ' def', 'g h i', ' j,l ']
        )
        self.assertRaises(ValueError, parse_list, "abc'def")

    def test_special(self):
        self.assertEqual(
            parse_list("'\babc','!def',',\\\\ghi'"),
            ['\babc', '!def', ',\\ghi']
        )
        self.assertEqual(
            parse_list("'a\nc', '\tdef' ,'\"ghi\"' , \"'jkl'\""),
            ['a\nc', '\tdef', '"ghi"', "'jkl'"]
        )
        self.assertEqual(
            parse_list("'abc\ ', '\\\\ def' ,'g h i' , ' jkl '"),
            ['abc ', '\\ def', 'g h i', ' jkl ']
        )

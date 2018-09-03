from __future__ import print_function
# coding=utf-8
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
import six
import shutil
from tempfile import mkdtemp
from binascii import hexlify, unhexlify
from mock import patch
import logging

from base import TestBase, unittest

from virtwho.config import DestinationToSourceMapper, parse_list, Satellite6DestinationInfo, init_config, \
    VW_GLOBAL, VW_ENV_CLI_SECTION_NAME
import virtwho.config

from virtwho.password import Password, InvalidKeyFile

default_config_values = {
    "name": "test",
    "type": "esx",
    "server": "1.2.3.4",
    "username": "admin",
    "password": "password",
    "owner": "root",
    "env": "staging",
    "rhsm_username": "admin",
    "rhsm_password": "password",
    "rhsm_hostname": "host",
    "rhsm_port": "1234",
    "rhsm_prefix": "prefix",
    "rhsm_proxy_hostname": "proxy host",
    "rhsm_proxy_port": "4321",
    "rhsm_proxy_user": "proxyuser",
    "rhsm_proxy_password": "proxypass",
    "rhsm_insecure": "1"
}


def combine_dicts(*args):
    """
    A utility method to combine all dictionaries passed into one
    @param args: One or more dicts
    @type args: dict

    @return: dict with the combined values from all args. NOTE: The value
    for any key in more than one dict will be the value of the last dict
    in the arg list that has that key.
    @rtype: dict
    """
    result = {}
    for arg in args:
        result.update(arg)
    return result


def append_number_to_all(in_dict, number):
    result = {}
    for key, value in in_dict.items():
        result[key] = value + str(number)
    return result


class TestReadingConfigs(TestBase):
    source_options_1 = {
        "name": "test1",
        "type": "esx",  # The following values are sensitive to the type involved
        "server": "https://1.2.3.4",  # for example, "http://" is needed here
        "username": "admin",
        "password": "password",
    }
    source_options_2 = {
        "name": "test2",
        "type": "esx",
        "server": "https://1.2.3.5",
        "username": "admin",
        "password": "password",
    }
    dest_options = {
        "owner": "root",
        "env": "staging",
        "rhsm_username": "rhsm_admin",
        "rhsm_password": "rhsm_password",
        "rhsm_hostname": "host",
        "rhsm_port": "1234",
        "rhsm_prefix": "prefix",
        "rhsm_proxy_hostname": "proxyhost",
        "rhsm_proxy_port": "4321",
        "rhsm_proxy_user": "proxyuser",
        "rhsm_proxy_password": "proxypass",
        "rhsm_insecure": ""
    }
    dest_options_1 = append_number_to_all(dest_options, 1)
    dest_options_2 = append_number_to_all(dest_options, 2)

    def setUp(self):
        self.config_dir = mkdtemp()
        self.custom_config_dir = mkdtemp()
        self.general_config_file_dir = mkdtemp()
        self.addCleanup(shutil.rmtree, self.config_dir, self.custom_config_dir, self.general_config_file_dir)
        self.logger = logging.getLogger("virtwho.main")

    def tearDown(self):
        virtwho.config.VW_GENERAL_CONF_PATH = '/etc/virt-who.conf'

    @staticmethod
    def dict_to_ini(in_dict):
        """
        A utility method that formats the given dict as a section of an ini

        @param in_dict: The dictionary containing the keys and values to be
        made ini-like. The section name returned by this method will be the
        value of the "name" key in this dict.
        @type in_dict: dict

        @return: A string formatted like an ini file section
        @rtype: str
        """
        header = "[%s]\n" % in_dict.get("name", "test")
        body = "\n".join(["%s=%s" % (key, val) for key, val in
                          in_dict.items() if key is not "name"])
        return header + body + "\n"

    def test_empty_config(self):
        config = init_config({}, {}, self.config_dir)
        six.assertCountEqual(self, list(config.keys()), [VW_GLOBAL, VW_ENV_CLI_SECTION_NAME])

    def assert_config_equals_default(self, config):
        self.assertEqual(config.name, "test")
        self.assertEqual(config['type'], "esx")
        self.assertEqual(config['server'], "https://1.2.3.4")
        self.assertEqual(config['username'], "admin")
        self.assertEqual(config['password'], "password")
        self.assertEqual(config['owner'], "root")
        self.assertEqual(config['env'], "staging")
        self.assertEqual(config['rhsm_username'], 'admin')
        self.assertEqual(config['rhsm_password'], 'password')
        self.assertEqual(config['rhsm_hostname'], 'host')
        self.assertEqual(config['rhsm_port'], '1234')
        self.assertEqual(config['rhsm_prefix'], 'prefix')
        self.assertEqual(config['rhsm_proxy_hostname'], 'proxy host')
        self.assertEqual(config['rhsm_proxy_port'], '4321')
        self.assertEqual(config['rhsm_proxy_user'], 'proxyuser')
        self.assertEqual(config['rhsm_proxy_password'], 'proxypass')
        self.assertEqual(config['rhsm_insecure'], '1')
        self.assertEqual(config['simplified_vim'], True)

    def assert_config_contains_all(self, config, options):
        for key in options:
            if key == 'name':
                config_value = getattr(config, key)
            else:
                config_value = config.get(key, None)
            self.assertEqual(config_value, options[key])

    def test_basic_config(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(default_config_values))
        config = init_config({}, {}, config_dir=self.config_dir)
        six.assertCountEqual(self, list(config.keys()), ['test', 'global'])
        self.assert_config_equals_default(config['test'])

    def test_invalid_config(self):
        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write("""
Malformed configuration file
""")
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # If there are only invalid configurations specified, and nothing has been specified via
        # the command line or ENV then we should use the default
        # TODO Remove the default hard-coded behaviour, and allow virt-who to output a
        # configuration that will cause it to behave equivalently
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0][0], VW_ENV_CLI_SECTION_NAME)

    def test_invalid_type(self):
        filename = os.path.join(self.config_dir, "test.conf")
        with open(filename, "w") as f:
            f.write("""
[test]
type=invalid
server=1.2.3.4
username=test
""")
        # Instantiating the DestinationToSourceMapper with an invalid config should not fail
        # instead we expect that the list of configs managed by the DestinationToSourceMapper does not
        # include the invalid one
        config_manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # There should be no configs parsed successfully, therefore the list of configs should
        # be empty
        self.assertEqual(len(config_manager.configs), 0)

    @unittest.skipIf(os.getuid() == 0, "Can't create unreadable file when running as root")
    def test_unreadable_config(self):
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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # There should be at least one 'env/cmdline' section
        self.assertEqual(len(manager.configs), 1)

    @patch('virtwho.password.Password._read_key_iv')
    def testCryptedPassword(self, password):
        password.return_value = (hexlify(Password._generate_key()), hexlify(Password._generate_key()))
        passwd = "TestSecretPassword!"
        crypted = hexlify(Password.encrypt(passwd)).decode('utf-8')

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0][1]['password'], passwd)

    @patch('virtwho.password.Password._read_key_iv')
    def testCryptedRHSMPassword(self, password):
        password.return_value = (hexlify(Password._generate_key()), hexlify(Password._generate_key()))
        passwd = "TestSecretPassword!"
        crypted = hexlify(Password.encrypt(passwd)).decode('utf-8')

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0][1]["rhsm_password"], passwd)

    @patch('virtwho.password.Password._read_key_iv')
    def testCryptedRHSMProxyPassword(self, password):
        password.return_value = (hexlify(Password._generate_key()), hexlify(Password._generate_key()))
        passwd = "TestSecretPassword!"
        crypted = hexlify(Password.encrypt(passwd)).decode('utf-8')

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0][1]["rhsm_proxy_password"], passwd)

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
        # Instantiating the DestinationToSourceMapper with an invalid config should not fail
        # instead we expect that the list of configs managed by the DestinationToSourceMapper does not
        # include the invalid one
        config_manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # There should be no configs parsed successfully, therefore the list of configs should
        # be empty
        self.assertEqual(len(config_manager.configs), 0)

    def testMultipleConfigsInFile(self):
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)
        config_2 = combine_dicts(TestReadingConfigs.source_options_2,
                                 TestReadingConfigs.dest_options_2)

        with open(os.path.join(self.config_dir, "test.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1) +
                    TestReadingConfigs.dict_to_ini(config_2))

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 2)
        for name, config in manager.configs:
            self.assertIn(config.name, [config_1["name"], config_2["name"]])
            if config.name == config_1['name']:
                self.assert_config_contains_all(config, config_1)
            elif config.name == config_2['name']:
                self.assert_config_contains_all(config, config_2)

    def testMultipleConfigFiles(self):
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)
        config_2 = combine_dicts(TestReadingConfigs.source_options_2,
                                 TestReadingConfigs.dest_options_2)

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1))
        with open(os.path.join(self.config_dir, "test2.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_2))

        expected_dest_1 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_1)
        expected_dest_2 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_2)

        expected_mapping = {
            expected_dest_1: [config_1['name']],
            expected_dest_2: [config_2['name']]
        }

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 2)
        self.assertEqual(manager.dest_to_sources_map, expected_mapping)
        self.assertEqual(manager.dests, set([expected_dest_1, expected_dest_2]))
        self.assertEqual(manager.sources,
                         set([config_1['name'], config_2['name']]))

        result1 = manager.configs[0][1]
        result2 = manager.configs[1][1]

        self.assertIn(result1.name, ("test1", "test2"))
        if result1.name == "test2":
            result2, result1 = result1, result2

        self.assert_config_contains_all(result1, config_1)
        self.assert_config_contains_all(result2, config_2)

    def test_many_sources_to_one_dest(self):
        # This tests that there can be multiple configs that specify to
        # report to the same destination
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)
        config_2 = combine_dicts(TestReadingConfigs.source_options_2,
                                 TestReadingConfigs.dest_options_1)
        expected_dest = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_1)

        expected_mapping = {expected_dest: [config_1['name'],
                                            config_2['name']]}

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1) +
                    TestReadingConfigs.dict_to_ini(config_2))

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(manager.dests, set([expected_dest]))
        self.assertEqual(manager.sources,
                         set([config_1['name'], config_2['name']]))

        self.assertEqual(manager.dest_to_sources_map, expected_mapping)

    def test_one_source_to_many_dests(self):
        # This tests that there can be one source that specifies
        # information for different destinations and that the correct mapping
        # is created.
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)

        # NOTE: virt-who today does not support config sections having the same
        # name. Hence the only way to have one source go to multiple
        # destinations (without new config options) is to have two sections
        # with the same information but different section names
        config_options_2 = TestReadingConfigs.source_options_1.copy()
        config_options_2['name'] = 'test2'
        config_2 = combine_dicts(config_options_2,
                                 TestReadingConfigs.dest_options_2)

        expected_dest_1 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_1)
        expected_dest_2 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_2)
        expected_mapping = {
            expected_dest_1: [config_1['name']],
            expected_dest_2: [config_2['name']]  # config_2['name'] ==
                                                 # config_1['name']
        }

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1) +
                    TestReadingConfigs.dict_to_ini(config_2))

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(manager.dest_to_sources_map, expected_mapping)

    def test_one_source_to_one_dest(self):
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)
        expected_dest_1 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_1)
        expected_mapping = {
            expected_dest_1: [config_1['name']]
        }

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1))

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(manager.dest_to_sources_map, expected_mapping)

    def test_two_sources_to_two_dests(self):
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)
        config_2 = combine_dicts(TestReadingConfigs.source_options_2,
                                 TestReadingConfigs.dest_options_2)
        expected_dest_1 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_1)
        expected_dest_2 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_2)
        expected_mapping = {
            expected_dest_1: [config_1['name']],
            expected_dest_2: [config_2['name']]
        }

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1) +
                    TestReadingConfigs.dict_to_ini(config_2))

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(manager.dest_to_sources_map, expected_mapping)

    def test_many_sources_to_many_dests(self):
        config_1 = combine_dicts(TestReadingConfigs.source_options_1,
                                 TestReadingConfigs.dest_options_1)
        config_2 = combine_dicts(TestReadingConfigs.source_options_2,
                                 TestReadingConfigs.dest_options_2)

        # Create another source config that is slightly different
        source_3_options = TestReadingConfigs.source_options_2.copy()
        source_3_options['name'] = 'test3'
        source_4_options = TestReadingConfigs.source_options_1.copy()
        source_4_options['name'] = 'test4'

        # Create another dest config that is slightly different
        dest_options_3 = TestReadingConfigs.dest_options_2.copy()
        dest_options_3['owner'] = 'some_cool_owner_person'

        config_3 = combine_dicts(source_3_options,
                                 TestReadingConfigs.dest_options_2)

        config_4 = combine_dicts(source_4_options,
                                 dest_options_3)

        expected_dest_1 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_1)
        expected_dest_2 = Satellite6DestinationInfo(
                **TestReadingConfigs.dest_options_2)
        expected_dest_3 = Satellite6DestinationInfo(**dest_options_3)

        expected_mapping = {
            expected_dest_1: [config_1['name']],
            expected_dest_2: [config_2['name'], config_3['name']],
            expected_dest_3: [config_4['name']]
        }

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write(TestReadingConfigs.dict_to_ini(config_1) +
                    TestReadingConfigs.dict_to_ini(config_2) +
                    TestReadingConfigs.dict_to_ini(config_3) +
                    TestReadingConfigs.dict_to_ini(config_4))

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(manager.dest_to_sources_map, expected_mapping)

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0][1]
        self.assertEqual(config.name, "test1")
        self.assertEqual(config["type"], "libvirt")
        # The following server value is different than what is provided above as it has been
        # processed by the libvirt config section validation.
        # TODO decouple this from the libvirt config section (for testing only)
        self.assertEqual(config["server"], "qemu+ssh://admin@1.2.3.4/system?no_tty=1")
        self.assertEqual(config["username"], "admin")
        self.assertEqual(config["password"], "password")
        self.assertEqual(config["owner"], "root")
        self.assertEqual(config["env"], "staging")

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        _, config = manager.configs[0]
        self.assertFalse(config['simplified_vim'])

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
        # Instantiating the DestinationToSourceMapper with an invalid config should not fail
        # instead we expect that the list of configs managed by the DestinationToSourceMapper does not
        # include the invalid one
        config_manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # There should be no configs parsed successfully, therefore the list of configs should
        # be empty
        self.assertEqual(len(config_manager.configs), 0)

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
        # Instantiating the DestinationToSourceMapper with an invalid config should not fail
        # instead we expect that the list of configs managed by the DestinationToSourceMapper does not
        # include the invalid one
        config_manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # There should be no configs parsed successfully, therefore the list of configs should
        # be empty
        self.assertEqual(len(config_manager.configs), 0)

    def testInvalidAndValidConfigs(self):
        valid_config_name = "valid_config"
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[%(valid_config_name)s]
type=esx
server=1.2.3.4
username=admin
password=password
owner=owner
env=env
rhsm_hostname=abc

[invalid_missing_owner]
type=esx
server=1.2.3.4
username=admin
password=password
env=env
rhsm_hostname=abc
""" % {'valid_config_name': valid_config_name})
        config_manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        # There should be only one config, and that should be the one that is valid
        self.assertEqual(len(config_manager.configs), 1)
        self.assertEqual(config_manager.configs[0][1].name, valid_config_name)

    def testCLIConfigOverridesDefaultDirectoryConfigs(self):
        cli_config_file_path = os.path.join(self.custom_config_dir, "my_file.conf")
        with open(cli_config_file_path, "w") as f:
            f.write("""
[valid_cli_section]
server=5.5.5.5
username=admin1
password=password1
owner=owner1
env=env1
rhsm_hostname=abc1
""")
        cli_dict = {'configs': [cli_config_file_path]}

        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[valid_default_dir_section]
server=1.2.3.4
username=admin
password=password
owner=owner
env=env
rhsm_hostname=abc
""")
        config_manager = DestinationToSourceMapper(init_config({}, cli_dict, config_dir=self.config_dir))
        # There should be only one config, and that should be the one passed from the cli
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0][1]
        self.assertEqual(config.name, "valid_cli_section")
        self.assertEqual(config["server"], "5.5.5.5")
        self.assertEqual(config["username"], "admin1")
        self.assertEqual(config["password"], "password1")
        self.assertEqual(config["owner"], "owner1")
        self.assertEqual(config["env"], "env1")
        self.assertEqual(config["rhsm_hostname"], "abc1")

    def testCLIConfigOverridesGeneralConfigFile(self):
        cli_config_file_path = os.path.join(self.custom_config_dir, "my_file.conf")
        with open(cli_config_file_path, "w") as f:
            f.write("""
[valid_cli_section]
server=5.5.5.5
username=admin1
password=password1
owner=owner1
env=env1
rhsm_hostname=abc1
""")
        cli_dict = {'configs': [cli_config_file_path]}

        # alter the main conf file constant temporarily:
        virtwho.config.VW_GENERAL_CONF_PATH = os.path.join(self.general_config_file_dir, "virt-who.conf")

        with open(virtwho.config.VW_GENERAL_CONF_PATH, "w") as f:
            f.write("""
[valid_default_main_conf_file_section]
server=1.2.3.4
username=admin
password=password
owner=owner
env=env
rhsm_hostname=abc
""")
        config_manager = DestinationToSourceMapper(init_config({}, cli_dict, config_dir=self.config_dir))
        # There should be only one config, and that should be the one passed from the cli
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0][1]
        self.assertEqual(config.name, "valid_cli_section")
        self.assertEqual(config["server"], "5.5.5.5")
        self.assertEqual(config["username"], "admin1")
        self.assertEqual(config["password"], "password1")
        self.assertEqual(config["owner"], "owner1")
        self.assertEqual(config["env"], "env1")
        self.assertEqual(config["rhsm_hostname"], "abc1")

    def testCLIConfigOverridesGeneralConfigFileButStillReadsItsGlobalAndDefaultsSections(self):
        cli_config_file_path = os.path.join(self.custom_config_dir, "my_file.conf")
        with open(cli_config_file_path, "w") as f:
            f.write("""
[valid_cli_section]
server=5.5.5.5
username=admin1
password=password1
owner=owner1
env=env1
rhsm_hostname=abc1
""")
        cli_dict = {'configs': [cli_config_file_path]}

        # alter the main conf file constant temporarily:
        virtwho.config.VW_GENERAL_CONF_PATH = os.path.join(self.general_config_file_dir, "virt-who.conf")

        with open(virtwho.config.VW_GENERAL_CONF_PATH, "w") as f:
            f.write("""
[global]
interval=100
log_file=rhsm45.log

[defaults]
hypervisor_id=hostname

[valid_default_main_conf_file_section]
server=1.2.3.4
username=admin
password=password
owner=owner
env=env
rhsm_hostname=abc
""")
        config_manager = DestinationToSourceMapper(init_config({}, cli_dict, config_dir=self.config_dir))
        # There should be only one config, and that should be the one passed from the cli
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0][1]
        self.assertEqual(config.name, "valid_cli_section")
        self.assertEqual(config["server"], "5.5.5.5")
        self.assertEqual(config["username"], "admin1")
        self.assertEqual(config["password"], "password1")
        self.assertEqual(config["owner"], "owner1")
        self.assertEqual(config["env"], "env1")
        self.assertEqual(config["rhsm_hostname"], "abc1")

        # Also, check that the default section values from the VW_GENERAL_CONF_PATH file are still read
        # (and used when any of the keys are missing in the virt config)
        self.assertEqual(config["hypervisor_id"], "hostname")

        # Additionally, the global section from the VW_GENERAL_CONF_PATH file should be read in
        self.assertEqual(config_manager.effective_config["global"]["log_file"], "rhsm45.log")
        self.assertEqual(config_manager.effective_config["global"]["interval"], 100)

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertTrue("test1" not in [name for (name, config) in manager.configs],
                        "Hidden config file shouldn't be read")

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0][1]["filter_hosts"], ['12345'])

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
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        self.assertEqual(manager.configs[0][1]["filter_hosts"], ['12345'])

    def testQuotesInConfig(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server="http://1.2.3.4"
username='admin'
password=p"asswor'd
owner=" root "
env='"staging"'
""")
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0][1]
        self.assertEqual(config.name, "test1")
        self.assertEqual(config["type"], "esx")
        self.assertEqual(config["server"], "http://1.2.3.4")
        self.assertEqual(config["username"], "admin")
        self.assertEqual(config["password"], "p\"asswor'd")
        self.assertEqual(config["owner"], " root ")
        self.assertEqual(config["env"], '"staging"')

    def testUnicode(self):
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=http://žluťoučký servřík
username=username
password=password
owner=здравствуйте
env=العَرَبِيَّة
""")
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0][1]
        self.assertEqual(config.name, "test1")
        self.assertEqual(config["type"], "esx")
        self.assertEqual(config["server"], "http://žluťoučký servřík")
        # Username and password can't be unicode, they has to be latin1 for HTTP Basic auth
        self.assertEqual(config["username"], "username")
        self.assertEqual(config["password"], "password")
        self.assertEqual(config["owner"], "здравствуйте")
        self.assertEqual(config["env"], 'العَرَبِيَّة')

    def testConfigFileExtensions(self):
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
        with open(os.path.join(self.config_dir, "test2.conf.bk"), "w") as f:
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

        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        name, config = manager.configs[0]

        self.assertEqual(name, "test1")
        # TODO decouple tests like these from the ConfigSections that they imply
        # The values used here reflect the expected output of the EsxConfigSection validation
        # (If in case these seem strange)
        self.assertEqual(config["type"], "esx")
        self.assertEqual(config["server"], "https://1.2.3.4")
        self.assertEqual(config["username"], "admin")
        self.assertEqual(config["password"], "password")
        self.assertEqual(config["owner"], "root")
        self.assertEqual(config["env"], "staging")
        self.assertEqual(config["rhsm_username"], 'rhsm_admin1')
        self.assertEqual(config["rhsm_password"], 'rhsm_password1')
        self.assertEqual(config["rhsm_hostname"], 'host1')
        self.assertEqual(config["rhsm_port"], '12341')
        self.assertEqual(config["rhsm_prefix"], 'prefix1')
        self.assertEqual(config["rhsm_proxy_hostname"], 'proxyhost1')
        self.assertEqual(config["rhsm_proxy_port"], '43211')
        self.assertEqual(config["rhsm_proxy_user"], 'proxyuser1')
        self.assertEqual(config["rhsm_proxy_password"], 'proxypass1')
        self.assertEqual(config["rhsm_insecure"], '1')

    def testLineContinuationInConfig(self):
        """ Test that when a config line that starts with space or tab, it is treated
        as a continuation of the previous line.
        :return:
        """
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=http://1.2.3.4
 value
username=admin
password=password
owner=root
env=staging
    filter_hosts=abc.efg.com
""")
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0][1]
        self.assertEqual(config.name, "test1")

        self.assertEqual(config["server"], 'http://1.2.3.4\nvalue')
        self.assertEqual(config["env"], 'staging\nfilter_hosts=abc.efg.com')

    @patch('logging.Logger.warn')
    def testCommentedOutLineContinuationInConfig(self, logger_warn):
        """Test that when a config line that starts with space or tab which is followed by a '#',
        if we are running python2: it is treated as a continuation of the previous line,
        but a warning is logged for the user.
        If we are running python3: it is ignored as a comment, and no warning is logged.
        :return:
        """
        with open(os.path.join(self.config_dir, "test1.conf"), "w") as f:
            f.write("""
[test1]
type=esx
server=http://1.2.3.4
 #value
username=admin
password=password
owner=root
env=staging
    #filter_hosts=abc.efg.com
""")
        manager = DestinationToSourceMapper(init_config({}, {}, config_dir=self.config_dir))
        self.assertEqual(len(manager.configs), 1)
        config = manager.configs[0][1]
        self.assertEqual(config.name, "test1")

        if six.PY2:
            self.assertEqual(config["server"], "http://1.2.3.4\n#value")
            self.assertEqual(config["env"], 'staging\n#filter_hosts=abc.efg.com')

            # Check that the warning was logged twice, and it was last called for line number 10 of the conf file:
            self.assertTrue(logger_warn.called)
            self.assertEqual(logger_warn.call_count, 2)
            logger_warn.assert_called_with('A line continuation (line starts with space) that is commented out '
                                           'was detected in file %s, line number %s.', f.name, 10)
        elif six.PY3:
            self.assertEqual(config["server"], "http://1.2.3.4")
            self.assertEqual(config["env"], 'staging')

            self.assertFalse(logger_warn.called)
            self.assertEqual(logger_warn.call_count, 0)


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

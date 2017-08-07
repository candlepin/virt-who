# coding=utf-8

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


"""
Test validating of configuration values.
"""

from base import TestBase
import copy

from virtwho.config import GlobalSection, VirtConfigSection, str_to_bool, VW_TYPES, \
    MinimumSendInterval, DefaultInterval
from virtwho.password import Password


# Values used for testing VirtConfigSection
LIBVIRT_SECTION_VALUES = {
    'type': 'libvirt',
    'server': '10.0.0.101',
    'username': 'admin',
    'password': 'top_secret',
    'env': '123456',
    'owner': '123456',
    'hypervisor_id': 'uuid',
    'filter_hosts': '*.example.com'
}

# Values used for testing GlobalConfigSection
GLOBAL_SECTION_VALUES = {
    'debug': True,
    'oneshot': 'true',
    'print': 'false',
    'wrong_bool_value': 'nein',
    'configs': ['local_libvirt.conf'],
    'log_file': 'my_custom.log',
    'interval': '120'
}


class TestVirtConfigSection(TestBase):
    """
    Test base for testing class VirtConfigSection
    """

    def setUp(self):
        """
        Method executed before each unit test
        """
        self.virt_config = VirtConfigSection('test-libvirt', None)
        self.virt_config._values = copy.deepcopy(LIBVIRT_SECTION_VALUES)

    def test_validate_virt_type(self):
        """
        Test of validation of supported types of virtual backends
        """
        test_virt_types = VW_TYPES[:]
        test_virt_types.extend('vmware, kvm, ')
        for virt_type in test_virt_types:
            self.virt_config._values['type'] = virt_type
            result = self.virt_config._validate_virt_type()
            if virt_type not in VW_TYPES:
                self.assertIsNotNone(result)
            else:
                self.assertIsNone(result)
                value = self.virt_config.get('type')
                self.assertEqual(value, virt_type)

    def test_validate_unencrypted_password(self):
        """
        Test of validation of password that is not encrypted
        """
        result = self.virt_config._validate_password()
        self.assertIsNone(result)

    def test_validate_encrypted_password(self):
        """
        Test of validation of encrypted password
        """
        password = self.virt_config['password']
        # Delete unencrypted password first
        del self.virt_config._values['password']
        # Set up encrypted password
        self.virt_config['encryped_password'] = Password.encrypt(password)
        # Do own testing here
        result = self.virt_config._validate_password()
        self.assertIsNone(result)

    def test_validate_correct_username(self):
        """
        Test of validation of username (it has to include only latin1 characters)
        """
        result = self.virt_config._validate_username()
        self.assertIsNone(result)

    def test_validate_wrong_username(self):
        """
        Test validation of wrong username (containing e.g. UTF-8 string)
        """
        # First, change username to something exotic ;-)
        self.virt_config['username'] = u'Jiří'
        result = self.virt_config._validate_username()
        self.assertIsNotNone(result)

    def test_validate_server(self):
        """
        Test validation of server
        """
        result = self.virt_config._validate_server()
        self.assertIsNone(result)

    def test_validate_missing_server(self):
        """
        Test validation of missing server for some virt backends
        """
        # These backends require server option in configuration
        virt_backends_requiring_server = ('esx', 'rhevm', 'hyperv', 'xen')
        # Delete server option
        del self.virt_config._values['server']
        # Test all of them
        for virt_type in virt_backends_requiring_server:
            self.virt_config._values['type'] = virt_type
            result = self.virt_config._validate_server()
            self.assertIsNotNone(result)

    def test_validate_missing_server_not_critical(self):
        """
        Test validation of missing server for some virt backends which
        do not need server option to exist.
        """
        # These backends do not require server option in configuration
        virt_backends_not_requiring_server = ('libvirt', 'vdsm', 'fake')
        # Delete server option
        del self.virt_config._values['server']
        # Test all of vm backend types
        for virt_type in virt_backends_not_requiring_server:
            self.virt_config._values['type'] = virt_type
            result = self.virt_config._validate_server()
            self.assertIsNone(result)

    def test_validate_environment(self):
        """
        Test validation of env option 
        """
        result = self.virt_config._validate_env()
        self.assertIsNone(result)

    def test_validate_owner(self):
        """
        Test validation of owner option
        """
        result = self.virt_config._validate_owner()
        self.assertIsNone(result)

    def test_validate_filter(self):
        result = self.virt_config._validate_filter()
        self.assertIsNone(result)


class TestGlobalConfigSection(TestBase):
    """
    Test base for testing class GlobalSection
    """

    def setUp(self):
        """
        Method executed before each unit test
        """
        self.global_config = GlobalSection('global', None)
        self.global_config._values = copy.deepcopy(GLOBAL_SECTION_VALUES)

    def test_validate_debug_value_bool(self):
        """
        Test validating of correct bool value 
        """
        result = self.global_config._validate_str_to_bool('debug')
        self.assertIsNone(result)
        value = self.global_config.get('debug')
        self.assertEqual(value, True)

    def test_validate_oneshot_value_string_true(self):
        """
        Test validating of correct bool value stored as string ('true') 
        """
        result = self.global_config._validate_str_to_bool('oneshot')
        self.assertIsNone(result)
        value = self.global_config.get('oneshot')
        self.assertEqual(value, True)

    def test_validate_print_value_string_false(self):
        """
        Test validating of correct bool value stored as string ('false') 
        """
        result = self.global_config._validate_str_to_bool('print')
        self.assertIsNone(result)
        value = self.global_config.get('print')
        self.assertEqual(value, False)

    def test_validate_wrong_bool_value(self):
        """
        Test validating of wrong string representing bool ('nein') 
        """
        self.assertRaises(ValueError, str_to_bool, self.global_config['wrong_bool_value'])
        result = self.global_config._validate_str_to_bool('wrong_bool_value')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)

    def test_validate_non_existing_key(self):
        """
        Test validation of non-existing key 
        """
        result = self.global_config._validate_str_to_bool('does_not_exist')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)

    def test_validate_string(self):
        """
        Test validation of correct string value 
        """
        result = self.global_config._validate_non_empty_string('log_file')
        self.assertIsNone(result)

    def test_validate_interval(self):
        """
        Test validation of time interval
        """
        result = self.global_config._validate_interval()
        self.assertIsNone(result)

    def test_validate_wrong_interval(self):
        """
        Test validation of wrong time interval
        """
        self.global_config._values['interval'] = '10'
        result = self.global_config._validate_interval()
        self.assertIsNotNone(result)
        interval = self.global_config.get('interval')
        self.assertEqual(interval, MinimumSendInterval)

    def test_validate_missing_interval(self):
        """
        Test validation of wrong time interval
        """
        del self.global_config._values['interval']
        result = self.global_config._validate_interval()
        self.assertIsNotNone(result)
        # interval = self.global_config.get('interval')
        # self.assertEqual(interval, DefaultInterval)

    def test_validate_configs(self):
        """
        Test validation of configs (list of paths to config files)
        """
        result = self.global_config._validate_configs()
        self.assertIsNone(result)

    def test_validate_section_values(self):
        """
        Test validation of all config values 
        """
        validate_messages = self.global_config.validate()
        expected_results = [
            ('warning', 'log_per_config must be a valid boolean, using default. See man virt-who-config for more info'),
            ('warning', 'Value for reporter_id not set, using default'),
            ('warning', 'Value for log_dir not set, using default'),
            ('warning', 'background must be a valid boolean, using default. See man virt-who-config for more info')
        ]
        self.assertGreater(len(validate_messages), 0)
        self.assertEqual(expected_results, validate_messages)

    def test_validate_default_value(self):
        """
        Test the validate method will set default value, when an option
        is missing and default value exist in DEFAULT
        """
        del self.global_config._values['interval']
        self.global_config.validate()
        default_interval = self.global_config.get('interval')
        self.assertEqual(default_interval, DefaultInterval)

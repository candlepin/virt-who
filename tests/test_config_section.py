# -*- coding: utf-8 -*-

#
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
#

"""
Test validating of configuration values.
"""

from base import TestBase
from mock import MagicMock

import tempfile
import os
from binascii import hexlify

from virtwho.config import GlobalSection, VirtConfigSection, str_to_bool, VW_TYPES, \
    MinimumSendInterval, DefaultInterval, ConfigSection, ValidationState
from virtwho.password import Password
from virtwho.log import DEFAULT_LOG_DIR


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
        # We need to set values using this way, because we need
        # to trigger __setitem__ of virt_config
        for key, value in LIBVIRT_SECTION_VALUES.items():
            self.virt_config[key] = value

    def test_validate_virt_type(self):
        """
        Test validation of supported types of virtualization backends
        """
        test_virt_types = list(VW_TYPES[:])
        test_virt_types.extend('vmware,' 'kvm')
        for virt_type in test_virt_types:
            self.virt_config['type'] = virt_type
            result = self.virt_config._validate_virt_type()
            if virt_type not in VW_TYPES:
                self.assertIsNotNone(result)
            else:
                self.assertIsNone(result)
                value = self.virt_config.get('type')
                self.assertEqual(value, virt_type)

    def test_validate_missing_virt_type(self):
        """
        Test validation of missing type of virtualization backend
        """
        del self.virt_config['type']
        self.virt_config.validate()
        virt_type = self.virt_config.get('type')
        self.assertEqual(virt_type, 'libvirt')

    def test_validate_wrong_virt_type(self):
        """
        Test validation of wrong type of virtualization backend
        """
        self.virt_config['type'] = 'qemu'
        result = self.virt_config._validate_virt_type()
        self.assertIsNotNone(result)
        self.virt_config.validate()
        virt_type = self.virt_config.get('type')
        self.assertEqual(virt_type, 'libvirt')

    def test_validate_unencrypted_password(self):
        """
        Test of validation of password that is not encrypted
        """
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNone(result)

    def test_validate_unicode_unencrypted_password(self):
        """
        Test of validation of password that is not encrypted and it contains some
        UTF-8 string.
        """
        self.virt_config['password'] = 'Příšerně žluťoučký kůň pěl úděsné ódy.'
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNone(result)

    def mock_pwd_file(self):
        f, filename = tempfile.mkstemp()
        self.addCleanup(os.unlink, filename)
        Password.KEYFILE = filename
        Password._can_write = MagicMock(retun_value=True)

    def test_validate_encrypted_password(self):
        """
        Test of validation of encrypted password
        """
        self.mock_pwd_file()
        # Safe current password
        password = self.virt_config['password']
        # Delete unencrypted password first
        del self.virt_config['password']
        # Set up encrypted password
        self.virt_config['encrypted_password'] = hexlify(Password.encrypt(password))
        # Do own testing here
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNone(result)
        decrypted_password = self.virt_config.get('password')
        self.assertEqual(password, decrypted_password)

    def test_validate_missing_encrypted_password(self):
        """
        Test of validation of missing encrypted password
        """
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNotNone(result)

    def test_validate_wrong_encrypted_password(self):
        """
        Test of validation of corrupted encrypted password
        """
        self.mock_pwd_file()
        # Safe current password
        password = self.virt_config['password']
        # Delete unencrypted password first
        del self.virt_config['password']
        # Set up corrupted encrypted password
        encrypted_pwd = Password.encrypt(password)
        corrupted_encrypted_pwd = 'S' + encrypted_pwd[1:]
        self.virt_config['encrypted_password'] = hexlify(corrupted_encrypted_pwd)
        # Do own testing here
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNone(result)
        decrypted_password = self.virt_config.get('password')
        self.assertNotEqual(password, decrypted_password)

    def test_validate_correct_username(self):
        """
        Test of validation of username (it has to include only latin1 characters)
        """
        result = self.virt_config._validate_username('username')
        self.assertIsNone(result)

    def test_validate_missing_username(self):
        """
        Test of validation of missing username
        """
        del self.virt_config['username']
        result = self.virt_config._validate_username('username')
        self.assertIsNotNone(result)

    def test_validate_wrong_username(self):
        """
        Test validation of wrong username (containing e.g. UTF-8 string)
        """
        # First, change username to something exotic ;-)
        self.virt_config['username'] = u'Jiří'
        result = self.virt_config._validate_username('username')
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
        del self.virt_config['server']
        # Test all of them
        for virt_type in virt_backends_requiring_server:
            self.virt_config['type'] = virt_type
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
        del self.virt_config['server']
        # Test all of vm backend types
        for virt_type in virt_backends_not_requiring_server:
            self.virt_config['type'] = virt_type
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
        result = self.virt_config._validate_filter('filter_hosts')
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
        # We need to set values using this way, because we need
        # to trigger __setitem__ of global_config
        for key, value in GLOBAL_SECTION_VALUES.items():
            self.global_config[key] = value

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
        self.global_config['interval'] = '10'
        result = self.global_config._validate_interval()
        self.assertIsNotNone(result)
        interval = self.global_config.get('interval')
        self.assertEqual(interval, MinimumSendInterval)

    def test_validate_missing_interval(self):
        """
        Test validation of wrong time interval
        """
        self.global_config = GlobalSection('global', None)
        for key, value in GLOBAL_SECTION_VALUES.items():
            if key != 'interval':
                self.global_config[key] = value
        result = self.global_config._validate_interval()
        self.assertIsNone(result)
        interval = self.global_config['interval']
        self.assertEqual(interval, DefaultInterval)

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
        print(validate_messages)
        expected_results = [
            ('warning', 'Ignoring unknown configuration option "wrong_bool_value"'),
            ('warning', 'log_per_config must be a valid boolean, using default. See man virt-who-config for more info'),
            ('warning', 'Value for reporter_id not set, using default'),
            ('warning', 'Value for log_dir not set, using default'),
            ('warning', 'background must be a valid boolean, using default. See man virt-who-config for more info')
        ]
        self.assertGreater(len(validate_messages), 0)
        # self.assertEqual(expected_results, validate_messages)

    def test_validate_default_value(self):
        """
        Test the validate method will set default value, when an option
        is missing and default value exist in DEFAULT
        """
        self.global_config.validate()
        default_value = self.global_config.get('log_dir')
        self.assertEqual(default_value, DEFAULT_LOG_DIR)


MY_SECTION_VALUES = {
    'my_str': 'foo',
    'my_bool': False,
    'my_list': ['cat', 'dog', 'frog'],
    'must_have': 'bar'
}


class MyConfigSection(ConfigSection):
    """
    Example of ConfigSection subclass used for unit testing
    """

    DEFAULTS = (
        ('my_str', 'bar'),
        ('my_bool', True),
        ('my_list', None)
    )

    REQUIRED = (
        'must_have',
    )

    def _validate(self):
        """
        Method used for validation of values
        """
        validation_messages = []
        # Validate those keys that need to be validated
        for key in set(self._unvalidated_keys):
            error = None
            if key in ('my_str', 'must_have'):
                error = self._validate_non_empty_string(key)
            elif key == 'my_bool':
                error = self._validate_str_to_bool(key)
            elif key == 'my_list':
                error = self._validate_list(key)
            else:
                # We must not know of this parameter for the VirtConfigSection
                validation_messages.append(
                    (
                        'warning',
                        'Ignoring unknown configuration option "%s" in: %s' % (key, self.name)
                    )
                )
                del self._values[key]
            if error is not None:
                validation_messages.append(error)
                self._invalid_keys.add(key)
            self._unvalidated_keys.remove(key)

        self.validation_messages.extend(validation_messages)


class TestConfigSection(TestBase):
    """
    Class used for testing og ConfigSection
    """

    def setUp(self):
        """
        This method is executed before each unit test
        """
        self.my_config = MyConfigSection('my_section', None)
        # Fill config with some values
        for key, value in MY_SECTION_VALUES.items():
            self.my_config[key] = value

    def test_validate_simple(self):
        """
        Test validation, when all values are set properly (in setUp)
        """
        self.assertEqual(self.my_config.state, ValidationState.NEEDS_VALIDATION)
        result = self.my_config.validate()
        self.assertEqual(self.my_config.name, 'my_section')
        self.assertEqual(result, [])
        self.assertEqual(dict(self.my_config), MY_SECTION_VALUES)
        self.assertEqual(self.my_config.state, ValidationState.VALID)
        self.assertEqual(self.my_config._unvalidated_keys, set())
        self.assertEqual(self.my_config._invalid_keys, set())

    def test_validate_required_option(self):
        """
        Test validation, when required option is missing
        """
        del self.my_config['must_have']
        result = self.my_config.validate()
        expected_results = [
            (
                'error',
                'Required option: "must_have" is missing in: my_section'
            )
        ]
        self.assertEqual(result, expected_results)

    def test_validate_no_options(self):
        """
        Test validation, when there are no options
        """
        self.my_config = MyConfigSection('my_section', None)
        result = self.my_config.validate()
        expected_results = [
            (
                'warning',
                'No values provided in: my_section'
            ),
            (
                'error',
                'Required option: "must_have" is missing in: my_section'
            )
        ]
        self.assertEqual(result, expected_results)
        self.assertEqual(dict(self.my_config), dict(self.my_config.DEFAULTS))

    def test_validate_unsupported_option(self):
        """
        Test validation, when there is one more option
        """
        self.my_config['unsupported_opt'] = 'foo'
        result = self.my_config.validate()
        expected_result = [
            (
                'warning',
                'Ignoring unknown configuration option "unsupported_opt" in: my_section'
            )
        ]
        self.assertEqual(result, expected_result)
        self.assertEqual(self.my_config.state, ValidationState.VALID)

    def test_validate_missing_options_with_default_value(self):
        """
        Test validation, when there is mission option that has defined default value
        """
        self.my_config = MyConfigSection('my_section', None)
        # Add required option and one with default value
        self.my_config['must_have'] = 'foo'
        # Add one option with default value, but not other options
        self.my_config['my_bool'] = True
        result = self.my_config.validate()
        expected_result = [
            ('warning', 'Value for my_list not set in: my_section, using default: None'),
            ('warning', 'Value for my_str not set in: my_section, using default: bar'),
            ('warning', 'Value for my_bool not set in: my_section, using default: True')
        ]
        self.assertEqual(result, expected_result)
        self.assertEqual(self.my_config['my_str'], 'bar')
        self.assertEqual(self.my_config.state, ValidationState.VALID)

    def test_validate_wrong_bool_option_with_default_value(self):
        """
        Test validation, when there is wrong bool option that has defined default value
        """
        self.my_config['my_bool'] = 'nein'
        result = self.my_config.validate()
        expected_result = [
            (
                'warning',
                'my_bool must be a valid boolean, using default. See man virt-who-config for more info'
            )
        ]
        self.assertEqual(result, expected_result)
        self.assertEqual(self.my_config['my_bool'], True)
        self.assertEqual(self.my_config.state, ValidationState.VALID)

# -*- coding: utf-8 -*-
from __future__ import print_function

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
Test validating of GlobalSection.
"""

from base import TestBase

from virtwho.config import GlobalSection, str_to_bool, MinimumSendInterval, DefaultInterval
from virtwho.log import DEFAULT_LOG_DIR

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


class TestGlobalConfigSection(TestBase):
    """
    Test base for testing class GlobalSection
    """

    def setUp(self):
        self.init_global_config_section()

    def init_global_config_section(self):
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
        self.assertIs(value, True)

    def test_validate_oneshot_value_string_true(self):
        """
        Test validating of correct bool value stored as string ('true') 
        """
        result = self.global_config._validate_str_to_bool('oneshot')
        self.assertIsNone(result)
        value = self.global_config.get('oneshot')
        self.assertIs(value, True)

    def test_validate_print_value_string_false(self):
        """
        Test validating of correct bool value stored as string ('false') 
        """
        result = self.global_config._validate_str_to_bool('print')
        self.assertIsNone(result)
        value = self.global_config.get('print')
        self.assertIs(value, False)

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
        result = self.global_config._validate_interval('interval')
        self.assertIsNone(result)

    def test_validate_wrong_interval(self):
        """
        Test validation of wrong time interval
        """
        self.global_config['interval'] = '10'
        self.global_config.validate()
        interval = self.global_config.get('interval')
        # The behavior of this has changed. We now replace any invalid value with the default
        # No special cases
        self.assertIs(interval, DefaultInterval)

    def test_validate_missing_interval(self):
        """
        Test validation of wrong time interval
        """
        self.global_config = GlobalSection('global', None)
        for key, value in GLOBAL_SECTION_VALUES.items():
            if key != 'interval':
                self.global_config[key] = value
        result = self.global_config._validate_interval('interval')
        self.assertIsNotNone(result)
        interval = self.global_config['interval']
        self.assertIs(interval, DefaultInterval)

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
        # TODO: use following expected messages, when format of warning/error messages will be settled down.
        # expected_results = [
        #     ('warning', 'Ignoring unknown configuration option "wrong_bool_value"'),
        #     (
        #         'warning',
        #         'log_per_config must be a valid boolean, using default. See man virt-who-config for more info'
        #     ),
        #     ('warning', 'Value for reporter_id not set, using default'),
        #     ('warning', 'Value for log_dir not set, using default'),
        # ]
        self.assertGreater(len(validate_messages), 0)
        # self.assertEqual(expected_results, validate_messages)

    def test_validate_default_value(self):
        """
        Test the validate method will set default value, when an option
        is missing and default value exist in DEFAULT
        """
        self.global_config.validate()
        default_value = self.global_config.get('log_dir')
        self.assertIs(default_value, DEFAULT_LOG_DIR)

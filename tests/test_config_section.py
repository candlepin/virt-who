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

from virtwho.config import ConfigSection, ValidationState

MY_SECTION_NAME = 'my_section'

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
    Class used for testing of ConfigSection
    """

    def __init__(self, *args, **kwargs):
        super(TestConfigSection, self).__init__(*args, **kwargs)
        self.my_config = None

    def init_config_section(self):
        """
        This method is executed before each unit test
        """
        self.my_config = MyConfigSection(MY_SECTION_NAME, None)
        # Fill config with some values
        for key, value in MY_SECTION_VALUES.items():
            self.my_config[key] = value

    def test_validate_simple(self):
        """
        Test validation, when all values are set properly (in setUp)
        """
        self.init_config_section()
        self.assertEqual(self.my_config.state, ValidationState.NEEDS_VALIDATION)
        result = self.my_config.validate()
        self.assertEqual(self.my_config.name, MY_SECTION_NAME)
        self.assertEqual(result, [])
        self.assertEqual(dict(self.my_config), MY_SECTION_VALUES)
        self.assertEqual(self.my_config.state, ValidationState.VALID)
        self.assertEqual(self.my_config._unvalidated_keys, set())
        self.assertEqual(self.my_config._invalid_keys, set())

    def test_validate_required_option(self):
        """
        Test validation, when required option is missing
        """
        self.init_config_section()
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
        self.my_config = MyConfigSection(MY_SECTION_NAME, None)
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
        self.init_config_section()
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
        self.init_config_section()
        self.my_config = MyConfigSection(MY_SECTION_NAME, None)
        # Add required option and one with default value
        self.my_config['must_have'] = 'foo'
        # Add one option with default value, but not other options
        self.my_config['my_bool'] = True
        result = self.my_config.validate()
        expected_result = [
            ('warning', 'Value for my_list not set in: my_section, using default: None'),
            ('warning', 'Value for my_str not set in: my_section, using default: bar'),
        ]
        self.assertEqual(result, expected_result)
        self.assertEqual(self.my_config['my_str'], 'bar')
        self.assertEqual(self.my_config.state, ValidationState.VALID)

    def test_validate_wrong_bool_option_with_default_value(self):
        """
        Test validation, when there is wrong bool option that has defined default value
        """
        self.init_config_section()
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

    def test_update_values(self):
        """
        Test updating values
        """
        my_config = MyConfigSection(MY_SECTION_NAME, None)
        my_config.update(**MY_SECTION_VALUES)
        for key, value in my_config.items():
            self.assertEqual(value, MY_SECTION_VALUES[key])

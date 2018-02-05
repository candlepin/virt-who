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
Test validating of configuration values.
"""

from base import TestBase
from mock import Mock
import six
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

    def __init__(self, *args, **kwargs):
        super(MyConfigSection, self).__init__(*args, **kwargs)
        self.add_key(key='my_str', validation_method=self._validate_non_empty_string,
                     default='bar')
        self.add_key(key='my_bool', validation_method=self._validate_str_to_bool, default=True)
        self.add_key(key='must_have', validation_method=lambda *args: None,
                     required=True)
        self.add_key(key="my_list", validation_method=self._validate_list, default=[])


class TestConfigSection(TestBase):
    """
    Class used for testing of ConfigSection
    """
    __marker = object()

    def __init__(self, *args, **kwargs):
        super(TestConfigSection, self).__init__(*args, **kwargs)
        self.my_config = None

    def setUp(self):
        self.init_config_section()

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
        Test validation, when required option is missing (with no default)
        """
        del self.my_config['must_have']
        result = self.my_config.validate()
        expected_results = [
            (
                'error',
                'Required option: "must_have" not set.'
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
                'Required option: "must_have" not set.'
            )
        ]
        self.assertEqual(result, expected_results)
        self.assertEqual(dict(self.my_config), dict(self.my_config.defaults))

    def test_validate_unsupported_option(self):
        """
        Test validation, when there is one more option
        """
        self.my_config['unsupported_opt'] = 'foo'
        result = self.my_config.validate()
        expected_result = [
            (
                'warning',
                'Ignoring unknown configuration option "unsupported_opt"'
            )
        ]
        self.assertEqual(result, expected_result)
        self.assertEqual(self.my_config.state, ValidationState.VALID)

    def test_validate_missing_options_with_default_value(self):
        """
        Test validation, when there is mission option that has defined default value
        """
        self.my_config = MyConfigSection(MY_SECTION_NAME, None)
        # Add required option and one with default value
        self.my_config['must_have'] = 'foo'
        # Add one option with default value, but not other options
        self.my_config['my_bool'] = True
        result = self.my_config.validate()
        expected_result = [
            ('warning', 'Value for "my_list" not set, using default: []'),
            ('warning', 'Value for "my_str" not set, using default: bar'),
        ]
        # We do not particularly care about the ordering here, just that the lists contain the same
        # elements.
        six.assertCountEqual(self, result, expected_result)
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
            ),
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

    # ---------- ADD_KEY AND RELATED VALIDATION TESTS ----------------------------------
    # Note about the below tests:
    # Some of the functionality of ConfigSection.validate (and add_key) is dependant on the
    # values returned by the validation_method given. Also, at present, some of the
    # validation_methods used in subclasses modify the values of the containing class (by
    # accessing _values etc). In my opinion this should stop.
    # Current behaviour for a validation_method is:
    #    take in (self, key)
    #    return None (if things are ok) OR a tuple (or list of tuples) of (log_level,
    #        presumably_error_message)
    #
    # Ideal future behaviour:
    #    Take in all params as kwargs only
    #        the ConfigSection can pass the current values as 'values'
    #    return a KeyValidationResult
    #        which has a known set of attributes that are set (including state to indicate what
    #        to do with the particular value)

    def test_add_key_no_validation_method(self):
        # Tests that given a key and nothing else, add_key fails
        config = ConfigSection('test', None)
        self.assertRaises(AttributeError, config.add_key, key='test')

    def test_add_key_destination(self):
        # Tests add_key with a key, destination (and validation_method) given
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        # The below should not blow up
        config.add_key(key='test_key', validation_method=mock_validate_method,
                       destination='test_key_dest')
        test_values = {'test_key': 'test_key_value'}
        config.update(**test_values)
        config.validate()
        # The validate_method should have been called with the ConfigSection and the key
        mock_validate_method.assert_called_once_with('test_key')
        self.assertNotIn('test_key', config, "The config contains the original test_key, "
                                             "should be removed post validate")
        self.assertIn('test_key_dest', config, "The config does not contain a value at the "
                                               "destination specified in the add_key call")
        self.assertEqual(config['test_key_dest'], test_values['test_key'])
        self.assertEqual(config.state, ValidationState.VALID)

    def test_add_key_required(self):
        # Tests add_key with a key, destination (and validation_method) given
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        # The below should not blow up
        config.add_key(key='test_key', validation_method=mock_validate_method, required=True)
        test_values = {'test_key': 'test_key_value'}
        config.update(**test_values)
        config.validate()
        # The validate_method should have been called with the key (bound methods would also have
        #  been passed the config section as the first arg)
        # FIXME This seems broken, we should let folks add functions that are not bound to the
        # class instance as validation_methods
        mock_validate_method.assert_called_once_with('test_key')
        self.assertIn('test_key', config, "The config does not contain the test_key, deleted by "
                                          "accident?")
        self.assertEqual(config['test_key'], test_values['test_key'])
        self.assertEqual(config.state, ValidationState.VALID)

    def test_add_key_required_missing(self):
        # Tests add_key with a key, destination (and validation_method) given
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        # The below should not blow up
        config.add_key(key='test_key', validation_method=mock_validate_method, required=True)
        test_values = {'test_key_different': 'test_key_different_value'}
        config.update(**test_values)
        config.validate()
        # The validate_method should not have been called (the associated key was not included)
        mock_validate_method.assert_not_called()
        self.assertNotIn('test_key', config, "The 'test_key' was added mistakenly somehow")
        self.assertEqual(config.state, ValidationState.INVALID)

    def test_add_key_default_no_value_provided(self):
        # Tests that a key added with a default uses that default, when not provided a value for
        # the same.
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        config.add_key(key='test_key', validation_method=mock_validate_method,
                       default="test_key_default")
        config.validate()
        # We only run the validation_methods on keys that are set (not on the defaults)
        mock_validate_method.assert_not_called()
        self.assertIn('test_key', config, "The default value was not added (check "
                                          "reset_to_defaults?)")
        # The value returned by the config should be that set as the default
        self.assertEqual(config['test_key'], "test_key_default")

    def test_add_key_default_valid_value_provided(self):
        # Tests that a key added with a default DOES NOT USE that default, when the provided
        # value is valid
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        config.add_key(key='test_key', validation_method=mock_validate_method,
                       default="test_key_default")
        values = {'test_key': 'test_key_value'}
        config.update(values)
        config.validate()
        mock_validate_method.assert_called_once_with('test_key')
        self.assertIn('test_key', config)
        # The value returned by the config should still be the valid one given it
        self.assertEqual(config['test_key'], "test_key_value")
        self.assertEqual(config.state, ValidationState.VALID)

    def test_add_key_default_invalid_value_provided(self):
        # Tests that a key added with a default DOES NOT USE that default
        # when an invalid value is given as the value to be validated
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning something (normally a tuple of (log_level, error_message)) from a validation
        # method with the log_level of 'error' means that the key is invalid
        # TODO Create a more meaningful way of validating values (and presenting messages about
        # validation to the user)
        mock_validate_method.return_value = ('error', 'THIS IS A BAD WAY TO GO...')
        config.add_key(key='test_key', validation_method=mock_validate_method,
                       default="test_key_default")
        values = {'test_key': 'PRETEND_BAD_VALUE'}
        config.update(values)
        config.validate()
        mock_validate_method.assert_called_once_with('test_key')
        self.assertIn('test_key', config)
        # The value that the invalid config holds on to should be the one that was provided,
        # NOT the default (which we assume is good to use)
        self.assertEqual(config['test_key'], values['test_key'])
        self.assertEqual(config.state, ValidationState.INVALID)

    def test_add_key_default_required_no_value_provided(self):
        # Tests that the config is still considered valid when a required key is not provided (
        # but has a default)
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        mock_validate_method.return_value = None
        config.add_key(key='test_key', validation_method=mock_validate_method, required=True,
                       default='test_key_default')
        config.validate()
        # Not given a value to chew on, don't try to chew on it
        mock_validate_method.assert_not_called()
        self.assertIn('test_key', config, "The config is missing the required, defaulted value ("
                                          "check reset_to_defaults?)")
        self.assertEqual(config['test_key'], 'test_key_default')
        self.assertEqual(config.state, ValidationState.VALID, "Check _unvalidated_keys, "
                                                              "_invalid_keys, _missing_required, "
                                                              "and _update_state()")

    def test_add_key_destination_required_valid_value(self):
        # Tests add_key with a key, destination (and validation_method) given that the key is
        # required
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        # The below should not blow up
        config.add_key(key='test_key', validation_method=mock_validate_method,
                       destination='test_key_dest', required=True)
        test_values = {'test_key': 'test_key_value'}
        config.update(**test_values)
        config.validate()
        mock_validate_method.assert_called_once_with('test_key')
        self.assertNotIn('test_key', config, "The config contains the original test_key, "
                                             "should be removed post validate")
        self.assertIn('test_key_dest', config, "The config does not contain a value at the "
                                               "destination specified in the add_key call")
        self.assertEqual(config['test_key_dest'], test_values['test_key'])
        self.assertEqual(config.state, ValidationState.VALID)

    def test_add_key_destination_invalid_value(self):
        # Tests add_key with a key, destination (and validation_method) given that the key is
        # required
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = ('error', 'THIS IS A TERRIBLE IDEA...')
        # The below should not blow up
        config.add_key(key='test_key', validation_method=mock_validate_method,
                       destination='test_key_dest')
        test_values = {'test_key': 'test_key_value'}
        config.update(**test_values)
        config.validate()
        mock_validate_method.assert_called_once_with('test_key')
        self.assertNotIn('test_key_dest', config, "The config has a value for the destination, "
                                                  "despite the value being invalid")
        self.assertEqual(config.state, ValidationState.INVALID)

    def test_add_key_validation_method(self):
        # The most minimal use of add_key
        # Verifies that the standard validate method does what is dictated by add_key in
        # the minimal case.
        config = ConfigSection('test', None)
        mock_validate_method = Mock()
        # Returning nothing from a validation_method means that the key's value is valid
        # TODO Don't be magical with the return values
        mock_validate_method.return_value = None
        # The below should not blow up
        config.add_key(key='test_key', validation_method=mock_validate_method)
        test_values = {'test_key': 'test_key_value'}
        config.update(**test_values)
        config.validate()
        # The validate_method should have been called with the ConfigSection and the key
        mock_validate_method.assert_called_once_with('test_key')
        self.assertIn('test_key', config, "The config does not contain the test_key, deleted by "
                                          "accident?")
        self.assertEqual(config['test_key'], test_values['test_key'])
        self.assertEqual(config.state, ValidationState.VALID)

    def _run_add_key_test(self, key, input_value=__marker, expected_value=__marker, add_key_kwargs=None,
                          expected_in=True,
                          expected_state=ValidationState.VALID,
                          validation_return_val=None,
                          expected_present_in_messages=True):
        if not add_key_kwargs:
            add_key_kwargs = {}

        # Provide mock validation_method if one is not given
        if 'validation_method' not in add_key_kwargs:
            add_key_kwargs['validation_method'] = Mock()
            add_key_kwargs['validation_method'].return_value = validation_return_val

        config = ConfigSection('test', None)

        config.add_key(key, **add_key_kwargs)

        # Only update the values in the config section if we've been given an input value
        if input_value is not self.__marker:
            test_values = {key: input_value}
            config.update(**test_values)

        messages = config.validate()

        # Assert the mock was called, if it was a mock (and we passed in an input_value
        if input_value is not self.__marker and \
                hasattr(add_key_kwargs['validation_method'], 'assert_called_once_with'):
            add_key_kwargs['validation_method'].assert_called_once_with(key)

        if expected_in:
            self.assertIn(key, config, "The config does not contain the expected key")

        if expected_value is not self.__marker:
            self.assertEqual(config[key], expected_value, 'Expected key "%s" to be "%s" found "%s"' % (key, expected_value, config[key]))

        if expected_present_in_messages:
            self.assertTrue(any(key in message[1] for message in messages), 'Expected at least one mention of key "%s" in validation messages' % key)
        else:
            bad_messages = []
            for message in messages:
                if key in message[1]:
                    bad_messages.append(message)
            if bad_messages:
                self.fail("Expected no mention of key '%s' in messages found: %s" % (key, bad_messages))

        self.assertEqual(config.state, expected_state)
        return config, messages

    def test_add_key_restricted_with_default(self):
        # Tests that a key added as restricted is not mentioned in validation output
        # Restricted keys are meant to be included in the validation process but are not mentioned
        # when missing with a default.
        add_key_kwargs = {
            'default': "default",
            'restricted': True,
        }
        self._run_add_key_test('test_key', add_key_kwargs=add_key_kwargs,
                               expected_value=add_key_kwargs['default'],
                               expected_present_in_messages=False
                               )
        # Now with a value provided
        self._run_add_key_test('test_key', add_key_kwargs=add_key_kwargs,
                               expected_in=True, input_value='input',
                               expected_value='input',
                               expected_present_in_messages=False
                               )

    def test_add_key_restricted_and_required(self):
        # Tests that a key added as restricted is not mentioned in validation output
        # Restricted keys are meant to be included in the validation process but are not mentioned
        # when missing with a default.
        no_default = dict(
                restricted=True,
                required=True,
        )
        with_default = dict(
                restricted=True,
                required=True,
                default="default"
        )
        # Tuples of args
        cases = [
            # No input_value given, and no default
            dict(
                add_key_kwargs=no_default,
                expected_in=False,
                expected_state=ValidationState.INVALID,
                expected_present_in_messages=True,
            ),
            # A value given, expect the same value, no default
            dict(
                add_key_kwargs=no_default,
                input_value='value',
                expected_value='value',
                expected_state=ValidationState.VALID,
                expected_present_in_messages=False,
            ),
            # Default given, no input value, expect default value
            dict(
                add_key_kwargs=with_default,
                expected_value=with_default['default'],
                expected_state=ValidationState.VALID,
                expected_present_in_messages=False,
            ),
            # Default given, with an input, expect input value
            dict(
                add_key_kwargs=with_default,
                input_value='value',
                expected_value='value',
                expected_state=ValidationState.VALID,
                expected_present_in_messages=False,
            ),
        ]

        for index, case in enumerate(cases):
            try:
                self._run_add_key_test('test_key', **case)
            except AssertionError:
                print("Assertion error during case #%s" % index)
                raise

from __future__ import print_function
"""
Basic module for tests,

Copyright (C) 2017 Radek Novacek <rnovacek@redhat.com>

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

import logging
from mock import patch, MagicMock
from virtwho.config import VirtConfigSection, ValidationState

# hack to use unittest2 on python <= 2.6, unittest otherwise
# based on python version
import sys
if sys.version_info[0] > 2 or sys.version_info[1] > 6:
    import unittest
else:
    import unittest2 as unittest


class TestBase(unittest.TestCase):
    @classmethod
    @patch('virtwho.log.getLogger')
    def setUpClass(cls, logger):
        cls.logger = logging.getLogger("")
        cls.logger.handlers = []
        cls.logger.setLevel(logging.CRITICAL)
        logger.return_value = cls.logger

    @staticmethod
    def create_fake_config(name, **kwargs):
        # Used to create a fake config with a given name
        # All kwargs that are given will be used as the values provided by the config
        mock_config = MagicMock(spec=VirtConfigSection)
        mock_config.name = name
        mock_config.__getitem__.side_effect = kwargs.__getitem__
        mock_config.__setitem__.side_effect = kwargs.__setitem__
        # Returns the mock_config and the dictionary that underlies it (useful for modifying the
        # contents of the config, without messing up the expected call stack of the mock_config
        return mock_config, kwargs


class ConfigSectionValidationTests(object):
    """
    This is a group of tests which are meant to test that a config section subclass ends up in the
    correct state, after validation, given various inputs.

    Can be used as a mixin to add these tests to any suite (that has valid values for the required
    class attributes).

    This is not a test case itself as we do not expect these tests to pass as written without a
    specific backend CONFIG_CLASS.
    """

    # A dictionary of valid configuration values
    VALID_CONFIG = {}

    # Should be changed for each set of tests, to make sure the right class is utilized
    CONFIG_CLASS = VirtConfigSection

    # should be a list of the keys which are required for sam destination
    SAM_REQUIRED_KEYS = set()

    # should be a list of the keys which are required for sam destination
    SAT5_REQUIRED_KEYS = set()

    # Those keys that should have a default (along with their expected default value)
    DEFAULTS = {}

    def _modified_dict(self, values, excluding=None, including=None):
        """
        Copies a dict removing values where necessary
        Args:
            values: a dict of values to take from
            excluding: a list or set of items to exclude from the copied dict
            including: a list or set of items to include from the copied dict (wins over exclude)

        Returns: a copied and modified dict

        """
        if excluding is None:
            excluding = set()
        if isinstance(excluding, list):
            excluding = set(excluding)

        if including is None:
            including = set()
        if isinstance(including, list):
            including = set(including)

        excluding = excluding - including

        out = {}
        for key in list(values.keys()):
            if key in including or not including:
                out[key] = values[key]
            if key in out and (key in excluding or (including and key not in including)):
                del out[key]
        return out

    def test_valid_config(self):
        """
        This is essentially a smoke test to ensure the following:
        1) An instance of the correct class is created from the valid configuration info
        2) That the configuration is in the proper state pre and post validation
        """
        config = self.CONFIG_CLASS.from_dict(self.VALID_CONFIG, "test", None)

        self.assertIsInstance(config, self.CONFIG_CLASS, 'Wrong type of config, was "type" set'
                                                         'correctly in "VALID_CONFIG"?')

        # Having been updated, the config section needs validation
        self.assertEqual(config.state, ValidationState.NEEDS_VALIDATION)

        messages = config.validate()

        # The config state should be valid, post validation with valid config information
        self.assertEqual(config.state, ValidationState.VALID)

        # There should be no error messages if this config section is valid
        self.assertFalse(any(message[0] == 'error' for message in messages))

    def test_missing_sam_required_no_default(self):
        """
        This tests that when a required key, which has no default, is missing, the config section
        becomes invalid post-validation. This test is specific for SAM destination (candlepin server).
        """
        config = self.CONFIG_CLASS("test", None)
        # A sorted list of keys that are required, but have no default
        target_keys = sorted(list(self.SAM_REQUIRED_KEYS - set(self.DEFAULTS.keys())))
        config_values = self._modified_dict(self.VALID_CONFIG, excluding=target_keys)
        config.update(**config_values)

        messages = config.validate()

        if len(self.SAM_REQUIRED_KEYS) > 0:
            self.assertEqual(config.state, ValidationState.INVALID)
            self.assertTrue(any(message[0] == 'error' for message in messages))

    def test_missing_sat5_required_no_default(self):
        """
        This tests that when a required key, which has no default, is missing, the config section
        becomes invalid post-validation. This test is specific for satellite 5 destination
        """
        config = self.CONFIG_CLASS("test", None)
        # A sorted list of keys that are required, but have no default
        target_keys = sorted(list(self.SAT5_REQUIRED_KEYS - set(self.DEFAULTS.keys())))
        config_values = self._modified_dict(self.VALID_CONFIG, excluding=target_keys)
        config.update(**config_values)

        messages = config.validate()

        if len(self.SAT5_REQUIRED_KEYS) > 0:
            self.assertEqual(config.state, ValidationState.INVALID)
            self.assertTrue(any(message[0] == 'error' for message in messages))

    def test_missing_sam_required_with_default(self):
        """
        Test that a config section given a set of values which are valid other than missing required
        keys which have defaults, will be valid post validation, and that the values for the
        defaults are used.

        NOTE: This does not account for modifications of default values made during validation.
        """
        config = self.CONFIG_CLASS("test", None)
        target_keys = sorted(list(self.SAM_REQUIRED_KEYS & set(self.DEFAULTS.keys())))
        config_values = self._modified_dict(self.VALID_CONFIG, excluding=target_keys)
        config.update(**config_values)

        config.validate()

        self.assertEqual(config.state, ValidationState.VALID)

        for key in target_keys:
            self.assertIn(key, config, "Key '%s' is missing from config")
            self.assertEqual(config[key], self.DEFAULTS[key])

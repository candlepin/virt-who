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
Test effective config
"""

from base import TestBase
import os
import tempfile
import shutil
from virtwho.config import EffectiveConfig, ConfigSection, parse_file


CUSTOM_SECTION_NAME = 'my_test_section'


CUSTOM_SECTION_VALUES = {
    'type': 'custom_type',
    'my_str': 'foo',
    'another_str': 'pub',
    'my_bool': False,
    'my_list': ['cat', 'dog', 'frog'],
    'must_have': 'bar'
}

CONFIG_SECTION_TEXT = """
[{section_name}]
type=custom_type
my_str=foo
another_str=pub
my_bool=false
my_list=cat, dog, frog
must_have=bar
""".format(section_name=CUSTOM_SECTION_NAME)


class CustomConfigSection(ConfigSection):
    """
    Example of ConfigSection subclass used for unit testing
    """

    VIRT_TYPE = 'custom_type'

    DEFAULTS = (
        ('type', VIRT_TYPE),
        ('my_str', 'bar'),
        ('another_str', 'pub'),
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
            if key in ('my_str', 'another_str', 'must_have', 'type'):
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


class TestEffectiveConfig(TestBase):
    """
    Class used for testing EffectiveConfig
    """

    def __init__(self, *args, **kwargs):
        super(TestEffectiveConfig, self).__init__(*args, **kwargs)
        self.effective_config = None
        self.config_section = None

    def init_effective_config(self):
        """
        This method is executed before each unit test
        """
        self.effective_config = EffectiveConfig()
        self.config_section = CustomConfigSection(CUSTOM_SECTION_NAME, self.effective_config)
        # Fill config section with some values
        for key, value in CUSTOM_SECTION_VALUES.items():
            self.config_section[key] = value
        self.effective_config[CUSTOM_SECTION_NAME] = self.config_section

    def test_effective_config_validate(self):
        self.init_effective_config()
        validate_messages = self.effective_config.validate()
        self.assertEqual(validate_messages, [])

    def test_effective_config_is_valid(self):
        self.init_effective_config()
        self.effective_config.validate()
        is_valid = self.effective_config.is_valid()
        self.assertEqual(is_valid, True)

    def test_effective_config_virt_sections(self):
        self.init_effective_config()
        self.effective_config.validate()
        virt_sections = self.effective_config.virt_sections()
        self.assertEqual(len(virt_sections), 1)
        self.assertEqual(virt_sections[0][0], CUSTOM_SECTION_NAME)

    def test_effective_config_is_value_default(self):
        self.init_effective_config()
        self.effective_config.validate()
        result = self.effective_config.is_default(CUSTOM_SECTION_NAME, 'my_str')
        self.assertEqual(result, False)
        result = self.effective_config.is_default(CUSTOM_SECTION_NAME, 'another_str')
        self.assertEqual(result, True)

    def test_effective_config_items(self):
        self.init_effective_config()
        self.effective_config.validate()
        for key, item in self.effective_config.items():
            self.assertEqual(key, CUSTOM_SECTION_NAME)
            self.assertEqual(type(item), CustomConfigSection)

    def test_effective_config_del_item(self):
        self.init_effective_config()
        self.effective_config.validate()
        self.assertEqual(len(self.effective_config), 1)
        del self.effective_config[CUSTOM_SECTION_NAME]
        self.assertEqual(len(self.effective_config), 0)

    def test_effective_config_filter_params(self):
        effective_config = EffectiveConfig()
        desired_params = [
            'foo',
            'bar',
            'foo.bar'
        ]
        values = {
            'foo': 'Foo',
            'bar': 'Bar',
            'bar.foo': 'Bar Foo',
            'pub': 'Pub Foo'
        }
        matching, non_matching = effective_config.filter_parameters(desired_params, values)
        expected_matching = {'foo': 'Foo', 'bar': 'Bar'}
        expected_non_matching = {'bar.foo': 'Bar Foo', 'pub': 'Pub Foo'}
        self.assertEqual(matching, expected_matching)
        self.assertEqual(non_matching, expected_non_matching)

    def test_read_effective_config_from_file(self):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write(CONFIG_SECTION_TEXT)
        conf = parse_file(os.path.join(config_dir, "test.conf"))
        effective_config = EffectiveConfig()
        conf_values = conf.pop(CUSTOM_SECTION_NAME)
        effective_config[CUSTOM_SECTION_NAME] = ConfigSection.from_dict(
            conf_values,
            CUSTOM_SECTION_NAME,
            effective_config
        )
        self.assertEqual(type(effective_config[CUSTOM_SECTION_NAME]), CustomConfigSection)
        self.assertEqual(effective_config[CUSTOM_SECTION_NAME]['my_str'], 'foo')
        validate_messages = effective_config.validate()
        self.assertEqual(validate_messages, [])

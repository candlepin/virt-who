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
Test validating of HypervConfigSection
"""

import os
import tempfile

from functools import wraps

from base import ConfigSectionValidationTests, TestBase
from virtwho.config import ValidationState
from virtwho.virt.hyperv.hyperv import HypervConfigSection


def with_named_tempfile(func):
    @wraps(func)
    def inner(*args, **kwargs):
        f = tempfile.NamedTemporaryFile(delete=False)
        try:
            return func(*args, f.name, **kwargs)
        finally:
            os.unlink(f.name)
    return inner


class TestHyperVConfigSection(ConfigSectionValidationTests, TestBase):
    """
    A group of tests to ensure proper validation of HyperVConfigSections
    """
    CONFIG_CLASS = HypervConfigSection
    VALID_CONFIG = {
        "type": "hyperv",
        "server": "1.2.3.4",
        "username": "username",
        "password": "password",
        "owner": "admin",
    }

    SAM_REQUIRED_KEYS = {
        'type',
        'server',
        'username',
        'password',
        'owner',
    }

    SAT5_REQUIRED_KEYS = SAM_REQUIRED_KEYS - {'owner'}

    DEFAULTS = {
        'hypervisor_id': 'uuid',
        'sm_type': 'sam',
    }

    def test_auth_method_default_is_basic(self):
        """auth_method defaults to 'basic' when not specified."""
        config = self.CONFIG_CLASS.from_dict(self.VALID_CONFIG, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'basic')

    def test_auth_method_basic_requires_username_and_password(self):
        """auth_method=basic still requires username and password."""
        values = dict(self.VALID_CONFIG, auth_method='basic')
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.INVALID)
        self.assertEqual(config['auth_method'], 'basic')
        self.assertTrue(any('password' in msg[1].lower() and msg[0] == 'error' for msg in messages))

    def test_auth_method_basic_explicit_valid(self):
        """auth_method=basic with full credentials is valid."""
        values = dict(self.VALID_CONFIG, auth_method='basic')
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'basic')

    def test_auth_method_kerberos_valid_without_password(self):
        """auth_method=kerberos is valid without password."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')

    def test_auth_method_kerberos_valid_without_username(self):
        """auth_method=kerberos is valid without username."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        del values['username']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')

    def test_auth_method_kerberos_valid_without_username_and_password(self):
        """auth_method=kerberos is valid without both username and password."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')

    def test_auth_method_invalid_value(self):
        """Invalid auth_method yields a clear validation error."""
        values = dict(self.VALID_CONFIG, auth_method='ntlm')
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.INVALID)
        error_messages = [msg for msg in messages if msg[0] == 'error']
        self.assertGreater(len(error_messages), 0)
        self.assertTrue(any('auth_method' in msg[1] for msg in error_messages))

    def test_auth_method_wired_through_config(self):
        """auth_method appears in the config dict after validation."""
        for auth_method in ('basic', 'kerberos'):
            values = dict(self.VALID_CONFIG, auth_method=auth_method)
            config = self.CONFIG_CLASS.from_dict(values, "test", None)
            config.validate()
            self.assertIn('auth_method', config)
            self.assertEqual(config['auth_method'], auth_method)

    def test_auth_method_kerberos_server_still_required(self):
        """auth_method=kerberos still requires server."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        del values['server']
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.INVALID)
        self.assertEqual(config['auth_method'], 'kerberos')

    def test_kerberos_warns_when_username_provided(self):
        """auth_method=kerberos warns that username is ignored."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertTrue(
            any('username' in msg[1].lower() and 'ignored' in msg[1].lower()
                for msg in messages if msg[0] == 'warning')
        )

    def test_kerberos_warns_when_password_provided(self):
        """auth_method=kerberos warns that password is ignored."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertTrue(
            any('password' in msg[1].lower() and 'ignored' in msg[1].lower()
                for msg in messages if msg[0] == 'warning')
        )

    def test_kerberos_no_credential_warning_when_absent(self):
        """auth_method=kerberos produces no ignored-credential warning when creds absent."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertFalse(
            any('ignored' in msg[1].lower() for msg in messages if msg[0] == 'warning')
        )

    def test_kerberos_principal_accepted(self):
        """kerberos_principal is accepted when auth_method=kerberos."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos',
                      kerberos_principal='virtwho@EXAMPLE.COM')
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertEqual(config['kerberos_principal'], 'virtwho@EXAMPLE.COM')

    def test_kerberos_principal_ignored_with_basic(self):
        """kerberos_principal with auth_method=basic produces a warning and is removed."""
        values = dict(self.VALID_CONFIG, auth_method='basic',
                      kerberos_principal='virtwho@EXAMPLE.COM')
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'basic')
        self.assertTrue(
            any('kerberos_principal' in msg[1] and 'ignoring' in msg[1].lower()
                for msg in messages if msg[0] == 'warning')
        )
        self.assertNotIn('kerberos_principal', config)

    def test_kerberos_principal_empty_string_is_error(self):
        """Empty kerberos_principal is an error."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos',
                      kerberos_principal='')
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.INVALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertTrue(any('kerberos_principal' in msg[1] and msg[0] == 'error' for msg in messages))

    @with_named_tempfile
    def test_kerberos_keytab_valid_file(self, keytab_path):
        """kerberos_keytab with a readable file is accepted."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos',
                      kerberos_keytab=keytab_path)
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertEqual(config['kerberos_keytab'], keytab_path)

    def test_kerberos_keytab_nonexistent_file_is_error(self):
        """kerberos_keytab pointing to a missing file is an error."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos',
                      kerberos_keytab='/no/such/file.keytab')
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.INVALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertTrue(any('kerberos_keytab' in msg[1] and msg[0] == 'error' for msg in messages))

    @with_named_tempfile
    def test_kerberos_keytab_ignored_with_basic(self, keytab_path):
        """kerberos_keytab with auth_method=basic produces a warning and is removed."""
        values = dict(self.VALID_CONFIG, auth_method='basic',
                      kerberos_keytab=keytab_path)
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        messages = config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'basic')
        self.assertTrue(
            any('kerberos_keytab' in msg[1] and 'ignoring' in msg[1].lower()
                for msg in messages if msg[0] == 'warning')
        )
        self.assertNotIn('kerberos_keytab', config)

    def test_kerberos_keytab_optional(self):
        """kerberos_keytab is optional even when auth_method=kerberos."""
        values = dict(self.VALID_CONFIG, auth_method='kerberos')
        del values['username']
        del values['password']
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')

    @with_named_tempfile
    def test_full_kerberos_config(self, keytab_path):
        """Full kerberos config with keytab and principal validates."""
        values = {
            "type": "hyperv",
            "server": "hyperv.example.com",
            "auth_method": "kerberos",
            "kerberos_keytab": keytab_path,
            "kerberos_principal": "virtwho@EXAMPLE.COM",
            "owner": "1234567",
        }
        config = self.CONFIG_CLASS.from_dict(values, "test", None)
        config.validate()
        self.assertEqual(config.state, ValidationState.VALID)
        self.assertEqual(config['auth_method'], 'kerberos')
        self.assertEqual(config['kerberos_keytab'], keytab_path)
        self.assertEqual(config['kerberos_principal'], 'virtwho@EXAMPLE.COM')

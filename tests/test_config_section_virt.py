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
Test validating of VirtConfigSection
"""

from base import TestBase
from mock import MagicMock

import tempfile
import os
from binascii import hexlify

from virtwho.config import VirtConfigSection, VW_TYPES
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


class TestVirtConfigSection(TestBase):
    """
    Test base for testing class VirtConfigSection
    """

    def __init__(self, *args, **kwargs):
        super(TestVirtConfigSection, self).__init__(*args, **kwargs)
        self.virt_config = None

    def init_virt_config_section(self):
        """
        Method executed before each unit test
        """
        self.virt_config = VirtConfigSection('test_libvirt', None)
        # We need to set values using this way, because we need
        # to trigger __setitem__ of virt_config
        for key, value in LIBVIRT_SECTION_VALUES.items():
            self.virt_config[key] = value

    def test_validate_virt_type(self):
        """
        Test validation of supported types of virtualization backends
        """
        self.init_virt_config_section()
        test_virt_types = list(VW_TYPES[:])
        test_virt_types.extend(['vmware,' 'kvm'])
        for virt_type in test_virt_types:
            self.virt_config['type'] = virt_type
            result = self.virt_config._validate_virt_type('type')
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
        self.init_virt_config_section()
        del self.virt_config['type']
        self.virt_config.validate()
        virt_type = self.virt_config.get('type')
        self.assertEqual(virt_type, 'libvirt')

    def test_validate_wrong_virt_type(self):
        """
        Test validation of wrong type of virtualization backend
        """
        self.init_virt_config_section()
        self.virt_config['type'] = 'qemu'
        result = self.virt_config._validate_virt_type('type')
        self.assertIsNotNone(result)
        self.virt_config.validate()
        virt_type = self.virt_config.get('type')
        self.assertEqual(virt_type, 'libvirt')

    def test_validate_unencrypted_password(self):
        """
        Test of validation of password that is not encrypted
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNone(result)

    def test_validate_unicode_unencrypted_password(self):
        """
        Test of validation of password that is not encrypted and it contains some
        UTF-8 string.
        """
        self.init_virt_config_section()
        self.virt_config['password'] = 'Příšerně žluťoučký kůň pěl úděsné ódy.'
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNone(result)

    def mock_pwd_file(self):
        # Backup previous values
        self.old_key_file = Password.KEYFILE
        self.old_can_write = Password._can_write
        # Mock pwd file
        f, filename = tempfile.mkstemp()
        self.addCleanup(os.unlink, filename)
        Password.KEYFILE = filename
        Password._can_write = MagicMock(return_value=True)

    def unmock_pwd_file(self):
        # Restore pwd file from backup
        Password.KEYFILE = self.old_key_file
        Password._can_write = self.old_can_write

    def test_validate_encrypted_password(self):
        """
        Test of validation of encrypted password
        """
        self.init_virt_config_section()
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
        self.unmock_pwd_file()

    def test_validate_missing_encrypted_password(self):
        """
        Test of validation of missing encrypted password
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNotNone(result)

    def test_validate_wrong_encrypted_password(self):
        """
        Test of validation of corrupted encrypted password
        """
        self.init_virt_config_section()
        self.mock_pwd_file()
        # Safe current password
        password = self.virt_config['password']
        # Delete unencrypted password first
        del self.virt_config['password']
        # Set up corrupted encrypted password
        encrypted_pwd = Password.encrypt(password)
        corrupted_encrypted_pwd = b'S' + encrypted_pwd[1:]
        self.virt_config['encrypted_password'] = hexlify(corrupted_encrypted_pwd)
        # Do own testing here
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNone(result)
        decrypted_password = self.virt_config.get('password')
        self.assertNotEqual(password, decrypted_password)
        self.unmock_pwd_file()

    def test_validate_correct_username(self):
        """
        Test of validation of username (it has to include only latin1 characters)
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_username('username')
        self.assertIsNone(result)

    def test_validate_missing_username(self):
        """
        Test of validation of missing username
        """
        self.init_virt_config_section()
        del self.virt_config['username']
        result = self.virt_config._validate_username('username')
        self.assertIsNotNone(result)

    def test_validate_wrong_username(self):
        """
        Test validation of wrong username (containing e.g. UTF-8 string)
        """
        self.init_virt_config_section()
        # First, change username to something exotic ;-)
        self.virt_config['username'] = 'Jiří'
        result = self.virt_config._validate_username('username')
        self.assertIsNotNone(result)

    def test_validate_server(self):
        """
        Test validation of server
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_server('server')
        self.assertIsNone(result)

    def test_validate_missing_server(self):
        """
        Test validation of missing server for some virt backends
        """
        self.init_virt_config_section()
        # These backends require server option in configuration
        virt_backends_requiring_server = ('esx', 'rhevm', 'hyperv', 'xen')
        # Delete server option
        del self.virt_config['server']
        # Test all of them
        for virt_type in virt_backends_requiring_server:
            self.virt_config['type'] = virt_type
            result = self.virt_config._validate_server('server')
            self.assertIsNotNone(result)

    def test_validate_missing_server_not_critical(self):
        """
        Test validation of missing server for some virt backends which
        do not need server option to exist.
        """
        self.init_virt_config_section()
        # These backends do not require server option in configuration
        virt_backends_not_requiring_server = ('libvirt', 'vdsm', 'fake')
        # Delete server option
        del self.virt_config['server']
        # Test all of vm backend types
        for virt_type in virt_backends_not_requiring_server:
            self.virt_config['type'] = virt_type
            result = self.virt_config._validate_server('server')
            self.assertIsNone(result)

    def test_validate_environment(self):
        """
        Test validation of env option 
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_env('env')
        self.assertIsNone(result)

    def test_validate_owner(self):
        """
        Test validation of owner option
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_owner('owner')
        self.assertIsNone(result)

    def test_validate_filter(self):
        """
        Test validation of host filter
        """
        self.init_virt_config_section()
        result = self.virt_config._validate_filter('filter_hosts')
        self.assertIsNone(result)

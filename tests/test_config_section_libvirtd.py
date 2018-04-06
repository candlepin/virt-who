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
Test validating of LibvirtdConfigSection
"""

from base import TestBase
from mock import MagicMock
import tempfile
import os
import six
from binascii import hexlify
import shutil

from virtwho.password import Password
from virtwho.config import EffectiveConfig, ConfigSection, parse_file
from virtwho.virt.libvirtd.libvirtd import LibvirtdConfigSection

MY_SECTION_NAME = 'test-libvirt'
MY_SAT5_SECTION_NAME = 'test-sat5-libvirt'

# Values used for testing VirtConfigSection
LIBVIRT_SECTION_VALUES = {
    'type': 'libvirt',
    'server': 'ssh://10.0.0.101/system',
    'env': '123456',
    'owner': '123456',
    'hypervisor_id': 'uuid',
    'filter_hosts': '*.example.com'
}

LIBVIRT_SECTION_TEXT = """
[test-libvirt]
type = libvirt
server = ssh://192.168.122.10
env = 123456
owner = 123456
"""

# No env or owner is required for Satellite 5
LIBVIRT_SAT5_SECTION_TEXT = """
[test-sat5-libvirt]
type = libvirt
sm_type = satellite
sat_server = https://sat5.company.com/XMLRPC
sat_username = admin
sat_password = secret
"""


class TestLibvirtdConfigSection(TestBase):
    """
    Test base for testing class LibvirtdConfigSection
    """

    def __init__(self, *args, **kwargs):
        super(TestLibvirtdConfigSection, self).__init__(*args, **kwargs)
        self.virt_config = None

    def init_virt_config_section(self):
        """
        Method executed before each unit test
        """
        self.virt_config = LibvirtdConfigSection(MY_SECTION_NAME, None)
        # We need to set values using this way, because we need
        # to trigger __setitem__ of virt_config
        for key, value in LIBVIRT_SECTION_VALUES.items():
            self.virt_config[key] = value

    def test_validate_libvirt_section(self):
        """
        Test validation of libvirt section
        """
        self.init_virt_config_section()
        result = self.virt_config.validate()
        self.assertGreater(len(result), 0)

    def test_validate_server_optional(self):
        """
        Test validation of server option. It is optional for libvirtd
        """
        self.init_virt_config_section()
        # The server option is set
        result = self.virt_config._validate_server('server')
        self.assertIsNone(result)
        # The server option is not set
        del self.virt_config['server']
        result = self.virt_config._validate_server('server')
        self.assertIsNone(result)

    def test_validate_server_full_url(self):
        """
        Test validation of libvirt URL containing all parts
        """
        self.init_virt_config_section()
        # Set full URL
        self.virt_config['server'] = 'qemu+ssh://admin@example.com/system'
        result = self.virt_config._validate_server('server')
        self.assertIsNone(result)

    def test_validate_uuid_hypervisor_id(self):
        """
        Test validation of valid hypervisor_id
        """
        # Following method sets hypervisor_id to 'uuid' and it is valid
        self.init_virt_config_section()
        result = self.virt_config._validate_hypervisor_id('hypervisor_id')
        self.assertIsNone(result)

    def test_validate_hostname_hypervisor_id(self):
        """
        Test validation of valid hypervisor_id
        """
        self.init_virt_config_section()
        self.virt_config['hypervisor_id'] = 'hostname'  # it is also valid value
        result = self.virt_config._validate_hypervisor_id('hypervisor_id')
        self.assertIsNone(result)

    def test_validate_unvalid_hypervisor_id(self):
        """
        Test validation of valid hypervisor_id
        """
        self.init_virt_config_section()
        self.virt_config['hypervisor_id'] = 'unsupported_id'
        result = self.virt_config._validate_hypervisor_id('hypervisor_id')
        expected_result = [
            ('error', 'Invalid option: "unsupported_id" for hypervisor_id, use one of: (uuid, hostname)')
        ]
        six.assertCountEqual(self, result, expected_result)

    def test_validate_server_url_missing_path(self):
        """
        Test validation of libvirt URL with missing path
        """
        self.init_virt_config_section()
        # Set full URL
        self.virt_config['server'] = 'qemu+ssh://admin@example.com'
        result = self.virt_config._validate_server('server')
        expected_result = [
            ('info', 'Libvirt path is not specified in the url, using /system')
        ]
        six.assertCountEqual(self, result, expected_result)
        self.assertEqual(self.virt_config['server'], 'qemu+ssh://admin@example.com/system?no_tty=1')

    def test_validate_server_url_missing_scheme(self):
        """
        Test validation of libvirt URL with missing scheme
        """
        self.init_virt_config_section()
        # Set full URL
        self.virt_config['server'] = 'example.com/system'
        result = self.virt_config._validate_server('server')
        expected_result = [
            ('info', 'Protocol is not specified in libvirt url, using qemu+ssh://')
        ]
        six.assertCountEqual(self, result, expected_result)
        self.assertEqual(self.virt_config['server'], 'qemu+ssh://example.com/system?no_tty=1')

    def test_validate_server_url_missing_scheme_and_path(self):
        """
        Test validation of libvirt URL with missing scheme and path
        """
        self.init_virt_config_section()
        # Set full URL
        self.virt_config['server'] = 'example.com'
        result = self.virt_config._validate_server('server')
        expected_result = [
            ('info', 'Protocol is not specified in libvirt url, using qemu+ssh://'),
            ('info', 'Libvirt path is not specified in the url, using /system')
        ]
        six.assertCountEqual(self, result, expected_result)
        self.assertEqual(self.virt_config['server'], 'qemu+ssh://example.com/system?no_tty=1')

    def test_validate_sam_owner(self):
        """
        Test validation of owner option for libvirtd virt. backend and SAM destination
        """
        self.init_virt_config_section()
        # When server is set and SAM destination is used, then owner has to be set
        assert 'server' in self.virt_config
        assert 'sam' == self.virt_config['sm_type']
        result = self.virt_config._validate_owner('owner')
        self.assertIsNone(result)
        # Delete 'owner' section
        del self.virt_config['owner']
        result = self.virt_config._validate_owner('owner')
        self.assertIsNotNone(result)
        # Delete server too, then owner need not to be set
        del self.virt_config['server']
        result = self.virt_config._validate_owner('owner')
        self.assertIsNone(result)

    def test_validate_sat5_owner(self):
        """
        Test validation of owner option for libvirtd virt. backend and SAT5 destination
        """
        self.init_virt_config_section()
        self.virt_config['sm_type'] = 'satellite'
        # When server is set and SAM destination is used, then owner has to be set
        assert 'server' in self.virt_config
        # Delete 'owner' section
        del self.virt_config['owner']
        result = self.virt_config._validate_owner('owner')
        self.assertIsNone(result)

    def test_validate_sam_env(self):
        """
        Test validation of owner option for libvirtd virt. backend. and SAM destination
        It is similar for owner
        """
        self.init_virt_config_section()
        # When server is set, then owner has to be set too
        assert 'server' in self.virt_config
        assert 'sam' == self.virt_config['sm_type']
        result = self.virt_config._validate_env('env')
        self.assertIsNone(result)
        # Delete 'env' section
        del self.virt_config['env']
        result = self.virt_config._validate_env('env')
        self.assertIsNotNone(result)
        # Delete server too, then env need not to be set
        del self.virt_config['server']
        result = self.virt_config._validate_env('env')
        self.assertIsNone(result)

    def test_validate_sat5_env(self):
        """
        Test validation of owner option for libvirtd virt. backend. and SAT5 destination
        It is similar for owner
        """
        self.init_virt_config_section()
        self.virt_config['sm_type'] = 'satellite'
        # When server is set, then owner has to be set too
        assert 'server' in self.virt_config
        # Delete 'env' section
        del self.virt_config['env']
        result = self.virt_config._validate_env('env')
        self.assertIsNone(result)

    def test_validate_unencrypted_password(self):
        """
        test validation of unecrypted password option for libvirt virt. backend
        """
        self.init_virt_config_section()
        # Validation with no password option
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNone(result)
        # RHSM password or RHSM proxy can be set
        self.virt_config['rhsm_password'] = 'secret_password'
        result = self.virt_config._validate_unencrypted_password('rhsm_password')
        self.assertIsNone(result)
        self.virt_config['rhsm_proxy_password'] = 'secret_password'
        result = self.virt_config._validate_unencrypted_password('rhsm_proxy_password')
        self.assertIsNone(result)
        # When server is set, then setting password is useless
        self.virt_config['password'] = 'another_secret_password'
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNotNone(result)
        # When server is not set, then setting password is useless too, but
        # reason is different
        del self.virt_config['server']
        result = self.virt_config._validate_unencrypted_password('password')
        self.assertIsNotNone(result)

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
        test validation of encrypted password option for libvirt virt. backend
        """
        self.mock_pwd_file()
        self.init_virt_config_section()
        # Validation with no encrypted_password option
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNone(result)
        # RHSM password or RHSM proxy can be set
        self.virt_config['rhsm_encrypted_password'] = hexlify(Password.encrypt('secret_password'))
        result = self.virt_config._validate_encrypted_password('rhsm_encrypted_password')
        self.assertIsNone(result)
        self.virt_config['rhsm_encrypted_proxy_password'] = hexlify(Password.encrypt('secret_password'))
        result = self.virt_config._validate_encrypted_password('rhsm_encrypted_proxy_password')
        self.assertIsNone(result)
        # When server is set, then setting password is useless
        self.virt_config['encrypted_password'] = hexlify(Password.encrypt('another_secret_password'))
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNotNone(result)
        # When server is not set, then setting password is useless too, but
        # reason is different
        del self.virt_config['server']
        result = self.virt_config._validate_encrypted_password('encrypted_password')
        self.assertIsNotNone(result)
        self.unmock_pwd_file()


class TestLibvirtEffectiveConfig(TestBase):
    """
    Test reading config section from text using EffectiveConfig
    """

    def __init__(self, *args, **kwargs):
        super(TestLibvirtEffectiveConfig, self).__init__(*args, **kwargs)
        self.effective_config = None

    def init_effective_config(self):
        """
        This method is executed before each unit test
        """
        self.effective_config = EffectiveConfig()

    def test_read_sam_effective_config_from_file(self):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write(LIBVIRT_SECTION_TEXT)
        conf = parse_file(os.path.join(config_dir, "test.conf"))
        self.init_effective_config()
        conf_values = conf.pop(MY_SECTION_NAME)
        self.effective_config[MY_SECTION_NAME] = ConfigSection.from_dict(
            conf_values,
            MY_SECTION_NAME,
            self.effective_config
        )
        self.assertEqual(type(self.effective_config[MY_SECTION_NAME]), LibvirtdConfigSection)
        self.assertEqual(self.effective_config[MY_SECTION_NAME]['server'], 'ssh://192.168.122.10')
        validate_messages = self.effective_config.validate()
        self.assertIsNotNone(validate_messages)
        del self.effective_config[MY_SECTION_NAME]

    def test_read_sat5_effective_config_from_file(self):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write(LIBVIRT_SAT5_SECTION_TEXT)
        conf = parse_file(os.path.join(config_dir, "test.conf"))
        self.init_effective_config()
        conf_values = conf.pop(MY_SAT5_SECTION_NAME)
        self.effective_config[MY_SAT5_SECTION_NAME] = ConfigSection.from_dict(
            conf_values,
            MY_SAT5_SECTION_NAME,
            self.effective_config
        )
        self.assertEqual(type(self.effective_config[MY_SAT5_SECTION_NAME]), LibvirtdConfigSection)
        validate_messages = self.effective_config.validate()
        self.assertEqual(self.effective_config[MY_SAT5_SECTION_NAME]['sat_server'], 'https://sat5.company.com/XMLRPC')
        self.assertEqual(self.effective_config[MY_SAT5_SECTION_NAME]['sm_type'], 'satellite')
        self.assertIsNotNone(validate_messages)
        del self.effective_config[MY_SAT5_SECTION_NAME]

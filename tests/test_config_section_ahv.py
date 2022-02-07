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
Test validating of AhvConfigSection
"""

from base import ConfigSectionValidationTests, TestBase
from virtwho.parser import SAT6
from virtwho.virt.ahv.ahv import AhvConfigSection


class TestEsxConfigSection(ConfigSectionValidationTests, TestBase):
    """
    A group of tests to ensure proper validation of AhvConfigSections
    """
    CONFIG_CLASS = AhvConfigSection
    VALID_CONFIG = {
        "type": "esx",
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
        'sm_type': SAT6,
    }

    def test_validate_server_good_ip(self):
        self.virt_config = AhvConfigSection('test_ahv', None)

        self.virt_config['server'] = "10.10.10.10"
        result = self.virt_config._validate_server('server')
        self.assertEqual(result, None)

        self.virt_config['server'] = ""
        result = self.virt_config._validate_server('server')
        self.assertEqual(result, ('error', "Option server needs to be set in config: 'test_ahv'"))

        self.virt_config['server'] = "xxx"
        result = self.virt_config._validate_server('server')
        self.assertEqual(result, ('error', 'Invalid server IP address provided'))
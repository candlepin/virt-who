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
Test validating of NutanixConfigSection
"""

from base import ConfigSectionValidationTests, TestBase
from virtwho.parser import SAT6
from virtwho.virt.nutanix.nutanix import NutanixConfigSection


class TestNutanixConfigSection(ConfigSectionValidationTests, TestBase):
    """
    A group of tests to ensure proper validation of NutanixConfigSections
    """
    CONFIG_CLASS = NutanixConfigSection
    VALID_CONFIG = {
        "type": "nutanix",
        "server": "1.2.3.4",
        "username": "username",
        "password": "password",
        "ssl_verify": "True",
        "api_base": "/PrismGateway/services/rest/v2.0/",
        "owner": "admin",
        "env": "admin",
        "filter_host_parents": "'PARENT_A', 'PARENT_B'",
        "exclude_host_parents": "'PARENT_C_EXCLUDED'",
    }

    SAM_REQUIRED_KEYS = {
        'type',
        'server',
        'username',
        'password',
        'owner',
        'env'
    }

    SAT5_REQUIRED_KEYS = SAM_REQUIRED_KEYS - {'owner', 'env'}

    DEFAULTS = {
        'filter_host_parents': None,
        'exclude_host_parents': None,
        'hypervisor_id': 'uuid',
        'ssl_verify': True,
        'sm_type': SAT6,
        'api_base': '/PrismGateway/services/rest/v2.0/'
    }


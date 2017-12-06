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
Test validating of EsxConfigSection
"""

from base import ConfigSectionValidationTests, TestBase
from virtwho.parser import SAT6
from virtwho.virt.esx.esx import EsxConfigSection


class TestEsxConfigSection(ConfigSectionValidationTests, TestBase):
    """
    A group of tests to ensure proper validation of EsxConfigSections
    """
    CONFIG_CLASS = EsxConfigSection
    VALID_CONFIG = {
        "type": "esx",
        "server": "1.2.3.4",
        "username": "username",
        "password": "password",
        "owner": "admin",
        "env": "admin",
        "filter_host_parents": "'PARENT_A', 'PARENT_B'",
        "exclude_host_parents": "'PARENT_C_EXCLUDED'",
    }

    REQUIRED_KEYS = set([
        'type',
        'server',
        'username',
        'password',
    ])

    DEFAULTS = {
        'filter_host_parents': None,
        'exclude_host_parents': None,
        'hypervisor_id': 'uuid',
        'simplified_vim': True,
        'sm_type': SAT6,
    }


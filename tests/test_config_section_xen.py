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
Test validating of XenConfigSection
"""

from base import ConfigSectionValidationTests, TestBase
from virtwho.virt.xen.xen import XenConfigSection


class TestXenConfigSection(ConfigSectionValidationTests, TestBase):
    """
    A group of tests to ensure proper validation of XenConfigSections
    """
    CONFIG_CLASS = XenConfigSection
    VALID_CONFIG = {
        "type": "xen",
        "server": "1.2.3.4",
        "username": "username",
        "password": "password",
        "owner": "admin",
        "env": "admin",
    }

    SAM_REQUIRED_KEYS = {
        'type',
        'server',
        'username',
        'password',
        'owner',
        'env',
    }

    SAT5_REQUIRED_KEYS = SAM_REQUIRED_KEYS - {'owner', 'env'}

    DEFAULTS = {
        'hypervisor_id': 'uuid',
        'sm_type': 'sam',
    }


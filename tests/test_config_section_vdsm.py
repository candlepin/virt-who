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
Test validating of VdsmConfigSection
"""

from base import ConfigSectionValidationTests, TestBase
from virtwho.virt.vdsm.vdsm import VdsmConfigSection


class TestVdsmConfigSection(ConfigSectionValidationTests, TestBase):
    """
    A group of tests to ensure proper validation of XenConfigSections
    """
    CONFIG_CLASS = VdsmConfigSection
    VALID_CONFIG = {
        "type": "vdsm",
        "server": "1.2.3.4",
        "owner": "admin",
    }

    SAM_REQUIRED_KEYS = set()

    DEFAULTS = {
        'sm_type': 'sam',
    }


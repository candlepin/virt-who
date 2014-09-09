"""
Basic module for tests,

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

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


# hack to use unittest2 on python <= 2.6, unittest otherwise
# based on python version
import sys
if sys.version_info[0] > 2 or sys.version_info[1] > 6:
    import unittest
else:
    import unittest2 as unittest

import logging
import log
from mock import patch


class TestBase(unittest.TestCase):
    @classmethod
    @patch('log.getLogger')
    def setUpClass(cls, logger):
        cls.logger = logging.getLogger("")
        cls.logger.handlers = []
        cls.logger.setLevel(logging.CRITICAL)
        logger.return_value = cls.logger

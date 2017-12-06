# -*- coding: utf-8 -*-
from __future__ import print_function

"""
Test for password encryption/decryption.

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

import os
import tempfile
from binascii import hexlify, unhexlify
from mock import MagicMock

from base import TestBase

from virtwho.password import Password


class TestPassword(TestBase):
    def mock_pwd_file(self):
        f, filename = tempfile.mkstemp()
        self.addCleanup(os.unlink, filename)
        Password.KEYFILE = filename
        Password._can_write = MagicMock(return_value=True)

    def test_encrypt(self):
        self.assertEqual(hexlify(
            Password._crypt(
                Password.ENCRYPT,
                '06a9214036b8a15b512e03d534120006',
                '3dafba429d9eb430b422da802c9fac41',
                b'Single block msg')),
            b'e353779c1079aeb82708942dbe77181a')

    def test_decrypt(self):
        self.assertEqual(
            Password._crypt(
                Password.DECRYPT,
                '06a9214036b8a15b512e03d534120006',
                '3dafba429d9eb430b422da802c9fac41',
                unhexlify('e353779c1079aeb82708942dbe77181a')),
            b'Single block msg')

    def test_both(self):
        self.mock_pwd_file()
        pwd = "Test password"
        encrypted = Password.encrypt(pwd)
        self.assertEqual(pwd, Password.decrypt(encrypted))

    def test_pad(self):
        self.assertEqual(hexlify(Password._pad(unhexlify("00010203040506070809"))), b"00010203040506070809060606060606")

    def test_unpad(self):
        self.assertEqual(hexlify(Password._unpad(unhexlify("00010203040506070809060606060606"))), b"00010203040506070809")

    def test_percent(self):
        self.mock_pwd_file()
        pwd = 'abc%%def'
        self.assertEqual(
            Password.decrypt(Password.encrypt(pwd)),
            pwd)

    def test_backslash(self):
        self.mock_pwd_file()
        pwd = 'abc\\def'
        self.assertEqual(
            Password.decrypt(Password.encrypt(pwd)),
            pwd)

    def test_unicode(self):
        self.mock_pwd_file()
        pwd = u'‣'
        self.assertEqual(Password.decrypt(Password.encrypt(pwd)), pwd)

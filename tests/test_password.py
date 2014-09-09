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

from password import Password


class TestPassword(TestBase):
    def testEncrypt(self):
        self.assertEqual(hexlify(
            Password._crypt(
                Password.ENCRYPT,
                '06a9214036b8a15b512e03d534120006',
                '3dafba429d9eb430b422da802c9fac41',
                'Single block msg')),
            'e353779c1079aeb82708942dbe77181a')

    def testDecrypt(self):
        self.assertEqual(
            Password._crypt(
                Password.DECRYPT,
                '06a9214036b8a15b512e03d534120006',
                '3dafba429d9eb430b422da802c9fac41',
                unhexlify('e353779c1079aeb82708942dbe77181a')),
            'Single block msg')

    def testBoth(self):
        f, filename = tempfile.mkstemp()
        self.addCleanup(os.unlink, filename)
        Password.KEYFILE = filename
        pwd = "Test password"
        Password._can_write = MagicMock(retun_value=True)
        encrypted = Password.encrypt(pwd)
        self.assertEqual(pwd, Password.decrypt(encrypted))

    def testPad(self):
        self.assertEqual(hexlify(Password._pad(unhexlify("00010203040506070809"))), "00010203040506070809060606060606")

    def testUnpad(self):
        self.assertEqual(hexlify(Password._unpad(unhexlify("00010203040506070809060606060606"))), "00010203040506070809")

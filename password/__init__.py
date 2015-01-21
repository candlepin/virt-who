"""
Module for encrypting and decrypting passwords.

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
import stat
from M2Crypto import EVP
from binascii import hexlify, unhexlify
from cStringIO import StringIO


class InvalidKeyFile(Exception):
    pass


class UnwrittableKeyFile(Exception):
    pass


class Password(object):
    KEYFILE = '/var/lib/virt-who/key'
    ENCRYPT = 1
    DECRYPT = 0

    BLOCKSIZE = 16

    @classmethod
    def _pad(cls, s):
        return s + (cls.BLOCKSIZE - len(s) % cls.BLOCKSIZE) * chr(cls.BLOCKSIZE - len(s) % cls.BLOCKSIZE)

    @classmethod
    def _unpad(cls, s):
        return s[0:-ord(s[-1])]


    @classmethod
    def _crypt(cls, op, key, iv, data):
        cipher = EVP.Cipher(alg='aes_128_cbc', key=unhexlify(key), iv=unhexlify(iv), op=op, padding=False)
        inf = StringIO(data)
        outf = StringIO()
        while 1:
            buf = inf.read()
            if not buf:
                break
            outf.write(cipher.update(buf))
        outf.write(cipher.final())
        return outf.getvalue()

    @classmethod
    def encrypt(cls, password):
        key, iv = cls._read_or_generate_key_iv()
        return cls._crypt(cls.ENCRYPT, key, iv, cls._pad(password))

    @classmethod
    def decrypt(cls, enc):
        key, iv = cls._read_key_iv()
        return cls._unpad(cls._crypt(cls.DECRYPT, key, iv, enc))

    @classmethod
    def _read_key_iv(cls):
        try:
            with open(cls.KEYFILE, 'r') as f:
                key = f.readline().strip()
                iv = f.readline().strip()
                if not iv or not key:
                    raise InvalidKeyFile("Invalid format")
            return key, iv
        except IOError as e:
            raise InvalidKeyFile(str(e))

    @classmethod
    def _can_write(cls):
        return os.getuid() == 0

    @classmethod
    def _read_or_generate_key_iv(cls):
        try:
            return cls._read_key_iv()
        except InvalidKeyFile:
            pass
        if not cls._can_write():
            raise UnwrittableKeyFile("Only root can write keyfile")
        key = hexlify(cls._generate_key())
        iv = hexlify(cls._generate_key())
        try:
            with open(cls.KEYFILE, 'w') as f:
                f.write("%s\n%s\n" % (key, iv))
        except IOError as e:
            raise UnwrittableKeyFile(str(e))
        os.chmod(cls.KEYFILE, stat.S_IRUSR | stat.S_IWUSR)
        return key, iv

    @classmethod
    def _generate_key(cls):
        return os.urandom(32)

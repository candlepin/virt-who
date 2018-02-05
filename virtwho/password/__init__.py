# -*- coding: utf-8 -*-
from __future__ import print_function
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
import six
if not six.PY3:
    from M2Crypto import EVP
else:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
from binascii import hexlify, unhexlify
from six.moves import cStringIO as StringIO


__all__ = ['InvalidKeyFile', 'UnwritableKeyFile', 'Password']


class InvalidKeyFile(Exception):
    pass


class UnwritableKeyFile(Exception):
    pass



class Password(object):
    KEYFILE = '/var/lib/virt-who/key'
    ENCRYPT = 1
    DECRYPT = 0

    BLOCKSIZE = 16

    @staticmethod
    def safe_ord(s):
        """
        Returns ord(s) if s is a string else if s is an int, returns the int other exceptions are
        raised
        :param s: str or int
        :return: int
        """
        if isinstance(s, int):
            return s
        return ord(s)

    @classmethod
    def _pad(cls, s):
        padding_amount = cls.BLOCKSIZE - len(s) % cls.BLOCKSIZE
        return s + (chr(padding_amount) * padding_amount).encode('ascii')

    @classmethod
    def _unpad(cls, s):
        return s[0:-Password.safe_ord(s[-1])]

    @classmethod
    def _crypt(cls, op, key, iv, data):
        key = unhexlify(key)[:cls.BLOCKSIZE]
        iv = unhexlify(iv)[:cls.BLOCKSIZE]

        if not six.PY3:
            return cls._crypt_py2(op, key, iv, data)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())

        if op == Password.ENCRYPT:
            crypter = cipher.encryptor()
        elif op == Password.DECRYPT:
            crypter = cipher.decryptor()
        else:
            raise ValueError("Unable to perform op '%s'" % op)
        value = crypter.update(data) + crypter.finalize()
        return value

    @classmethod
    def _crypt_py2(cls, op, key, iv, data):
        cipher = EVP.Cipher(alg='aes_128_cbc', key=key, iv=iv, op=op, padding=False)
        inf = StringIO(data)
        outf = StringIO()
        while True:
            buf = inf.read()
            if not buf:
                break
            outf.write(cipher.update(buf))
        outf.write(cipher.final())
        return outf.getvalue()

    @classmethod
    def encrypt(cls, password):
        key, iv = cls._read_or_generate_key_iv()
        if isinstance(password, six.text_type):
            password = password.encode('utf-8')
        return cls._crypt(cls.ENCRYPT, key, iv, cls._pad(password))

    @classmethod
    def decrypt(cls, enc):
        try:
            key, iv = cls._read_key_iv()
            if isinstance(enc, six.text_type):
                enc = enc.encode('utf-8')
            return cls._unpad(cls._crypt(cls.DECRYPT, key, iv, enc)).decode('utf-8')
        except TypeError:
            raise InvalidKeyFile("Encryption key is invalid")

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
            raise UnwritableKeyFile("Only root can write keyfile")
        key = hexlify(cls._generate_key())
        iv = hexlify(cls._generate_key())
        try:
            with open(cls.KEYFILE, 'w') as f:
                f.write("%s\n%s\n" % (key.decode(), iv.decode()))
        except IOError as e:
            raise UnwritableKeyFile(str(e))
        os.chmod(cls.KEYFILE, stat.S_IRUSR | stat.S_IWUSR)
        return key, iv

    @classmethod
    def _generate_key(cls):
        return os.urandom(cls.BLOCKSIZE)

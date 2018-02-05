#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Command line script for password encryption.

Copyright (C) 2012 Radek Novacek <rnovacek@redhat.com>

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
import sys
from getpass import getpass
from binascii import hexlify

from virtwho.password import Password, UnwritableKeyFile, InvalidKeyFile

from optparse import OptionParser

class RawDescriptionOptionParser(OptionParser):
    def format_description(self, description):
        return self.description or ""

def parseOptions():
    parser = RawDescriptionOptionParser(usage="virt-who-password",
                                        description="""Utility that encrypts passwords for virt-who.

Enter password that should be encrypted. This encrypted password then can be
supplied to virt-who configuration.

This command must be executed as root!

WARNING: root user can still decrypt encrypted passwords!
    """)
    parser.add_option("-p", "--password", dest="password", help="Password")
    return parser.parse_args()

def main():
    options, _args = parseOptions()

    if os.getuid() != 0:
        print("Only root can encrypt passwords", file=sys.stderr)
        sys.exit(1)

    try:
        pwd = options.password or getpass("Password: ")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)
    try:
        enc = Password.encrypt(pwd)
    except UnwritableKeyFile:
        print("Keyfile %s doesn't exist and can't be created, rerun as root" % Password.KEYFILE, file=sys.stderr)
        sys.exit(1)
    except InvalidKeyFile:
        print("Can't access keyfile %s, rerun as root" % Password.KEYFILE, file=sys.stderr)
        sys.exit(1)
    print("Use following as value for encrypted_password key in the configuration file:", file=sys.stderr)
    print(hexlify(enc).decode())


if __name__ == '__main__':
    main()

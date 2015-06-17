#!/usr/bin/python2
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
from password import Password, UnwritableKeyFile, InvalidKeyFile
from binascii import hexlify

if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] in ('-h', '--help'):
        print """Utility that encrypts passwords for virt-who.

Enter password that should be encrypted. This encrypted password then can be
supplied to virt-who configuration.

This command must be executed as root!

WARNING: root user can still decrypt encrypted passwords!
"""
        sys.exit(0)

    if os.getuid() != 0:
        print >>sys.stderr, "Only root can encrypt passwords"
        sys.exit(1)

    try:
        pwd = getpass("Password: ")
    except (KeyboardInterrupt, EOFError):
        print
        sys.exit(1)
    try:
        enc = Password.encrypt(pwd)
    except UnwritableKeyFile:
        print >>sys.stderr, "Keyfile %s doesn't exist and can't be created, rerun as root" % Password.KEYFILE
        sys.exit(1)
    except InvalidKeyFile:
        print >>sys.stderr, "Can't access keyfile %s, rerun as root" % Password.KEYFILE
        sys.exit(1)
    print >>sys.stderr, "Use following as value for encrypted_password key in the configuration file:"
    print hexlify(enc)

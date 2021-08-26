# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import
"""
Agent for reporting virtual guest IDs to subscription-manager

Copyright (C) 2011 Radek Novacek <rnovacek@redhat.com>

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

import sys
import os
import time
import fcntl

PIDFILE = "/var/run/virt-who.pid"
STATUS_LOCK = "/var/run/virt-who-status.pid"
STATUS_DATA = "/var/lib/virt-who/run_data.json"
STATUS_DATA_DIR = "/var/lib/virt-who"
DEFAULT_TIMEOUT = 1.0


class PIDLock(object):
    def __init__(self, filename):
        self.filename = filename

    def is_locked(self):
        try:
            with open(self.filename, "r") as f:
                pid = int(f.read().strip())
            try:
                # this does not kill the process, it is a way
                # to see if the process with this PID still exists
                os.kill(pid, 0)
                return True
            except OSError:
                # Process no longer exists
                print(
                    "PID file exists but associated process "
                    "does not, deleting PID file",
                    file=sys.stderr
                )
                os.remove(self.filename)
                return False
        except Exception:
            return False

    def __enter__(self):
        # Write pid to pidfile
        try:
            with os.fdopen(
                    os.open(self.filename, os.O_WRONLY | os.O_CREAT, 0o600),
                    'w') as f:
                f.write("%d" % os.getpid())
        except Exception as e:
            print("Unable to create pid file: %s" % str(e), file=sys.stderr)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.filename)
        except Exception:
            pass


class FileLock(object):
    def __init__(self, filename, logger=None, timeout=None):
        self.lock_file = filename
        self.logger = logger
        self.timeout = timeout or DEFAULT_TIMEOUT

    def __enter__(self):
        open_mode = os.O_RDWR | os.O_CREAT | os.O_TRUNC
        fd = os.open(self.lock_file, open_mode)
        self.lock_file_fd = None

        start_time = current_time = time.time()
        while current_time < start_time + self.timeout:
            try:
                # The LOCK_EX means that only one process can hold the lock
                # The LOCK_NB means that the fcntl.flock() is not blocking
                # and we are able to implement termination of while loop,
                # when timeout is reached.
                # More information here:
                # https://docs.python.org/3/library/fcntl.html#fcntl.flock
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                pass
            else:
                self.lock_file_fd = fd
                break
            time.sleep(0.2)
            current_time = time.time()
        # we did not get the lock in the time allowed
        if self.lock_file_fd is None:
            os.close(fd)
            raise IOError

    def __exit__(self, exc_type, exc_value, traceback):
        # Do not remove the lockfile:
        #
        #   https://github.com/benediktschmitt/py-filelock/issues/31
        #   https://stackoverflow.com/questions/17708885/flock-removing-locked-file-without-race-condition
        fcntl.flock(self.lock_file_fd, fcntl.LOCK_UN)
        os.close(self.lock_file_fd)

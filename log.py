"""
Module for logging, part of virt-who

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


import logging
import logging.handlers
import os
import sys

FILE_LOG_FORMAT = """%(asctime)s [%(levelname)s]  @%(filename)s:%(lineno)d - %(message)s"""
STREAM_LOG_FORMAT = """%(asctime)s %(levelname)s: %(message)s"""


DEBUG_FORMAT = "%(asctime)s [%(name)s %(levelname)s] " \
                "%(processName)s(%(process)d):%(threadName)s " \
                "@%(filename)s:%(funcName)s:%(lineno)d - %(message)s"

DEFAULT_FORMAT = DEBUG_FORMAT
def getLogger(debug, background):
    logger = logging.getLogger("virtwho")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    logdir = '/var/log/rhsm'
    path = os.path.join(logdir, 'virtwho.log')
    try:
        if not os.path.isdir(logdir):
            os.mkdir(logdir)
    except Exception as e:
        sys.stderr.write("Unable to create %s directory: %s" % (logdir, str(e)))

    # Try to write to /var/log, fallback on console logging:
    try:
        fileHandler = logging.handlers.WatchedFileHandler(path)
        fileHandler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        if debug:
            fileHandler.setLevel(logging.DEBUG)
        else:
            fileHandler.setLevel(logging.INFO)
        logger.addHandler(fileHandler)
    except Exception as e:
        sys.stderr.write("Unable to log to %s: %s\n" % (path, e))

    if not background:
        streamHandler = logging.StreamHandler()
        streamHandler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        if debug:
            streamHandler.setLevel(logging.DEBUG)
            streamHandler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        else:
            streamHandler.setLevel(logging.INFO)

            # Don't print exceptions to stdout in non-debug mode
            f = logging.Filter()
            f.filter = lambda record: record.exc_info is None
            streamHandler.addFilter(f)

        logger.addHandler(streamHandler)

    return logger

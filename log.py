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

journalEnabled = False
try:
    from systemd import journal
    journalEnabled = True
except ImportError:
    pass

class NoExceptionFormatter(logging.Formatter):
    def format(self, record):
        if record.exc_info is not None:
            record.exc_text = "\t" + str(record.exc_info[1])
        return logging.Formatter.format(self, record)

class JournalHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        logging.Handler.__init__(self, level)

    def emit(self, record):
        if journalEnabled:
            try:
                msg = self.format(record)
                args = ['MESSAGE=' + record.message,
                        'LOGGER=' + record.name,
                        'THREAD_NAME=' + record.threadName,
                        'CODE_FILE=' + record.pathname,
                        'CODE_LINE=%d' % record.lineno,
                        'CODE_FUNC=' + record.funcName]

                journal.sendv(*args)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                self.handleError(record)

def getLogger(debug, background):
    logger = logging.getLogger("rhsm-app")
    logger.setLevel(logging.DEBUG)

    path = '/var/log/rhsm/rhsm.log'
    try:
        if not os.path.isdir("/var/log/rhsm"):
            os.mkdir("/var/log/rhsm")
    except:
        pass

    # Try to write to /var/log, fallback on console logging:
    try:
        fileHandler = logging.handlers.RotatingFileHandler(path, maxBytes=0x100000, backupCount=5)
        fileHandler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s]  @%(filename)s:%(lineno)d - %(message)s'))
        if debug:
            fileHandler.setLevel(logging.DEBUG)
        else:
            fileHandler.setLevel(logging.WARNING)
        logger.addHandler(fileHandler)
    except Exception, e:
        sys.stderr.write("Unable to log to %s: %s\n" % (path, e))

    if not background:
        streamHandler = logging.StreamHandler()
        streamHandler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        if debug:
            streamHandler.setLevel(logging.DEBUG)
        else:
            streamHandler.setLevel(logging.WARNING)

            # Don't print exceptions to stdout in non-debug mode
            streamHandler.setFormatter(NoExceptionFormatter())


        logger.addHandler(streamHandler)

    if os.getppid() == 1:
        # Also log to journal if available
        journalHandler = JournalHandler()
        if debug:
            journalHandler.setLevel(logging.DEBUG)
        else:
            journalHandler.setLevel(logging.WARNING)

            # Don't print exceptions to journal in non-debug mode
            journalHandler.setFormatter(NoExceptionFormatter())

        logger.addHandler(journalHandler)
    return logger

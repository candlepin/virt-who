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
import traceback
import cStringIO
import os
import sys
import json
from Queue import Empty, Queue
from threading import Thread

from virtwho import util

try:
    from systemd import journal
except ImportError:
    journal = None

FILE_LOG_FORMAT = """%(asctime)s [%(levelname)s] @%(filename)s:%(lineno)d - %(message)s"""
STREAM_LOG_FORMAT = """%(asctime)s %(levelname)s: %(message)s"""
JOURNAL_LOG_FORMAT = """[%(levelname)s] @%(filename)s:%(lineno)d - %(message)s"""

DEBUG_FORMAT = "%(asctime)s [%(name)s %(levelname)s] " \
               "%(processName)s(%(process)d):%(threadName)s " \
               "@%(filename)s:%(funcName)s:%(lineno)d - %(message)s"

DEFAULT_FORMAT = DEBUG_FORMAT
DEFAULT_LOG_DIR = '/var/log/rhsm'
DEFAULT_LOG_FILE = 'rhsm.log'
DEFAULT_NAME = 'virtwho'


class QueueHandler(logging.Handler):
    """
    A handler that will write logrecords to a queue (Queue or multiprocessing.Queue)
    For use in logging in situations involving multiple processes
    """
    def __init__(self, queue, level=logging.NOTSET):
        logging.Handler.__init__(self, level)
        self._queue = queue
        self._formatter = self.formatter or logging.Formatter(FILE_LOG_FORMAT if level != logging.DEBUG else DEBUG_FORMAT)

    def formatException(self, ei):
        if self.level != logging.DEBUG:
            s = traceback.format_exception_only(ei[0], ei[1])[0]
        else:
            sio = cStringIO.StringIO()
            traceback.print_exception(ei[0], ei[1], ei[2], None, sio)
            s = sio.getvalue()
            sio.close()
        if s[-1:] == "\n":
            s = s[:-1]
        return s

    def prepare(self, record):
        """
        Prepares the record to be placed on the queue
        """
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info)
            record.exc_info = None

        # Apply string formatting to the message using args
        if hasattr(record, 'args'):
            record.msg = record.msg % record.args
            record.args = []

        serialized_record = json.dumps(record.__dict__)
        return serialized_record

    def emit(self, record):
        try:
            self._queue.put_nowait(self.prepare(record))
        except Exception:
            self.handleError(record)


class QueueLogger(object):
    """
    A threaded logger reading objects off a queue
    """
    def __init__(self, name, queue=None):
        self.name = name
        self.logger = logging.getLogger(self.name)
        self.queue = queue or Queue()
        self._logging_thread = Thread(target=QueueLogger._log,
                                      args=(self.logger,
                                            self.queue))

    @staticmethod
    def _log(logger, queue):
        exit = False
        while not exit:
            record = None
            try:
                record = queue.get()
            except Empty:
                return
            if record:
                to_log = QueueLogger.prepare(record)
                if to_log:
                    logger.handle(to_log)
            else:
                exit = True

    def start_logging(self):
        self._logging_thread.start()

    def terminate(self):
        self.queue.put_nowait(None)
        if self._logging_thread:
            self._logging_thread.join()
            self._logging_thread = None

    @staticmethod
    def prepare(record):
        prepared_record = None
        try:
            deserialized_record = json.loads(record, object_hook=util.decode)
            prepared_record = logging.makeLogRecord(deserialized_record)
        except Exception:
            # Swallow exceptions
            pass
        return prepared_record

    def getHandler(self, level=logging.NOTSET):
        # Return a queue handler that will write to this queue logger
        return QueueHandler(self.queue, level)

    def addHandler(self, handler):
        self.logger.addHandler(handler)


def checkDir(directory):
    try:
        if not os.path.isdir(directory):
            os.mkdir(directory)
    except Exception as e:
        sys.stderr.write("Unable to create %s directory: %s" % (directory, str(e)))
        return False
    return True


class Logger(object):
    _log_dir = DEFAULT_LOG_DIR
    _log_file = DEFAULT_LOG_FILE
    _log_per_config = False
    _logs = {}
    _stream_handler = None
    _journal_handler = None
    _level = logging.DEBUG
    _rhsm_level = logging.WARN
    _queue_logger = None
    _background = False

    @classmethod
    def initialize(cls, log_dir=None, log_file=None, log_per_config=None,
                   debug=None, background=None):
        # Set defaults if necessary
        if log_dir:
            cls._log_dir = log_dir
        if log_file:
            cls._log_file = log_file
        if log_per_config:
            cls._log_per_config = True
        cls._level = logging.DEBUG if debug else logging.INFO
        # We don't want INFO message from RHSM in non-debug mode
        cls._rhsm_level = logging.DEBUG if debug else logging.WARN
        cls._background = bool(background)

    @classmethod
    def get_logger(cls, name=None, config=None, queue=True):
        if name is None:
            # Remove slashes and periods in the config.name (as that could mess logging up
            name = config.name.replace('.', '').replace('/', '_') if config else 'main'
        logger_name = 'virtwho.' + name  # The name of the logger instance
        try:
            # Try to get an existing log
            return cls._logs[logger_name]
        except KeyError:
            pass

        logger = logging.getLogger(logger_name)
        cls._logs[logger_name] = logger
        logger.propagate = False  # Because we are using or own queue logger we don't want any of the loggers to propagate
        logger.setLevel(logging.DEBUG)

        # Show logging from RHSM in the log when DEBUG is enabled
        rhsm_logger = logging.getLogger("rhsm")
        rhsm_logger.setLevel(cls._rhsm_level)

        fileHandler = cls.get_file_handler(name=logger_name, config=config)

        ppid = os.getppid()

        journalHandler = None
        streamHandler = None
        if ppid == 1:
            # we're running under systemd, log to journal
            journalHandler = cls.get_journal_handler()
        else:
            # we're not running under systemd, set up streamHandler if we're not running in the background
            if not cls._background:
                streamHandler = cls.get_stream_handler(name)

        if queue:
            queueLogger = cls.get_queue_logger()
            # get a QueueHandler that will send to this queuelogger
            queueHandler = queueLogger.getHandler(cls._level)
            logger.addHandler(queueHandler)
            main_logger = queueLogger
        else:
            main_logger = logger

        if fileHandler:
            main_logger.addHandler(fileHandler)
            rhsm_logger.addHandler(fileHandler)

        if streamHandler:
            main_logger.addHandler(streamHandler)
            rhsm_logger.addHandler(streamHandler)

        if journalHandler:
            main_logger.addHandler(journalHandler)
            rhsm_logger.addHandler(journalHandler)

        return logger

    @classmethod
    def get_file_handler(cls, name, config=None):
        if cls._log_per_config:
            log_file = getattr(config, 'log_file', None) or (name + '.log')
        else:
            log_file = cls._log_file

        checkDir(cls._log_dir)
        path = os.path.join(cls._log_dir, log_file)

        try:
            fileHandler = logging.handlers.WatchedFileHandler(path)
        except Exception as e:
            sys.stderr.write("Unable to log to %s: %s\n" % (path, e))
            return None

        fileHandler.addFilter(logging.Filter(name))
        fileHandler.setLevel(cls._level)
        fileHandler.setFormatter(logging.Formatter(FILE_LOG_FORMAT if cls._level != logging.DEBUG else DEBUG_FORMAT))
        return fileHandler

    @classmethod
    def get_stream_handler(cls, name):
        if cls._stream_handler is not None:
            return cls._stream_handler
        streamHandler = logging.StreamHandler()
        streamHandler.setLevel(cls._level)
        streamHandler.setFormatter(logging.Formatter(STREAM_LOG_FORMAT if cls._level != logging.DEBUG else DEBUG_FORMAT))
        f = logging.Filter()
        f.filter = lambda record: record.exc_info is None
        streamHandler.addFilter(f)
        cls._stream_handler = streamHandler
        return streamHandler

    @classmethod
    def get_journal_handler(cls):
        if cls._journal_handler is None and journal:
            cls._journal_handler = journal.JournalHandler()
            cls._journal_handler.setLevel(cls._level)
            cls._journal_handler.setFormatter(logging.Formatter(JOURNAL_LOG_FORMAT if cls._level != logging.DEBUG else DEBUG_FORMAT))
        return cls._journal_handler

    @classmethod
    def get_queue_logger(cls):
        if cls._queue_logger is None:
            cls._queue_logger = QueueLogger(DEFAULT_NAME)
            cls._queue_logger.start_logging()
        return cls._queue_logger

    @classmethod
    def has_queue_logger(cls):
        return cls._queue_logger is not None


def init(config):
    log_dir = config['global']['log_dir']
    log_file = config['global']['log_file']
    log_per_config = config['global']['log_per_config']
    debug = config['global']['debug']
    background = config['global']['background']
    return Logger.initialize(log_dir=log_dir, log_file=log_file, log_per_config=log_per_config,
                             debug=debug, background=background)


def getLogger(name=None, config=None, queue=True):
    """
    This method does the setup necessary to create and connect both
    the main logger instance used from virtwho as well as loggers for
    all the connected virt backends

    If virt-who is running in background mode, the double fork closes all the
    filedescriptiors, disrupting communication to queue logger. So the
    queue logger is created after the initialization phase (after the fork).

    First the logger is created without the queue and it's added later on
    (after the fork).
    """

    return Logger.get_logger(name=name, config=config, queue=queue)


def getQueueLogger():
    return Logger.get_queue_logger()


def hasQueueLogger():
    return Logger.has_queue_logger()


def closeLogger(logger):
    while len(logger.handlers):
        h = logger.handlers[0]
        h.close()
        logger.removeHandler(h)

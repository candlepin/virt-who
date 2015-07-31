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
import json
from Queue import Empty
from multiprocessing import Queue
from threading import Thread, Event
import util

FILE_LOG_FORMAT = """%(asctime)s [%(levelname)s]  @%(filename)s:%(lineno)d - %(message)s"""
STREAM_LOG_FORMAT = """%(asctime)s %(levelname)s: %(message)s"""


DEBUG_FORMAT = "%(asctime)s [%(name)s %(levelname)s] " \
                "%(processName)s(%(process)d):%(threadName)s " \
                "@%(filename)s:%(funcName)s:%(lineno)d - %(message)s"

DEFAULT_FORMAT = DEBUG_FORMAT
DEFAULT_LOG_DIR = '/var/log/virtwho'
DEFAULT_LOG_FILE = 'virtwho.log'
DEFAULT_NAME = 'virtwho'

class QueueHandler(logging.Handler):
    """
    A handler that will write logrecords to a queue (Queue or multiprocessing.Queue)
    For use in logging in situations involving multiple processes
    """
    def __init__(self, queue, level=logging.NOTSET):
        super(QueueHandler, self).__init__(level)
        self._queue = queue

    def prepare(self, record):
        """
        Prepares the record to be placed on the queue
        """
        if record.exc_info:
            record.exc_text = self.formatter.formatException(record.exc_info)
            record.exc_info = None
        try:
            serialized_record = json.dumps(record.__dict__)
        except Exception as e:
            logging.error(str(e))
            serialized_record = None
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
                logger.handle(QueueLogger.prepare(record))
            else:
                exit = True

    def start_logging(self):
        self._logging_thread.start()

    def terminate(self):
        self.queue.put_nowait(None)
        self._logging_thread.join()
        self._logging_thread = None

    @staticmethod
    def prepare(record):
        return logging.makeLogRecord(json.loads(record, object_hook=util.decode))

    def getHandler(self, level=logging.NOTSET):
        # Return a queue handler that will write to this queue logger
        return QueueHandler(self.queue, level)

    def addHandler(self, handler):
        self.logger.addHandler(handler)

__DEFAULT_QUEUE_LOGGER = None


def getDefaultQueueLogger():
    """
    This method returns a default logger instance at the module level
    if it does not exist it creates it
    """
    global __DEFAULT_QUEUE_LOGGER
    if not __DEFAULT_QUEUE_LOGGER:
        __DEFAULT_QUEUE_LOGGER = QueueLogger(DEFAULT_NAME)
        __DEFAULT_QUEUE_LOGGER.start_logging()
    return __DEFAULT_QUEUE_LOGGER


def setDefaultLogDir(log_dir):
    """
    A method to change the default log directory
    """
    global DEFAULT_LOG_DIR
    if not checkDir(log_dir):
        sys.stderr.write("Default Log Directory not changed")
    else:
        DEFAULT_LOG_DIR = log_dir


def setDefaultLogFile(log_file):
    """
    Sets the default log file
    """
    global DEFAULT_LOG_FILE
    DEFAULT_LOG_FILE = log_file

def checkDir(directory):
    try:
        if not os.path.isdir(directory):
            os.mkdir(directory)
    except Exception as e:
        sys.stderr.write("Unable to create %s directory: %s" % (directory, str(e)))
        return False
    return True


def getLogger(options, config=None):
    """
    This method does the setup necessary to create and connect both
    the main logger instance used from virtwho as well as loggers for
    all the connected virt backends
    """
    # Set defaults if necessary
    if options.log_dir:
        setDefaultLogDir(options.log_dir)

    if options.log_file:
        setDefaultLogFile(options.log_file)
    # Remove the periods in the config.name (as that could mess logging up
    name = (''.join(config.name.split('.'))) if config else 'main'
    logger_name = 'virtwho.' + name  # The name of the logger instance
    logger = logging.getLogger(logger_name)
    logger.propagate = False  # Because we are using or own queue logger we don't want any of the loggers to propagate
    logger.setLevel(logging.DEBUG)
    level = logging.DEBUG if options.debug else logging.INFO

    if not options.single_log_file:
        log_file = getattr(config, 'log_file', None) or (name + '.log')
    else:
        log_file = DEFAULT_LOG_FILE
    # Add a FileHandler to the queue logger that filters on the name of the
    # newly created logger
    fileHandler = getFileHandler(logger_name,
                                 log_file,
                                 getattr(config, 'log_dir', None))
    fileHandler.setLevel(level)
    queueLogger = getDefaultQueueLogger()
    queueHandler = queueLogger.getHandler(level)  # get a QueueHandler that will send to this queuelogger

    if not options.background:
        # set up a streamhandler if we are not running in the background
        streamHandler = logging.StreamHandler()
        streamHandler.setLevel(level)
        streamHandler.addFilter(logging.Filter(logger_name))
        streamHandler.setFormatter(logging.Formatter(STREAM_LOG_FORMAT if level != logging.DEBUG else DEBUG_FORMAT))
        f = logging.Filter()
        f.filter = lambda record: record.exc_info is None
        streamHandler.addFilter(f)
        queueLogger.addHandler(streamHandler)

    fileHandler.setFormatter(logging.Formatter(FILE_LOG_FORMAT if level != logging.DEBUG else DEBUG_FORMAT))
    queueHandler.setFormatter(fileHandler.formatter)
    queueLogger.addHandler(fileHandler)
    logger.addHandler(queueHandler)

    return logger

def getFileHandler(filtername, log_file=None, log_dir=None):
    log_file = log_file or DEFAULT_LOG_FILE
    log_dir = log_dir or DEFAULT_LOG_DIR
    path = os.path.join(log_dir, log_file)
    checkDir(log_dir)
    fileHandler = None
    try:
        fileHandler = logging.handlers.WatchedFileHandler(path)
        fileHandler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        fileHandler.addFilter(logging.Filter(filtername))
    except Exception as e:
        sys.stderr.write("Unable to log to %s: %s\n" % (path, e))
    return fileHandler

"""
Test for the log module of virt-who.

Copyright (C) 2015 Christopher Snyder <csnyder@redhat.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at you option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
"""
from base import TestBase
from mock import patch, Mock, sentinel
import threading
from multiprocessing import Queue
import log


class TestLog(TestBase):
    def setUp(self):
        # Reset initial values of the Logger class variables
        log.Logger._log_dir = log.DEFAULT_LOG_DIR
        log.Logger._log_file = log.DEFAULT_LOG_FILE
        log.Logger._log_per_config = False
        log.Logger._queue_logger = None

    @patch('log.QueueLogger')
    def test_get_queue_logger(self, queueloggerClass):
        queueloggerClass.return_value = Mock()

        # These two should be the same Mock object
        defaultQueueLogger = log.getQueueLogger()
        self.addCleanup(defaultQueueLogger.terminate())
        secondQueueLogger = log.getQueueLogger()

        self.assertTrue(defaultQueueLogger == secondQueueLogger)
        defaultQueueLogger.start_logging.assert_any_call()

    @patch('os.path.isdir')
    @patch('log.Logger.get_queue_logger')
    @patch('logging.FileHandler._open')
    def test_get_logger_no_config(self, open, getQueueLogger, isdir):
        open.return_value = None
        isdir.return_value = True
        queueLogger = log.QueueLogger('virtwho')
        queueLogger.logger.handlers = []
        mockQueueLogger = Mock(wraps=queueLogger)
        getQueueLogger.return_value = mockQueueLogger
        options = Mock()
        options.debug = False
        options.background = True
        options.log_file = log.DEFAULT_LOG_FILE
        options.log_dir = log.DEFAULT_LOG_DIR
        options.log_per_config = False
        log.init(options)
        main_logger = log.getLogger(name='main')
        self.assertTrue(main_logger.name == 'virtwho.main')
        self.assertTrue(len(main_logger.handlers) == 1)
        self.assertTrue(isinstance(main_logger.handlers[0], log.QueueHandler))
        queue_handlers = queueLogger.logger.handlers
        self.assertTrue(len(queue_handlers) == 1)
        self.assertEquals(queue_handlers[0].baseFilename, '%s/%s' % (log.DEFAULT_LOG_DIR, log.DEFAULT_LOG_FILE))

    @patch('log.Logger.get_queue_logger')
    @patch('log.Logger.get_file_handler')
    def test_get_logger_different_log_file(self, getFileHandler, getQueueLogger):
        queueLogger = log.QueueLogger('virtwho')
        queueLogger.logger.handlers = []
        mockQueueLogger = Mock(wraps=queueLogger)
        getQueueLogger.return_value = mockQueueLogger

        config = Mock()
        config.name = 'test'
        config.log_file = 'test.log'
        config.log_dir = '/test/'

        options = Mock()
        options.debug = False
        options.background = True
        options.log_per_config = True
        options.log_dir = ''
        options.log_file = ''
        log.init(options)
        test_logger = log.getLogger(name='test', config=config)

        self.assertTrue(test_logger.name == 'virtwho.test')
        self.assertTrue(len(test_logger.handlers) == 1)
        self.assertTrue(len(queueLogger.logger.handlers) == 1)
        getFileHandler.assert_called_with(name=test_logger.name, config=config)

    @patch('os.path.isdir')
    @patch('logging.FileHandler._open')
    def test_get_file_handler_defaults(self, open, isdir):
        open.return_value = None  # Ensure we don't actually try to open a file
        isdir.return_value = True
        filtername = 'test'
        fileHandler = log.Logger.get_file_handler(filtername)
        self.assertEquals(fileHandler.baseFilename, '%s/%s' % (log.DEFAULT_LOG_DIR, log.DEFAULT_LOG_FILE))
        self.assertEquals(len(fileHandler.filters), 1)
        self.assertEquals(fileHandler.filters[0].name, filtername)

    @patch('os.path.isdir')
    @patch('logging.FileHandler._open')
    def test_get_file_handler(self, open, isdir):
        open.return_value = None  # Ensure we don't actually try to open a file

        # Ensure we don't try to make a directory
        isdir.return_value = True
        options = Mock()
        filtername = 'test'
        options.log_file = 'test.log'
        options.log_dir = '/nonexistant/'

        log.Logger.initialize(options)
        fileHandler = log.Logger.get_file_handler(filtername)
        self.assertEquals(fileHandler.baseFilename, options.log_dir + options.log_file)


class TestQueueLogger(TestBase):

    @patch('multiprocessing.queues.Queue')
    @patch('logging.getLogger')
    def test_queue_logger(self, getLogger, queue):
        fake_queue = sentinel.queue
        name = sentinel.name
        logger = sentinel.logger
        queue.return_value = fake_queue
        getLogger.return_value = logger
        queueLogger = log.QueueLogger(name)
        getLogger.assert_called_with(name)

        self.assertTrue(isinstance(queueLogger._logging_thread,
                                   threading.Thread))
        thread = queueLogger._logging_thread
        self.assertTrue(thread.__dict__['_Thread__target'] == log.QueueLogger._log)
        self.assertTrue(thread.__dict__['_Thread__args'] == (logger, fake_queue))
        self.assertTrue(queueLogger.queue == fake_queue)
        self.assertTrue(queueLogger.logger == logger)
        self.assertTrue(queueLogger.name == name)

    def test_log_quits_on_none(self):
        # This test will hang if the method fails to exit
        queue = Queue()
        queue.put(None)
        logger = Mock()
        log.QueueLogger._log(logger, queue)

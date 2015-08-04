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
import logging
import base
from base import TestBase
from mock import patch, Mock, sentinel
import threading
from multiprocessing import Queue
import log

class TestLog(TestBase):

    @patch('log.QueueLogger')
    def test_get_default_queue_logger(self, queueloggerClass):
        queueloggerClass.return_value = Mock()

        # These two should be the same Mock object
        defaultQueueLogger = log.getDefaultQueueLogger()
        secondQueueLogger = log.getDefaultQueueLogger()

        self.assertTrue(defaultQueueLogger == secondQueueLogger)
        defaultQueueLogger.start_logging.assert_any_call()

    @patch('os.path.isdir')
    @patch('log.getDefaultQueueLogger')
    def test_get_logger_no_config(self, getDefaultQueueLogger, isdir):
        isdir.return_value = True
        queueLogger = log.QueueLogger('virtwho')
        queueLogger.logger.handlers = []
        mockQueueLogger = Mock(wraps=queueLogger)
        getDefaultQueueLogger.return_value = mockQueueLogger
        options = Mock()
        options.debug = False
        options.background = True
        options.log_file = log.DEFAULT_LOG_FILE
        options.log_dir = log.DEFAULT_LOG_DIR
        options.log_per_config = False
        main_logger = log.getLogger(options)
        self.assertTrue(main_logger.name == 'virtwho.main')
        self.assertTrue(len(main_logger.handlers) == 1)
        self.assertTrue(isinstance(main_logger.handlers[0], log.QueueHandler))
        mockQueueLogger.getHandler.assert_called_with(logging.INFO)
        queue_handlers = queueLogger.logger.handlers
        self.assertTrue(len(queue_handlers) == 1)
        self.assertEquals(queue_handlers[0].baseFilename, '%s/%s' % (log.DEFAULT_LOG_DIR, log.DEFAULT_LOG_FILE))

    @patch('log.getDefaultQueueLogger')
    @patch('log.getFileHandler')
    def test_get_logger_different_log_file(self, getFileHandler, getDefaultQueueLogger):
        queueLogger = log.QueueLogger('virtwho')
        queueLogger.logger.handlers = []
        mockQueueLogger = Mock(wraps=queueLogger)
        getDefaultQueueLogger.return_value = mockQueueLogger

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
        test_logger = log.getLogger(options, config)

        self.assertTrue(test_logger.name == 'virtwho.test')
        self.assertTrue(len(test_logger.handlers) == 1)
        self.assertTrue(len(queueLogger.logger.handlers) == 1)
        getFileHandler.assert_called_with(test_logger.name, config.log_file, config.log_dir)

    @patch('os.path.isdir')
    def test_get_file_handler_defaults(self, isdir):
        isdir.return_value = True
        filtername = 'virtwho.test'
        fileHandler = log.getFileHandler(filtername)
        self.assertTrue(fileHandler.baseFilename == '%s/%s' % (log.DEFAULT_LOG_DIR, log.DEFAULT_LOG_FILE))
        self.assertTrue(len(fileHandler.filters) == 1)
        self.assertTrue(fileHandler.filters[0].name == filtername)


    @patch('os.path.isdir')
    def test_get_file_handler(self, isdir):
        # Monkey patching the _open function to ensure we don't try to access a
        # fake file
        real_open = logging.FileHandler._open
        logging.FileHandler._open = Mock()
        logging.FileHandler._open.return_value = None

        # Ensure we don't try to make a directory
        isdir.return_value  = True
        filtername = 'virtwho.test'
        log_file = 'test.log'
        log_dir = '/nonexistant/'

        fileHandler = log.getFileHandler(filtername,
                                         log_file,
                                         log_dir)
        self.assertTrue(fileHandler.baseFilename == log_dir + log_file)

        logging.FileHandler._open = real_open


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

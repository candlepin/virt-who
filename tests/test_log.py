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

    @patch('log.getDefaultQueueLogger')
    def test_get_logger_no_config(self, getDefaultQueueLogger):
        queueLogger = log.QueueLogger('virtwho')
        queueLogger.logger.handlers = []
        mockQueueLogger = Mock(wraps=queueLogger)
        getDefaultQueueLogger.return_value = mockQueueLogger
        options = Mock()
        options.debug = False
        options.background = True
        options.log_dir = ""
        options.log_file = ""
        main_logger = log.getLogger(options)
        self.assertTrue(main_logger.name == 'virtwho.main')
        self.assertTrue(len(main_logger.handlers) == 1)
        self.assertTrue(isinstance(main_logger.handlers[0], log.QueueHandler))
        mockQueueLogger.getHandler.assert_called_with(logging.INFO)
        queue_handlers = queueLogger.logger.handlers
        self.assertTrue(len(queue_handlers) == 1)
        self.assertTrue(queue_handlers[0].baseFilename == '%s/%s' % (log.DEFAULT_LOG_DIR, log.DEFAULT_LOG_FILE))

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
        options.single_log_file = False
        options.log_dir = ''
        options.log_file = ''
        test_logger = log.getLogger(options, config)

        self.assertTrue(test_logger.name == 'virtwho.test')
        self.assertTrue(len(test_logger.handlers) == 1)
        self.assertTrue(len(queueLogger.logger.handlers) == 1)
        getFileHandler.assert_called_with(test_logger.name, config.log_file, config.log_dir)

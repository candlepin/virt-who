from __future__ import print_function
"""
Test for basic virt-who operations.

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

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

from mock import patch, Mock, call

from base import TestBase

from virtwho import util
from virtwho.config import VW_GLOBAL
from virtwho.parser import parse_options
from virtwho.executor import Executor


class TestOptions(TestBase):
    NO_GENERAL_CONF = {'global': {}}

    def setUp(self):
        self.clearEnv()

    def tearDown(self):
        self.clearEnv()
        super(TestBase, self).tearDown()

    def clearEnv(self):
        for key in list(os.environ.keys()):
            if key.startswith("VIRTWHO"):
                del os.environ[key]

    def setUpParseFile(self, parseFileMock):
        parseFileMock.return_value = TestOptions.NO_GENERAL_CONF

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parse_file')
    def test_default_cmdline_options(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py"]
        _, options = parse_options()
        self.assertFalse(options[VW_GLOBAL]['debug'])
        self.assertFalse(options[VW_GLOBAL]['oneshot'])
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)
        self.assertEqual(options[VW_GLOBAL]['reporter_id'], util.generate_reporter_id())

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parse_file')
    def test_minimum_interval_options(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py", "--interval=5"]
        _, options = parse_options()
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)

        sys.argv = ["virtwho.py"]
        os.environ["VIRTWHO_INTERVAL"] = '1'

        _, options = parse_options()
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)

        self.clearEnv()
        bad_conf = {'global': {'interval': '1'}}
        parseFile.return_value = bad_conf

        _, options = parse_options()
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parse_file')
    def test_empty_interval_options(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py", "--interval="]
        _, options = parse_options()
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)

        sys.argv = ["virtwho.py"]
        os.environ["VIRTWHO_INTERVAL"] = ''

        _, options = parse_options()
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)

        self.clearEnv()
        bad_conf = {'global': {'interval': ''}}
        parseFile.return_value = bad_conf

        _, options = parse_options()
        self.assertEqual(options[VW_GLOBAL]['interval'], 3600)

    @patch('virtwho.log.getLogger')
    @patch('virtwho.config.parse_file')
    def test_options_debug(self, parseFile, getLogger):
        self.setUpParseFile(parseFile)
        sys.argv = ["virtwho.py", "-d"]
        _, options = parse_options()
        self.assertTrue(options[VW_GLOBAL]['debug'])


class TestExecutor(TestBase):

    @patch.object(Executor, 'terminate_threads')
    @patch('virtwho.executor.time')
    def test_wait_on_threads(self, mock_time, mock_terminate_threads):
        """
        Tests that, given no kwargs, the wait_on_threads method will wait until
        all threads is_terminated method returns True.
        Please note that a possible consequence of something going wrong in
        the wait on threads method (with no kwargs) could cause this test to
        never quit.
        """
        # Create a few mock threads
        # The both will return False the first time is_terminated is called
        # Only the second mock thread will wait not return True until the
        # third call of is_terminated
        mock_thread1 = Mock()
        mock_thread1.is_terminated = Mock(side_effect=[False, True])
        mock_thread2 = Mock()
        mock_thread2.is_terminated = Mock(side_effect=[False, False, True])

        threads = [mock_thread1, mock_thread2]

        mock_time.sleep = Mock()
        Executor.wait_on_threads(threads)
        mock_time.sleep.assert_has_calls([
            call(1),
            call(1),
        ])
        mock_terminate_threads.assert_not_called()

    def test_terminate_threads(self):
        threads = [Mock(), Mock()]
        Executor.terminate_threads(threads)
        for mock_thread in threads:
            mock_thread.stop.assert_called()
            mock_thread.join.assert_called()

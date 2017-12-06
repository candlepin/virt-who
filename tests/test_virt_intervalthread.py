from __future__ import print_function
from base import TestBase

from mock import patch, Mock, sentinel, call
from virtwho.virt import IntervalThread
from threading import Event
from datetime import datetime

class TestIntervalThreadTiming(TestBase):
    """
    This is a group of tests intended to test the timing of the interval thread.
    """

    def setUp(self):
        time_patcher = patch('time.sleep')
        self.mock_time = time_patcher.start()
        event_patcher = patch('virtwho.virt.virt.Event')
        self.mock_internal_terminate_event = event_patcher.start().return_value
        self.mock_internal_terminate_event.is_set.return_value = False
        self.addCleanup(time_patcher.stop)
        self.addCleanup(event_patcher.stop)

        # default mock objects that can be passed into a new interval thread
        self.config = Mock()
        self.source = Mock()
        self.dest = Mock()
        self.terminate_event = Mock()
        self.terminate_event.is_set.return_value = False
        self.interval = 2
        self.oneshot = True

        self._get_data_return = sentinel.default_data_to_send
        self._send_data_return = sentinel.default_send_data_return

    def setup_interval_thread(self, **kwargs):
        """
        Sets up an interval thread class with mocks of unimplemented methods
        to allow testing of the base implementation of those methods that have
        concrete implementations.
        """
        logger = kwargs.get('logger', self.logger)
        config = kwargs.get('config', self.config)
        source = kwargs.get('source', self.source)
        dest = kwargs.get('dest', self.dest)
        terminate_event = kwargs.get('terminate_event', self.terminate_event)
        interval = kwargs.get('interval', self.interval)
        oneshot = kwargs.get('oneshot', self.oneshot)

        interval_thread = IntervalThread(logger, config, source, dest,
                                         terminate_event, interval, oneshot)

        mock_get_data_impl = kwargs.get('mock_get_data', None)
        if mock_get_data_impl is None:
            mock_get_data_impl = Mock()
            mock_get_data_impl.return_value = self._get_data_return

        mock_send_data_impl = kwargs.get('mock_send_data', None)
        if mock_send_data_impl is None:
            mock_send_data_impl = Mock()
            mock_send_data_impl.return_value = self._send_data_return

        interval_thread._get_data = mock_get_data_impl
        interval_thread._send_data = mock_send_data_impl

        return interval_thread


    def test__run(self):
        """
        Tests the timing of the _run method
        """
        oneshot = False
        interval = 20  # Seconds
        start_time = datetime(1, 1, 1, 1, 1)
        time_taken = 10  # seconds, must be less than 60
        end_time = datetime(start_time.year, start_time.month,
                            start_time.day, start_time.hour, start_time.minute,
                            start_time.second + time_taken,
                            start_time.microsecond, start_time.tzinfo)
        expected_wait_time = interval - time_taken
        with patch('virtwho.virt.virt.datetime') as patcher:
            patcher.now = Mock(side_effect=[start_time, end_time])
            interval_thread = self.setup_interval_thread(oneshot=oneshot,
                                                         interval=interval)
            interval_thread.is_terminated = Mock(side_effect=[False, True])
            interval_thread.wait = Mock()
            interval_thread._run()
            interval_thread._get_data.assert_called()
            interval_thread._send_data.assert_has_calls([call(self._get_data_return)])
            interval_thread.wait.assert_has_calls([call(expected_wait_time)])

    def test__run_send_takes_longer_than_interval(self):
        """
        Tests the timing of the _run method
        """
        oneshot = False
        interval = 20  # Seconds
        start_time = datetime(1, 1, 1, 1, 1)
        time_taken = 21  # seconds, must be less than 60
        end_time = datetime(start_time.year, start_time.month,
                            start_time.day, start_time.hour, start_time.minute,
                            start_time.second + time_taken,
                            start_time.microsecond, start_time.tzinfo)
        with patch('virtwho.virt.virt.datetime') as patcher:
            patcher.now = Mock(side_effect=[start_time, end_time])
            interval_thread = self.setup_interval_thread(oneshot=oneshot,
                                                         interval=interval)
            interval_thread.is_terminated = Mock(side_effect=[False, True])
            interval_thread.wait = Mock()
            interval_thread._run()
            interval_thread._get_data.assert_called()
            interval_thread._send_data.assert_has_calls([call(self._get_data_return)])
            interval_thread.wait.assert_not_called()


    def test_wait(self):
        interval_thread = self.setup_interval_thread()
        interval_thread.is_terminated = Mock()
        interval_thread.is_terminated.return_value = False
        # The total time we expect to be waited
        wait_time = 10
        # The time we expect to be waited each interval
        expected_wait_interval = 1
        expected_calls = [call(expected_wait_interval) for x in range(wait_time)]

        interval_thread.wait(wait_time=wait_time)
        self.assertEqual(interval_thread.is_terminated.call_count, wait_time)
        self.mock_time.assert_has_calls(expected_calls)

    def test_is_terminated_terminate_event(self):
        interval_thread = self.setup_interval_thread()
        self.assertEqual(False, interval_thread.is_terminated())
        self.terminate_event.is_set.return_value = True
        self.assertEqual(True, interval_thread.is_terminated())

    def test_is_terminated_internal_terminate_event(self):
        interval_thread = self.setup_interval_thread()
        self.assertEqual(False, interval_thread.is_terminated())
        self.mock_internal_terminate_event.is_set.return_value = True
        self.assertEqual(True, interval_thread.is_terminated())

    def test_is_terminated_both_events(self):
        interval_thread = self.setup_interval_thread()
        self.assertEqual(False, interval_thread.is_terminated())
        interval_thread._internal_terminate_event.is_set.return_value = True
        self.terminate_event.is_set.return_value = True
        self.assertEqual(True, interval_thread.is_terminated())

    def test_stop(self):
        interval_thread = self.setup_interval_thread()
        interval_thread.stop()
        self.mock_internal_terminate_event.set.assert_called()

    def test_run(self):
        oneshot = False
        interval = 20  # Seconds
        interval_thread = self.setup_interval_thread(oneshot=oneshot,
                                                     interval=interval)
        interval_thread.is_terminated = Mock(side_effect=[False, False, True])
        interval_thread._run = Mock()
        interval_thread.wait = Mock()
        interval_thread.run()
        interval_thread.wait.assert_has_calls([call(interval)])

    def test_run_has_error(self):
        oneshot = False
        interval = 20  # Seconds
        interval_thread = self.setup_interval_thread(oneshot=oneshot,
                                                     interval=interval)
        interval_thread.is_terminated = Mock(side_effect=[False, False,
                                                          False, True])
        interval_thread._run = Mock(side_effect=Exception)
        interval_thread.wait = Mock()
        interval_thread.run()
        interval_thread.wait.assert_has_calls([call(interval)])

    def test_run_has_error_and_terminated(self):
        oneshot = False
        interval = 20  # Seconds
        interval_thread = self.setup_interval_thread(oneshot=oneshot,
                                                     interval=interval)
        interval_thread.is_terminated = Mock(side_effect=[False, True,
                                                          True, True])
        interval_thread._run = Mock(side_effect=Exception)
        interval_thread.wait = Mock()
        interval_thread.run()
        interval_thread.wait.assert_not_called()

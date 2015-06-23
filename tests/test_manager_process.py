from base import TestBase
from manager import managerprocess
from mock import patch, MagicMock
from config import Config
import logging

from multiprocessing import Queue, Event

class TestManagerProcess(TestBase):

    def run_manager_process(self, config, in_queue=None, out_queue=None, oneshot=False):
        mp = managerprocess.ManagerProcess(self.logger)
        mp.queue = in_queue or Queue()
        mp._out_queue = out_queue or Queue()
        mp._terminate_event = Event()
        mp._oneshot = oneshot
        mp.run()

    def test_newJobStatus(self):
        in_queue = Queue()
        out_queue = Queue()
        terminate_event = Event()
        fake_job_id = 'fake-job-id'
        in_queue.put(('newJobStatus', [Config('test', 'esx'), fake_job_id], 1))
        in_queue.put(('newJobStatus', [Config('test', 'esx'), fake_job_id, 120], 1))
        in_queue.put(('quit', [], 1))
        mp = managerprocess.ManagerProcess(self.logger)
        mp.start(in_queue, out_queue, terminate_event)
        mp.join(3)

        if(mp.is_alive()):
            mp.terminate()
            self.fail('The process took longer to quit than the time given (1 second)')
        result = in_queue.get(False)
        self.assertTrue(result.target == 'checkJobStatus')
        self.assertTrue(fake_job_id in result.args)
        self.assertTrue(result.interval == 60)
        second_result = in_queue.get(False)
        self.assertTrue(second_result.target == 'checkJobStatus')
        self.assertTrue(fake_job_id in second_result.args)
        self.assertFalse(120 in second_result.args)
        self.assertTrue(second_result.interval == 120)

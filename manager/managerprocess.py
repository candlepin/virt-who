import sys
import time
import logging
from datetime import datetime
from multiprocessing import Process
from Queue import Empty

class ManagerError(Exception):
    pass

class Job(object):
    """
    This class represents a job to be completed possibly within an interval
    Parameters:
        'target': this is the method to be executed with 'args' arguments
        'args': OPTIONAL the arguements in a list [] to be passed to 'target'
        'interval': OPTIONAL the interval in seconds to wait until execution
   Notes:
       Set 'firstRun'=True if you want this job to run the first time it is
       attempted regardless of any set interval
    """
    # TODO refactor / abstract this class so it is useful as more than a data
    # model (as that is what it is currently being used as
    def __init__(self, target,
                 args=None, interval=None, firstRun=False):
        self.target = target
        self.args = args
        self.lastChecked = None
        self._result = None
        # allow for functions that require no args
        if self.args is None:
            self.args = []

        if interval is None:
            self.interval = 0
        else:
            self.interval = interval

        if not firstRun:
            self.lastChecked = datetime.now()

class ManagerProcess(Process):
    """
    Manager backend class.

    This class is very similar and meant to run much like a virtualization backend
    process.
    The primary distinction here is that this class will handle all async
    operations coming from managers (subscription manager, satellite).

    This class will initially focus on updating job statuses but is meant
    to be expanded on
    """
    # TODO add dictionary of JOB_ID -> Job object with pertainent info

    # For now we will use a logger that is passed in
    # FIXME: Make sure we actually want multiple processes using the same logger
    def __init__(self, logger, options=None):
        super(ManagerProcess, self).__init__()
        self.logger = logger
        self.options = options

    def start(self, in_queue, out_queue, terminate_event, oneshot=False):
        """
        This starts the manager process waiting for tasks to complete
        off of 'in_queue' (which will be an instance of 'Queue.Queue' as in
        virt/virt.py)

        Items on this queue are expected to be in the form
        (target, [args], [waitInterval])

        The target is expected to be a method of this class

        'out_queue' should be the queue that virtwho will be taking tasks off
        of

        The parameters below are the same as in virt/virt.py:
        "
        `terminate_event` is `multiprocessing.Event` instance and will be set
        when the process should be terminated.

        If `oneshot` parameter is True, the data will be reported only once
        and the process will be terminated after that. `interval` and
        `terminate_event` parameters won't be used in that case.
        "
        """
        self.queue = in_queue
        self._out_queue = out_queue
        self._terminate_event = terminate_event
        self._oneshot = oneshot
        self._internal_terminate_event = False
        super(ManagerProcess, self).start()

    def checkJobStatus(self, config, job_id):
        # This method checks the status of the job using the given path
        # TODO Create a more well-defined way of interprocess communication
        self.putOnOutQueue(('checkJobStatus', [config, job_id]))

    def newJobStatus(self, config, job_id, interval=60):
        self.putOnInQueue(Job('checkJobStatus', [config, job_id], interval))

    def putOnOutQueue(self, item):
        self._out_queue.put(item)
        self.logger.debug('"%s" placed on outgoing queue.' % item)
        self.logger.debug('There are now %s tasks in the out going queue.'
                          % self._out_queue.qsize())

    def putOnInQueue(self, item):
        self.queue.put(item)
        self.logger.debug('"%s" placed on incoming queue.' % item)
        self.logger.debug('There are now %s tasks in the incoming queue.'
                          % self.queue.qsize())

    def quit(self):
        self.logger.debug('Terminating process')
        self._internal_terminate_event = True

    def run(self):
        """
        Run an interuptable loop to read off the queue -> do the job repeat
        """
        while self._oneshot or (not self._terminate_event.is_set() and not self._internal_terminate_event):
            nextJob = None
            try:
                nextJob = self.queue.get()
            except Empty:
                # In this case we really don't care if the queue is empty
                continue
            if nextJob:
                if (not isinstance(nextJob, Job)):
                    nextJob = Job(*nextJob)
                if (not nextJob.lastChecked or
                   (datetime.now() - nextJob.lastChecked).seconds >
                   nextJob.interval):
                    self.logger.debug(
                        "Running method %s with args '%s'" %
                        (nextJob.target, nextJob.args)
                    )
                    nextJob._result = getattr(self, nextJob.target)(*nextJob.args)
                else:
                    self.queue.put(nextJob)

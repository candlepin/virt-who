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
        'owner': this is the instance of the class that has the method 'target'
        'target': this is the method to be executed with 'args' arguments
        'args': OPTIONAL the arguements in a list [] to be passed to 'target'
        'interval': OPTIONAL the interval in seconds to wait until execution
   Notes:
       Set 'firstRun'=True if you want this job to run the first time it is
       attempted regardless of any set interval
    """
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

    # Returns True if the job ran, false if not
    def run(self):
        if (self.lastChecked is None or
           (datetime.now() - self.lastChecked).seconds > self._interval):
            self._result = self._method(*self._args)
            self.lastChecked = datetime.now()
            return True
        return False

    # we might want to change the way we get the result
    @property
    def result(self):
        return self._result

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
    def __init__(self, logger, options):
        super(ManagerProcess, self).__init__()
        self.logger = logger
        self.options = options
        # this is a map of job_id -> job object
        self.jobs = {}

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
        super(ManagerProcess, self).start()

    def checkJobStatus(self, config, job_id):
        # This method checks the status of the job using the given path
        # TODO Create a more well-defined way of interprocess communication
        self._out_queue.put(('checkJobStatus', [config, job_id]))

    def newJobStatus(self, config, job_id, interval=10):
        self.jobs[job_id] = Job('checkJobStatus', [config, job_id], interval)
        self.queue.put(self.jobs[job_id])

    def removeJob(self, job_id):
        del self.jobs[job_id]

    def run(self):
        """
        Run an interuptable loop to read off the queue -> do the job repeat
        """
        while self._oneshot or not self._terminate_event.is_set():
            nextJob = None
            try:
                nextJob = self.queue.get()
            except Empty:
                continue
            # TODO Modify to check if the ID passed in is in the dictionary
            if nextJob:
                if (not isinstance(nextJob, Job)):
                    nextJob = Job(*nextJob)
                # TODO: Implement the logic for checking if a job is ready to be
                # done
                if (not nextJob.lastChecked or
                   (datetime.now() - nextJob.lastChecked).seconds >
                   nextJob.interval):
                    self.logger.debug(
                        "Running method %s with args '%s'" %
                        (nextJob.target, nextJob.args)
                    )
                    nextJob._result = getattr(self, nextJob.target)(*nextJob.args)
                    #del self.jobs[nextJob.args[1]]
                else:
                    self.queue.put(nextJob)


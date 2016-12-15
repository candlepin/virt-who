import time
from multiprocessing import Event, Queue
from Queue import Empty
import errno
import socket

from virtwho import log, MinimumSendInterval

from virtwho.config import ConfigManager
from virtwho.manager import (
    Manager, ManagerThrottleError, ManagerError, ManagerFatalError)
from virtwho.virt import (
    AbstractVirtReport, ErrorReport, DomainListReport,
    HostGuestAssociationReport, Virt)

try:
    from collections import OrderedDict
except ImportError:
    # Python 2.6 doesn't have OrderedDict, we need to have our own
    from util import OrderedDict


class ReloadRequest(Exception):
    ''' Reload of virt-who was requested by sending SIGHUP signal. '''


class Executor(object):
    def __init__(self, logger, options, config_dir=None):
        """
        Executor class provides bridge between virtualization supervisor and
        Subscription Manager.

        logger - logger instance
        options - options for virt-who, parsed from command line arguments
        """
        self.logger = logger
        self.options = options
        self.terminate_event = Event()
        self.virts = []

        # Queue for getting events from virt backends
        self.queue = None

        # Dictionary with mapping between config names and report hashes,
        # used for checking if the report changed from last time
        self.last_reports_hash = {}
        # How long should we wait between reports sent to server
        self.retry_after = MinimumSendInterval
        # This counts the number of responses of http code 429
        # received between successfully sent reports
        self._429_count = 0
        self.reloading = False

        # Reports that are queued for sending
        self.queued_reports = OrderedDict()

        # Name of configs that wasn't reported in oneshot mode
        self.oneshot_remaining = set()

        # Reports that are currently processed by server
        self.reports_in_progress = []

        self.configManager = ConfigManager(self.logger, config_dir)

        for config in self.configManager.configs:
            logger.debug("Using config named '%s'" % config.name)

        self.send_after = time.time()

    def check_report_state(self, report):
        ''' Check state of one report that is being processed on server. '''
        manager = Manager.fromOptions(self.logger, self.options, report.config)
        manager.check_report_state(report)

    def check_reports_state(self):
        ''' Check status of the reports that are being processed on server. '''
        if not self.reports_in_progress:
            return
        updated = []
        for report in self.reports_in_progress:
            self.check_report_state(report)
            if report.state == AbstractVirtReport.STATE_CREATED:
                self.logger.warning("Can't check status of report that is not yet sent")
            elif report.state == AbstractVirtReport.STATE_PROCESSING:
                updated.append(report)
            else:
                self.report_done(report)
        self.reports_in_progress = updated

    def send_current_report(self):
        name, report = self.queued_reports.popitem(last=False)
        return self.send_report(name, report)

    def send_report(self, name, report):
        try:
            if self.send(report):
                # Success will reset the 429 count
                if self._429_count > 0:
                    self._429_count = 1
                    self.retry_after = MinimumSendInterval

                self.logger.debug('Report for config "%s" sent', name)
                if report.state == AbstractVirtReport.STATE_PROCESSING:
                    self.reports_in_progress.append(report)
                else:
                    self.report_done(report)
            else:
                report.state = AbstractVirtReport.STATE_FAILED
                self.logger.debug('Report from "%s" failed to sent', name)
                self.report_done(report)
        except ManagerThrottleError as e:
            self.queued_reports[name] = report
            self._429_count += 1
            self.retry_after = max(MinimumSendInterval, e.retry_after * self._429_count)
            self.send_after = time.time() + self.retry_after
            self.logger.debug('429 received, waiting %s seconds until sending again', self.retry_after)

    def report_done(self, report):
        name = report.config.name
        self.send_after = time.time() + self.options.interval
        if report.state == AbstractVirtReport.STATE_FINISHED:
            self.last_reports_hash[name] = report.hash

        if self.options.oneshot:
            try:
                self.oneshot_remaining.remove(name)
            except KeyError:
                pass

    def send(self, report):
        """
        Send list of uuids to subscription manager

        return - True if sending is successful, False otherwise
        """
        try:
            if isinstance(report, DomainListReport):
                self._sendGuestList(report)
            elif isinstance(report, HostGuestAssociationReport):
                self._sendGuestAssociation(report)
            else:
                self.logger.warn("Unable to handle report of type: %s", type(report))
        except ManagerError as e:
            self.logger.error("Unable to send data: %s", str(e))
            return False
        except ManagerFatalError:
            raise
        except ManagerThrottleError:
            raise
        except socket.error as e:
            if e.errno == errno.EINTR:
                self.logger.debug("Communication with subscription manager interrupted")
            return False
        except Exception as e:
            if self.reloading:
                # We want to skip error reporting when reloading,
                # it is caused by interrupted syscall
                self.logger.debug("Communication with subscription manager interrupted")
                return False
            exceptionCheck(e)
            self.logger.exception("Error in communication with subscription manager:")
            return False
        return True

    def _sendGuestList(self, report):
        manager = Manager.fromOptions(self.logger, self.options, report.config)
        manager.sendVirtGuests(report, self.options)

    def _sendGuestAssociation(self, report):
        manager = Manager.fromOptions(self.logger, self.options, report.config)
        manager.hypervisorCheckIn(report, self.options)

    def run(self):
        self.reloading = False
        if not self.options.oneshot:
            self.logger.debug("Starting infinite loop with %d seconds interval", self.options.interval)

        # Queue for getting events from virt backends
        if self.queue is None:
            self.queue = Queue()

        # Run the virtualization backends
        self.virts = []
        for config in self.configManager.configs:
            try:
                logger = log.getLogger(config=config)
                virt = Virt.fromConfig(logger, config)
            except Exception as e:
                self.logger.error('Unable to use configuration "%s": %s', config.name, str(e))
                continue
            # Run the process
            virt.start(self.queue, self.terminate_event, self.options.interval, self.options.oneshot)
            self.virts.append(virt)

        # This set is used both for oneshot mode and to bypass rate-limit
        # when virt-who is starting
        self.oneshot_remaining = set(virt.config.name for virt in self.virts)

        if len(self.virts) == 0:
            err = "virt-who can't be started: no suitable virt backend found"
            self.logger.error(err)
            exit(1, err)

        # queued reports depend on OrderedDict feature that if key exists
        # when setting an item, it will remain in the same order
        self.queued_reports.clear()

        # Clear last reports, we need to resend them when reloaded
        self.last_reports_hash.clear()

        # List of reports that are being processed by server
        self.reports_in_progress = []

        # Send the first report immediately
        self.send_after = time.time()

        while not self.terminate_event.is_set():
            if self.reports_in_progress:
                # Check sent report status regularly
                timeout = 1
            elif time.time() > self.send_after:
                if self.queued_reports:
                    # Reports are queued and we can send them right now,
                    # don't wait in queue
                    timeout = 0
                else:
                    # No reports in progress or queued and we can send report
                    # immediately, we can wait for report as long as we want
                    timeout = 3600
            else:
                # We can't send report right now, wait till we can
                timeout = max(1, self.send_after - time.time())

            # Wait for incoming report from virt backend or for timeout
            try:
                report = self.queue.get(block=True, timeout=timeout)
            except Empty:
                report = None
            except IOError:
                continue

            # Read rest of the reports from the queue in order to remove
            # obsoleted reports from same virt
            while True:
                if isinstance(report, ErrorReport):
                    if self.options.oneshot:
                        # Don't hang on the failed backend
                        try:
                            self.oneshot_remaining.remove(report.config.name)
                        except KeyError:
                            pass
                        self.logger.warn('Unable to collect report for config "%s"', report.config.name)
                elif isinstance(report, AbstractVirtReport):
                    if self.last_reports_hash.get(report.config.name, None) == report.hash:
                        self.logger.info('Report for config "%s" hasn\'t changed, not sending', report.config.name)
                    else:
                        if report.config.name in self.oneshot_remaining:
                            # Send the report immediately
                            self.oneshot_remaining.remove(report.config.name)
                            if not self.options.print_:
                                self.send_report(report.config.name, report)
                            else:
                                self.queued_reports[report.config.name] = report
                        else:
                            self.queued_reports[report.config.name] = report
                elif report in ['exit', 'reload']:
                    # Reload and exit reports takes priority, do not process
                    # any other reports
                    break

                # Get next report from queue
                try:
                    report = self.queue.get(block=False)
                except Empty:
                    break

            if report == 'exit':
                break
            elif report == 'reload':
                self.stop_virts()
                raise ReloadRequest()

            self.check_reports_state()

            if not self.reports_in_progress and self.queued_reports and time.time() > self.send_after:
                # No report is processed, send next one
                if not self.options.print_:
                    self.send_current_report()

            if self.options.oneshot and not self.oneshot_remaining and not self.reports_in_progress:
                break

        self.queue = None
        self.stop_virts()

        self.virt = []
        if self.options.print_:
            return self.queued_reports

    def stop_virts(self):
        for virt in self.virts:
            virt.stop()
            virt.terminate()
            virt.join()
        self.virts = []

    def terminate(self):
        self.logger.debug("virt-who is shutting down")

        # Terminate the backends before clearing the queue, the queue must be empty
        # to end a child process, otherwise it will be stuck in queue.put()
        self.terminate_event.set()
        # Give backends some time to terminate properly
        time.sleep(0.5)

        if self.queue:
            # clear the queue and put "exit" there
            try:
                while True:
                    self.queue.get(False)
            except Empty:
                pass
            self.queue.put("exit")

        # Give backends some more time to terminate properly
        time.sleep(0.5)

        self.stop_virts()

    def reload(self):
        self.logger.warn("virt-who reload")
        # Set the terminate event in all the virts
        for virt in self.virts:
            virt.stop()
        # clear the queue and put "reload" there
        try:
            while True:
                self.queue.get(False)
        except Empty:
            pass
        self.reloading = True
        self.queue.put("reload")


def exceptionCheck(e):
    try:
        # This happens when connection to server is interrupted (CTRL+C or signal)
        if e.args[0] == errno.EALREADY:
            exit(0)
    except Exception:
        pass

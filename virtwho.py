"""
Agent for reporting virtual guest IDs to subscription-manager

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

import sys
import os
import signal
import errno
import time
from multiprocessing import Event, Queue
import json

from Queue import Empty

try:
    from collections import OrderedDict
except ImportError:
    # Python 2.6 doesn't have OrderedDict, we need to have our own
    from util import OrderedDict

from daemon import daemon
from virt import Virt, AbstractVirtReport, DomainListReport, HostGuestAssociationReport, ErrorReport
from manager import Manager, ManagerError, ManagerFatalError, ManagerThrottleError
from config import Config, ConfigManager, InvalidPasswordFormat, GlobalConfig, NotSetSentinel, VIRTWHO_GENERAL_CONF_PATH
from password import InvalidKeyFile

import log
import logging

from optparse import OptionParser, OptionGroup, SUPPRESS_HELP

try:
    from systemd.daemon import notify as sd_notify
except ImportError:
    def sd_notify(status, unset_environment=False):
        pass


class ReloadRequest(Exception):
    ''' Reload of virt-who was requested by sending SIGHUP signal. '''


class OptionParserEpilog(OptionParser):
    """ Epilog is new in Python 2.5, we need to support Python 2.4. """
    def __init__(self, usage="%prog [options]", description=None, epilog=None):
        self.myepilog = epilog
        OptionParser.__init__(self, usage=usage, description=description)

    def format_help(self, formatter=None):
        if formatter is None:
            formatter = self.formatter
        help = OptionParser.format_help(self, formatter)
        return help + "\n" + self.format_myepilog(formatter) + "\n"

    def format_myepilog(self, formatter=None):
        if self.myepilog is not None:
            return formatter.format_description(self.myepilog)
        else:
            return ""

# Default interval for sending list of UUIDs
DefaultInterval = 60  # One per minute
MinimumSendInterval = 60  # One minute

PIDFILE = "/var/run/virt-who.pid"
SAT5 = "satellite"
SAT6 = "sam"


class VirtWho(object):
    def __init__(self, logger, options, config_dir=None):
        """
        VirtWho class provides bridge between virtualization supervisor and
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
        self.send_after = time.time() + self.retry_after
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
            self.logger.error("No suitable virt backend found")
            return

        # queued reports depend on OrderedDict feature that if key exists
        # when setting an item, it will remain in the same order
        self.queued_reports.clear()

        # Clear last reports, we need to resend them when reloaded
        self.last_reports_hash.clear()

        # List of reports that are being processed by server
        self.reports_in_progress = []

        # Send the first report immediatelly
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


class OptionError(Exception):
    pass


def parseOptions():
    parser = OptionParserEpilog(usage="virt-who [-d] [-i INTERVAL] [-o] [--sam|--satellite5|--satellite6] [--libvirt|--vdsm|--esx|--rhevm|--hyperv|--xen]",
                                description="Agent for reporting virtual guest IDs to subscription manager",
                                epilog="virt-who also reads enviroment variables. They have the same name as command line arguments but uppercased, with underscore instead of dash and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are considered as disabled, non-empty as enabled")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-o", "--one-shot", action="store_true", dest="oneshot", default=False, help="Send the list of guest IDs and exit immediately")
    parser.add_option("-i", "--interval", type="int", dest="interval", default=NotSetSentinel(), help="Acquire list of virtual guest each N seconds. Send if changes are detected.")
    parser.add_option("-p", "--print", action="store_true", dest="print_", default=False, help="Print the host/guest association obtained from virtualization backend (implies oneshot)")
    parser.add_option("-c", "--config", action="append", dest="configs", default=[], help="Configuration file that will be processed, can be used multiple times")
    parser.add_option("-m", "--log-per-config", action="store_true", dest="log_per_config", default=NotSetSentinel(), help="Write one log file per configured virtualization backend.\nImplies a log_dir of %s/virtwho (Default: all messages are written to a single log file)" % log.DEFAULT_LOG_DIR)
    parser.add_option("-l", "--log-dir", action="store", dest="log_dir", default=log.DEFAULT_LOG_DIR, help="The absolute path of the directory to log to. (Default '%s')" % log.DEFAULT_LOG_DIR)
    parser.add_option("-f", "--log-file", action="store", dest="log_file", default=log.DEFAULT_LOG_FILE, help="The file name to write logs to. (Default '%s')" % log.DEFAULT_LOG_FILE)
    parser.add_option("-r", "--reporter-id", action="store", dest="reporter_id", default=NotSetSentinel(), help="Label host/guest associations obtained by this instance of virt-who with the provided id.")

    virtGroup = OptionGroup(parser, "Virtualization backend", "Choose virtualization backend that should be used to gather host/guest associations")
    virtGroup.add_option("--libvirt", action="store_const", dest="virtType", const="libvirt", default=None, help="Use libvirt to list virtual guests [default]")
    virtGroup.add_option("--vdsm", action="store_const", dest="virtType", const="vdsm", help="Use vdsm to list virtual guests")
    virtGroup.add_option("--esx", action="store_const", dest="virtType", const="esx", help="Register ESX machines using vCenter")
    virtGroup.add_option("--xen", action="store_const", dest="virtType", const="xen", help="Register XEN machines using XenServer")
    virtGroup.add_option("--rhevm", action="store_const", dest="virtType", const="rhevm", help="Register guests using RHEV-M")
    virtGroup.add_option("--hyperv", action="store_const", dest="virtType", const="hyperv", help="Register guests using Hyper-V")
    parser.add_option_group(virtGroup)

    managerGroup = OptionGroup(parser, "Subscription manager", "Choose where the host/guest associations should be reported")
    managerGroup.add_option("--sam", action="store_const", dest="smType", const=SAT6, default=SAT6, help="Report host/guest associations to the Subscription Asset Manager [default]")
    managerGroup.add_option("--satellite6", action="store_const", dest="smType", const=SAT6, help="Report host/guest associations to the Satellite 6 server")
    managerGroup.add_option("--satellite5", action="store_const", dest="smType", const=SAT5, help="Report host/guest associations to the Satellite 5 server")
    managerGroup.add_option("--satellite", action="store_const", dest="smType", const=SAT5, help=SUPPRESS_HELP)
    parser.add_option_group(managerGroup)

    libvirtGroup = OptionGroup(parser, "Libvirt options", "Use these options with --libvirt")
    libvirtGroup.add_option("--libvirt-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products, default is owner of current system")
    libvirtGroup.add_option("--libvirt-env", action="store", dest="env", default="", help="Environment where the server belongs to, default is environment of current system")
    libvirtGroup.add_option("--libvirt-server", action="store", dest="server", default="", help="URL of the libvirt server to connect to, default is empty for libvirt on local computer")
    libvirtGroup.add_option("--libvirt-username", action="store", dest="username", default="", help="Username for connecting to the libvirt daemon")
    libvirtGroup.add_option("--libvirt-password", action="store", dest="password", default="", help="Password for connecting to the libvirt daemon")
    parser.add_option_group(libvirtGroup)

    esxGroup = OptionGroup(parser, "vCenter/ESX options", "Use these options with --esx")
    esxGroup.add_option("--esx-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    esxGroup.add_option("--esx-env", action="store", dest="env", default="", help="Environment where the vCenter server belongs to")
    esxGroup.add_option("--esx-server", action="store", dest="server", default="", help="URL of the vCenter server to connect to")
    esxGroup.add_option("--esx-username", action="store", dest="username", default="", help="Username for connecting to vCenter")
    esxGroup.add_option("--esx-password", action="store", dest="password", default="", help="Password for connecting to vCenter")
    parser.add_option_group(esxGroup)

    rhevmGroup = OptionGroup(parser, "RHEV-M options", "Use these options with --rhevm")
    rhevmGroup.add_option("--rhevm-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    rhevmGroup.add_option("--rhevm-env", action="store", dest="env", default="", help="Environment where the RHEV-M belongs to")
    rhevmGroup.add_option("--rhevm-server", action="store", dest="server", default="", help="URL of the RHEV-M server to connect to (preferable use secure connection - https://<ip or domain name>:<secure port, usually 8443>)")
    rhevmGroup.add_option("--rhevm-username", action="store", dest="username", default="", help="Username for connecting to RHEV-M in the format username@domain")
    rhevmGroup.add_option("--rhevm-password", action="store", dest="password", default="", help="Password for connecting to RHEV-M")
    parser.add_option_group(rhevmGroup)

    hypervGroup = OptionGroup(parser, "Hyper-V options", "Use these options with --hyperv")
    hypervGroup.add_option("--hyperv-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    hypervGroup.add_option("--hyperv-env", action="store", dest="env", default="", help="Environment where the Hyper-V belongs to")
    hypervGroup.add_option("--hyperv-server", action="store", dest="server", default="", help="URL of the Hyper-V server to connect to")
    hypervGroup.add_option("--hyperv-username", action="store", dest="username", default="", help="Username for connecting to Hyper-V")
    hypervGroup.add_option("--hyperv-password", action="store", dest="password", default="", help="Password for connecting to Hyper-V")
    parser.add_option_group(hypervGroup)

    xenGroup = OptionGroup(parser, "XenServer options", "Use these options with --xen")
    xenGroup.add_option("--xen-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    xenGroup.add_option("--xen-env", action="store", dest="env", default="", help="Environment where the XenServer belongs to")
    xenGroup.add_option("--xen-server", action="store", dest="server", default="", help="URL of the XenServer server to connect to")
    xenGroup.add_option("--xen-username", action="store", dest="username", default="", help="Username for connecting to XenServer")
    xenGroup.add_option("--xen-password", action="store", dest="password", default="", help="Password for connecting to XenServer")
    parser.add_option_group(xenGroup)

    satelliteGroup = OptionGroup(parser, "Satellite 5 options", "Use these options with --satellite5")
    satelliteGroup.add_option("--satellite-server", action="store", dest="sat_server", default="", help="Satellite server URL")
    satelliteGroup.add_option("--satellite-username", action="store", dest="sat_username", default="", help="Username for connecting to Satellite server")
    satelliteGroup.add_option("--satellite-password", action="store", dest="sat_password", default="", help="Password for connecting to Satellite server")
    parser.add_option_group(satelliteGroup)

    (cli_options, args) = parser.parse_args()

    options = GlobalConfig.fromFile(VIRTWHO_GENERAL_CONF_PATH)

    # Handle defaults from the command line options parser

    options.update(**parser.defaults)

    # Handle enviroment variables

    env = os.getenv("VIRTWHO_LOG_PER_CONFIG", "0").strip().lower()
    if env in ["1", "true"]:
        options.log_per_config = True

    env = os.getenv("VIRTWHO_LOG_DIR", log.DEFAULT_LOG_DIR).strip()
    if env != log.DEFAULT_LOG_DIR:
        options.log_dir = env
    elif options.log_per_config:
        options.log_dir = os.path.join(log.DEFAULT_LOG_DIR, 'virtwho')

    env = os.getenv("VIRTWHO_LOG_FILE", log.DEFAULT_LOG_FILE).strip()
    if env != log.DEFAULT_LOG_FILE:
        options.log_file = env

    env = os.getenv("VIRTWHO_REPORTER_ID", "").strip()
    if len(env) > 0:
        options.reporter_id = env

    env = os.getenv("VIRTWHO_DEBUG", "0").strip().lower()
    if env in ["1", "true"] or cli_options.debug is True:
        options.debug = True

    # Used only when starting as service (initscript sets it to 1, systemd to 0)
    env = os.getenv("VIRTWHO_BACKGROUND", "0").strip().lower()
    options.background = env in ["1", "true"]

    log.init(options)
    logger = log.getLogger(name='init', queue=False)

    env = os.getenv("VIRTWHO_ONE_SHOT", "0").strip().lower()
    if env in ["1", "true"]:
        options.oneshot = True

    env = os.getenv("VIRTWHO_INTERVAL")
    if env:
        env = env.strip().lower()
    try:
        if env and int(env) >= MinimumSendInterval:
            options.interval = int(env)
    except ValueError:
        logger.warning("Interval is not number, ignoring")

    env = os.getenv("VIRTWHO_SAM", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT6

    env = os.getenv("VIRTWHO_SATELLITE6", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT6

    env = os.getenv("VIRTWHO_SATELLITE5", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT5

    env = os.getenv("VIRTWHO_SATELLITE", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = SAT5

    env = os.getenv("VIRTWHO_LIBVIRT", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "libvirt"

    env = os.getenv("VIRTWHO_VDSM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "vdsm"

    env = os.getenv("VIRTWHO_ESX", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "esx"

    env = os.getenv("VIRTWHO_XEN", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "xen"

    env = os.getenv("VIRTWHO_RHEVM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "rhevm"

    env = os.getenv("VIRTWHO_HYPERV", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "hyperv"

    def getNonDefaultOptions(cli_options, defaults):
        return dict((option, value) for option, value in cli_options.iteritems()
                    if defaults.get(option, NotSetSentinel()) != value)

    # Handle non-default command line options
    options.update(**getNonDefaultOptions(vars(cli_options), parser.defaults))

    # Check Env
    def checkEnv(variable, option, name, required=True):
        """
        If `option` is empty, check enviroment `variable` and return its value.
        Exit if it's still empty
        """
        if not option or len(option) == 0:
            option = os.getenv(variable, "").strip()
        if required and (not option or len(option) == 0):
            raise OptionError("Required parameter '%s' is not set, exiting" % name)
        return option

    if options.smType == SAT5:
        options.sat_server = checkEnv("VIRTWHO_SATELLITE_SERVER", options.sat_server, "satellite-server")
        options.sat_username = checkEnv("VIRTWHO_SATELLITE_USERNAME", options.sat_username, "satellite-username")
        if len(options.sat_password) == 0:
            options.sat_password = os.getenv("VIRTWHO_SATELLITE_PASSWORD", "")

    if options.virtType == "libvirt":
        options.owner = checkEnv("VIRTWHO_LIBVIRT_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_LIBVIRT_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_LIBVIRT_SERVER", options.server, "server", required=False)
        options.username = checkEnv("VIRTWHO_LIBVIRT_USERNAME", options.username, "username", required=False)
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_LIBVIRT_PASSWORD", "")

    if options.virtType == "esx":
        options.owner = checkEnv("VIRTWHO_ESX_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_ESX_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_ESX_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_ESX_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_ESX_PASSWORD", "")

    if options.virtType == "xen":
        options.owner = checkEnv("VIRTWHO_XEN_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_XEN_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_XEN_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_XEN_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_XEN_PASSWORD", "")

    if options.virtType == "rhevm":
        options.owner = checkEnv("VIRTWHO_RHEVM_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_RHEVM_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_RHEVM_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_RHEVM_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_RHEVM_PASSWORD", "")

    if options.virtType == "hyperv":
        options.owner = checkEnv("VIRTWHO_HYPERV_OWNER", options.owner, "owner", required=False)
        options.env = checkEnv("VIRTWHO_HYPERV_ENV", options.env, "env", required=False)
        options.server = checkEnv("VIRTWHO_HYPERV_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_HYPERV_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_HYPERV_PASSWORD", "")

    if options.smType == 'sam' and options.virtType in ('esx', 'rhevm', 'hyperv', 'xen'):
        if not options.owner:
            raise OptionError("Option --%s-owner (or VIRTWHO_%s_OWNER environment variable) needs to be set" % (options.virtType, options.virtType.upper()))
        if not options.env:
            raise OptionError("Option --%s-env (or VIRTWHO_%s_ENV environment variable) needs to be set" % (options.virtType, options.virtType.upper()))

    if options.interval < MinimumSendInterval:
        if not options.interval or options.interval == parser.defaults['interval']:
            logger.info("Interval set to the default of %d seconds.", DefaultInterval)
        else:
            logger.warning("Interval value may not be set below the default of %d seconds. Will use default value.", MinimumSendInterval)
        options.interval = MinimumSendInterval

    if options.print_:
        options.oneshot = True

    logger.info("Using reporter_id='%s'", options.reporter_id)
    return (logger, options)


class PIDLock(object):
    def __init__(self, filename):
        self.filename = filename

    def is_locked(self):
        try:
            with open(self.filename, "r") as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                # Process no longer exists
                print >>sys.stderr, "PID file exists but associated process does not, deleting PID file"
                os.remove(self.filename)
                return False
        except Exception:
            return False

    def __enter__(self):
        # Write pid to pidfile
        try:
            with os.fdopen(os.open(self.filename, os.O_WRONLY | os.O_CREAT, 0600), 'w') as f:
                f.write("%d" % os.getpid())
        except Exception as e:
            print >>sys.stderr, "Unable to create pid file: %s" % str(e)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.filename)
        except Exception:
            pass


virtWho = None


def atexit_fn(*args, **kwargs):
    global virtWho
    if virtWho:
        virtWho.terminate()
    virtWho = None


def reload(signal, stackframe):
    if virtWho:
        virtWho.reload()


def main():
    try:
        logger, options = parseOptions()
    except OptionError as e:
        print >>sys.stderr, str(e)
        exit(1, status="virt-who can't be started: %s" % str(e))

    lock = PIDLock(PIDFILE)
    if lock.is_locked():
        msg = "virt-who seems to be already running. If not, remove %s" % PIDFILE
        print >>sys.stderr, msg
        exit(1, status=msg)

    global virtWho
    try:
        virtWho = VirtWho(logger, options)
    except (InvalidKeyFile, InvalidPasswordFormat) as e:
        logger.error(str(e))
        exit(1, "virt-who can't be started: %s" % str(e))

    if options.virtType is not None:
        config = Config("env/cmdline", options.virtType, virtWho.configManager._defaults, **options)
        config.checkOptions(logger)
        virtWho.configManager.addConfig(config)
    for conffile in options.configs:
        try:
            virtWho.configManager.readFile(conffile)
        except Exception as e:
            logger.error('Config file "%s" skipped because of an error: %s', conffile, str(e))
    if len(virtWho.configManager.configs) == 0:
        # In order to keep compatibility with older releases of virt-who,
        # fallback to using libvirt as default virt backend
        logger.info("No configurations found, using libvirt as backend")
        virtWho.configManager.addConfig(Config("env/cmdline", "libvirt"))

    for config in virtWho.configManager.configs:
        if config.name is None:
            logger.info('Using commandline or sysconfig configuration ("%s" mode)', config.type)
        else:
            logger.info('Using configuration "%s" ("%s" mode)', config.name, config.type)

    log.closeLogger(logger)
    if options.background:
        locker = lambda: daemon.DaemonContext(pidfile=lock)  # flake8: noqa
    else:
        locker = lambda: lock  # flake8: noqa

    with locker():
        signal.signal(signal.SIGHUP, reload)
        signal.signal(signal.SIGTERM, atexit_fn)

        virtWho.logger = logger = log.getLogger(name='main', config=None, queue=True)

        sd_notify("READY=1\nMAINPID=%d" % os.getpid())
        while True:
            try:
                return _main(virtWho)
            except ReloadRequest:
                logger.info("Reloading")
                continue


def _main(virtWho):
    try:
        result = virtWho.run()
    except ManagerFatalError:
        virtWho.stop_virts()
        virtWho.logger.exception("Fatal error:")
        if not virtWho.options.oneshot:
            virtWho.logger.info("Waiting for reload signal")
            # Wait indefinately until we get reload or exit signal
            while True:
                report = virtWho.queue.get(block=True)
                if report == 'reload':
                    raise ReloadRequest()
                elif report == 'exit':
                    return 0

    if virtWho.options.print_:
        if len(result) == 0:
            virtWho.logger.error("No hypervisor reports found")
            return 1
        hypervisors = []
        for config, report in result.items():
            if isinstance(report, DomainListReport):
                hypervisors.append({
                    'guests': [guest.toDict() for guest in report.guests]
                })
            elif isinstance(report, HostGuestAssociationReport):
                for hypervisor in report.association['hypervisors']:
                    h = OrderedDict((
                        ('uuid', hypervisor.hypervisorId),
                        ('guests', [guest.toDict() for guest in hypervisor.guestIds])
                    ))
                    hypervisors.append(h)
        data = json.dumps({
            'hypervisors': hypervisors
        })
        virtWho.logger.debug("Associations found: %s", json.dumps({
            'hypervisors': hypervisors
        }, indent=4, sort_keys=True))
        print(data)
    return 0


def exit(code, status=None):
    """
    exits with the code provided, properly disposing of resources

    If status is not None, use sd_notify to report the status to systemd
    """
    if status is not None:
        sd_notify("STATUS=%s" % status)

    if virtWho:
        virtWho.terminate()
    if log.hasQueueLogger():
        queueLogger = log.getQueueLogger()
        queueLogger.terminate()
    sys.exit(code)

if __name__ == '__main__':  # pragma: no cover
    try:
        res = main()
    except KeyboardInterrupt:
        exit(1)
    except Exception as e:
        print >>sys.stderr, e
        import traceback
        traceback.print_exc(file=sys.stderr)
        logger = logging.getLogger("virtwho.main")
        logger.exception("Fatal error:")
        exit(1, "virt-who failed: %s" % str(e))
    logger = logging.getLogger("virtwho.main")
    logger.debug("virt-who terminated")
    exit(res)

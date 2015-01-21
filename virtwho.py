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
import time
import atexit
import signal
import errno
import threading

from daemon import daemon
from virt import Virt, VirtError
from manager import Manager, ManagerError
from config import Config, ConfigManager

import logging
import log

from optparse import OptionParser, OptionGroup


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

from ConfigParser import NoOptionError

# Default interval to retry after unsuccessful run
RetryInterval = 60 # One minute
# Default interval for sending list of UUIDs
DefaultInterval = 3600 # Once per hour

PIDFILE = "/var/run/virt-who.pid"


class VirtWho(object):
    def __init__(self, logger, options):
        """
        VirtWho class provides bridge between virtualization supervisor and
        Subscription Manager.

        logger - logger instance
        options - options for virt-who, parsed from command line arguments
        """
        self.logger = logger
        self.options = options
        self.sync_event = threading.Event()

        self.configManager = ConfigManager()
        for config in self.configManager.configs:
            logger.debug("Using config named '%s'" % config.name)

        self.unableToRecoverStr = "Unable to recover"
        if not options.oneshot:
            self.unableToRecoverStr += ", retry in %d seconds." % RetryInterval

    def send(self):
        """
        Send list of uuids to subscription manager

        return - True if sending is successful, False otherwise
        """
        # Try to send it twice
        result = True
        for config in self.configManager.configs:
            if not self._send(config, True):
                result = False
        return result

    def _send(self, config, retry):
        """
        Send list of uuids to subscription manager. This method will call itself
        once if sending fails.

        retry - Should be True on first run, False on second.
        return - True if sending is successful, False otherwise
        """
        virt = Virt.fromConfig(self.logger, config)
        try:
            virtualGuests = self._readGuests(virt)
        except Exception as e:
            exceptionCheck(e)
            # Retry once
            if retry:
                self.logger.exception("Error in communication with virtualization backend, trying to recover:")
                return self._send(config, False)
            else:
                self.logger.error(self.unableToRecoverStr)
                return False

        try:
            self._sendGuests(virt, virtualGuests)
        except Exception as e:
            # Communication with subscription manager failed
            exceptionCheck(e)
            # Retry once
            if retry:
                self.logger.exception("Error in communication with subscription manager, trying to recover:")
                return self._send(config, False)
            else:
                self.logger.error(self.unableToRecoverStr)
                return False
        return True

    def _readGuests(self, virt):
        if not self.options.oneshot and virt.canMonitor():
            virt.startMonitoring(self.sync_event)
        if not virt.isHypervisor():
            return virt.listDomains()
        else:
            return virt.getHostGuestMapping()

    def _sendGuests(self, virt, virtualGuests):
        manager = Manager.fromOptions(self.logger, self.options)
        if not virt.isHypervisor():
            manager.sendVirtGuests(virtualGuests)
        else:
            result = manager.hypervisorCheckIn(virt.config, virtualGuests, virt.config.type)

            # Show the result of hypervisorCheckIn
            for fail in result['failedUpdate']:
                self.logger.error("Error during update list of guests: %s", str(fail))
            for updated in result['updated']:
                guests = [x['guestId'] for x in updated['guestIds']]
                self.logger.info("Updated host: %s with guests: [%s]", updated['uuid'], ", ".join(guests))
            for created in result['created']:
                guests = [x['guestId'] for x in created['guestIds']]
                self.logger.info("Created host: %s with guests: [%s]", created['uuid'], ", ".join(guests))

    def run(self):
        if self.options.background and self.options.virtType == "libvirt":
            self.logger.debug("Starting infinite loop with %d seconds interval and event handling" % self.options.interval)
        else:
            self.logger.debug("Starting infinite loop with %d seconds interval" % self.options.interval)

        while 1:
            # Run in infinite loop and send list of UUIDs every 'options.interval' seconds

            if self.send():
                timeout = self.options.interval
            else:
                timeout = RetryInterval

            self.sync_event.wait(timeout)
            self.sync_event.clear()

    def reload(self):
        try:
            self.sync_event.set()
        except Exception:
            raise


def exceptionCheck(e):
    try:
        # This happens when connection to server is interrupted (CTRL+C or signal)
        if e.args[0] == errno.EALREADY:
            sys.exit(0)
    except Exception:
        pass


def parseOptions():
    parser = OptionParserEpilog(usage="virt-who [-d] [-i INTERVAL] [-b] [-o] [--sam|--satellite] [--libvirt|--vdsm|--esx|--rhevm|--hyperv]",
                                description="Agent for reporting virtual guest IDs to subscription manager",
                                epilog="virt-who also reads enviromental variables. They have the same name as command line arguments but uppercased, with underscore instead of dash and prefixed with VIRTWHO_ (e.g. VIRTWHO_ONE_SHOT). Empty variables are considered as disabled, non-empty as enabled")
    parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Enable debugging output")
    parser.add_option("-b", "--background", action="store_true", dest="background", default=False, help="Run in the background and monitor virtual guests")
    parser.add_option("-o", "--one-shot", action="store_true", dest="oneshot", default=False, help="Send the list of guest IDs and exit immediately")
    parser.add_option("-i", "--interval", type="int", dest="interval", default=0, help="Acquire and send list of virtual guest each N seconds")

    virtGroup = OptionGroup(parser, "Virtualization backend", "Choose virtualization backend that should be used to gather host/guest associations")
    virtGroup.add_option("--libvirt", action="store_const", dest="virtType", const="libvirt", default=None, help="Use libvirt to list virtual guests [default]")
    virtGroup.add_option("--vdsm", action="store_const", dest="virtType", const="vdsm", help="Use vdsm to list virtual guests")
    virtGroup.add_option("--esx", action="store_const", dest="virtType", const="esx", help="Register ESX machines using vCenter")
    virtGroup.add_option("--rhevm", action="store_const", dest="virtType", const="rhevm", help="Register guests using RHEV-M")
    virtGroup.add_option("--hyperv", action="store_const", dest="virtType", const="hyperv", help="Register guests using Hyper-V")
    parser.add_option_group(virtGroup)

    managerGroup = OptionGroup(parser, "Subscription manager", "Choose where the host/guest associations should be reported")
    managerGroup.add_option("--sam", action="store_const", dest="smType", const="sam", default="sam", help="Report host/guest associations to the Subscription Asset Manager or Satellite 6 [default]")
    managerGroup.add_option("--satellite", action="store_const", dest="smType", const="satellite", help="Report host/guest associations to the Satellite 5")
    parser.add_option_group(managerGroup)

    libvirtGroup = OptionGroup(parser, "Libvirt options", "Use this options with --libvirt")
    libvirtGroup.add_option("--libvirt-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products, default is owner of current system")
    libvirtGroup.add_option("--libvirt-env", action="store", dest="env", default="", help="Environment where the vCenter server belongs to, default is environment of current system")
    libvirtGroup.add_option("--libvirt-server", action="store", dest="server", default="", help="URL of the libvirt server to connect to, default is empty for libvirt on local computer")
    libvirtGroup.add_option("--libvirt-username", action="store", dest="username", default="", help="Username for connecting to the libvirt daemon")
    libvirtGroup.add_option("--libvirt-password", action="store", dest="password", default="", help="Password for connecting to the libvirt daemon")
    parser.add_option_group(libvirtGroup)

    esxGroup = OptionGroup(parser, "vCenter/ESX options", "Use this options with --esx")
    esxGroup.add_option("--esx-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    esxGroup.add_option("--esx-env", action="store", dest="env", default="", help="Environment where the vCenter server belongs to")
    esxGroup.add_option("--esx-server", action="store", dest="server", default="", help="URL of the vCenter server to connect to")
    esxGroup.add_option("--esx-username", action="store", dest="username", default="", help="Username for connecting to vCenter")
    esxGroup.add_option("--esx-password", action="store", dest="password", default="", help="Password for connecting to vCenter")
    parser.add_option_group(esxGroup)

    rhevmGroup = OptionGroup(parser, "RHEV-M options", "Use this options with --rhevm")
    rhevmGroup.add_option("--rhevm-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    rhevmGroup.add_option("--rhevm-env", action="store", dest="env", default="", help="Environment where the RHEV-M belongs to")
    rhevmGroup.add_option("--rhevm-server", action="store", dest="server", default="", help="URL of the RHEV-M server to connect to (preferable use secure connection - https://<ip or domain name>:<secure port, usually 8443>)")
    rhevmGroup.add_option("--rhevm-username", action="store", dest="username", default="", help="Username for connecting to RHEV-M in the format username@domain")
    rhevmGroup.add_option("--rhevm-password", action="store", dest="password", default="", help="Password for connecting to RHEV-M")
    parser.add_option_group(rhevmGroup)

    hypervGroup = OptionGroup(parser, "Hyper-V options", "Use this options with --hyperv")
    hypervGroup.add_option("--hyperv-owner", action="store", dest="owner", default="", help="Organization who has purchased subscriptions of the products")
    hypervGroup.add_option("--hyperv-env", action="store", dest="env", default="", help="Environment where the Hyper-V belongs to")
    hypervGroup.add_option("--hyperv-server", action="store", dest="server", default="", help="URL of the Hyper-V server to connect to")
    hypervGroup.add_option("--hyperv-username", action="store", dest="username", default="", help="Username for connecting to Hyper-V")
    hypervGroup.add_option("--hyperv-password", action="store", dest="password", default="", help="Password for connecting to Hyper-V")
    parser.add_option_group(hypervGroup)

    satelliteGroup = OptionGroup(parser, "Satellite options", "Use this options with --satellite")
    satelliteGroup.add_option("--satellite-server", action="store", dest="sat_server", default="", help="Satellite server URL")
    satelliteGroup.add_option("--satellite-username", action="store", dest="sat_username", default="", help="Username for connecting to Satellite server")
    satelliteGroup.add_option("--satellite-password", action="store", dest="sat_password", default="", help="Password for connecting to Satellite server")
    parser.add_option_group(satelliteGroup)

    (options, args) = parser.parse_args()

    # Handle enviromental variables

    env = os.getenv("VIRTWHO_DEBUG", "0").strip().lower()
    if env in ["1", "true"]:
        options.debug = True

    env = os.getenv("VIRTWHO_BACKGROUND", "0").strip().lower()
    if env in ["1", "true"]:
        options.background = True

    logger = log.getLogger(options.debug, options.background)

    env = os.getenv("VIRTWHO_ONE_SHOT", "0").strip().lower()
    if env in ["1", "true"]:
        options.oneshot = True

    env = os.getenv("VIRTWHO_INTERVAL", "0").strip().lower()
    try:
        if int(env) > 0 and options.interval == 0:
            options.interval = int(env)
    except ValueError:
        logger.warning("Interval is not number, ignoring")

    env = os.getenv("VIRTWHO_SAM", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = "sam"

    env = os.getenv("VIRTWHO_SATELLITE", "0").strip().lower()
    if env in ["1", "true"]:
        options.smType = "satellite"

    env = os.getenv("VIRTWHO_LIBVIRT", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "libvirt"

    env = os.getenv("VIRTWHO_VDSM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "vdsm"

    env = os.getenv("VIRTWHO_ESX", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "esx"

    env = os.getenv("VIRTWHO_RHEVM", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "rhevm"

    env = os.getenv("VIRTWHO_HYPERV", "0").strip().lower()
    if env in ["1", "true"]:
        options.virtType = "hyperv"

    def checkEnv(variable, option, name, required=True):
        """
        If `option` is empty, check enviromental `variable` and return its value.
        Exit if it's still empty
        """
        if len(option) == 0:
            option = os.getenv(variable, "").strip()
        if required and len(option) == 0:
            logger.error("Required parameter '%s' is not set, exitting" % name)
            sys.exit(1)
        return option

    if options.smType == "satellite":
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
        options.owner = checkEnv("VIRTWHO_ESX_OWNER", options.owner, "owner")
        options.env = checkEnv("VIRTWHO_ESX_ENV", options.env, "env")
        options.server = checkEnv("VIRTWHO_ESX_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_ESX_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_ESX_PASSWORD", "")

    if options.virtType == "rhevm":
        options.owner = checkEnv("VIRTWHO_RHEVM_OWNER", options.owner, "owner")
        options.env = checkEnv("VIRTWHO_RHEVM_ENV", options.env, "env")
        options.server = checkEnv("VIRTWHO_RHEVM_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_RHEVM_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_RHEVM_PASSWORD", "")

    if options.virtType == "hyperv":
        options.owner = checkEnv("VIRTWHO_HYPERV_OWNER", options.owner, "owner")
        options.env = checkEnv("VIRTWHO_HYPERV_ENV", options.env, "env")
        options.server = checkEnv("VIRTWHO_HYPERV_SERVER", options.server, "server")
        options.username = checkEnv("VIRTWHO_HYPERV_USERNAME", options.username, "username")
        if len(options.password) == 0:
            options.password = os.getenv("VIRTWHO_HYPERV_PASSWORD", "")

    if options.interval < 0:
        logger.warning("Interval is not positive number, ignoring")
        options.interval = 0

    if options.background and options.oneshot:
        logger.error("Background and oneshot can't be used together, using background mode")
        options.oneshot = False

    if options.oneshot and options.interval > 0:
        logger.error("Interval doesn't make sense in oneshot mode, ignoring")

    if not options.oneshot and options.interval == 0:
        # Interval is still used in background mode, because events can get lost
        # (e.g. libvirtd restart)
        options.interval = DefaultInterval

    return (logger, options)


class PIDLock(object):
    def __init__(self, filename):
        self.filename = filename

    def is_locked(self):
        try:
            f = open(self.filename, "r")
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
            f = open(self.filename, "w")
            f.write("%d" % os.getpid())
            f.close()
        except Exception as e:
            print >>sys.stderr, "Unable to create pid file: %s" % str(e)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.filename)
        except Exception:
            pass


def main():
    lock = PIDLock(PIDFILE)
    if lock.is_locked():
        print >>sys.stderr, "virt-who seems to be already running. If not, remove %s" % PIDFILE
        sys.exit(1)
    logger, options = parseOptions()

    if options.background:
        # Do a daemon initialization
        with daemon.DaemonContext(pidfile=lock, files_preserve=[logger.handlers[0].stream]):
            _main(logger, options)
    else:
        with lock:
            _main(logger, options)


def _main(logger, options):
    global RetryInterval
    if options.interval < RetryInterval:
        RetryInterval = options.interval

    virtWho = VirtWho(logger, options)
    if options.virtType is not None:
        config = Config(None, options.virtType, options.server,
                        options.username, options.password, options.owner, options.env)
        virtWho.configManager.addConfig(config)
    if len(virtWho.configManager.configs) == 0:
        # In order to keep compatibility with older releases of virt-who,
        # fallback to using libvirt as default virt backend
        logger.info("No configurations found, using libvirt as backend")
        virtWho.configManager.addConfig(Config("virt-who", "libvirt"))

    for config in virtWho.configManager.configs:
        if config.name is None:
            logger.info('Using commandline or sysconfig configuration ("%s" mode)' % config.type)
        else:
            logger.info('Using configuration "%s" ("%s" mode)' % (config.name, config.type))

    def reload(signal, stackframe):
        virtWho.reload()
    signal.signal(signal.SIGHUP, reload)

    if options.oneshot:
        # Send list of virtual guests and exit
        virtWho.send()
    else:
        virtWho.run()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger = log.getLogger(False, False)
        logger.exception("Fatal error:")
        sys.exit(1)

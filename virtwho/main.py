# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import
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
import requests
import json

try:
    from collections import OrderedDict
except ImportError:
    # Python 2.6 doesn't have OrderedDict, we need to have our own
    from .util import OrderedDict

from virtwho import log
from virtwho.config import InvalidPasswordFormat, VW_GLOBAL
from virtwho.daemon import daemon
from virtwho.executor import Executor, ReloadRequest, ExitRequest
from virtwho.parser import parse_options, OptionError
from virtwho.password import InvalidKeyFile
from virtwho.virt import DomainListReport, HostGuestAssociationReport

try:
    from systemd.daemon import notify as sd_notify
except ImportError:
    def sd_notify(status, unset_environment=False):
        pass

# Disable Insecure Request warning from requests library
try:
    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.InsecureRequestWarning)
except AttributeError:
    pass

PIDFILE = "/var/run/virt-who.pid"


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
                print("PID file exists but associated process " \
                                     "does not, deleting PID file", file=sys.stderr)
                os.remove(self.filename)
                return False
        except Exception:
            return False

    def __enter__(self):
        # Write pid to pidfile
        try:
            with os.fdopen(
                    os.open(self.filename, os.O_WRONLY | os.O_CREAT, 0o600),
                    'w') as f:
                f.write("%d" % os.getpid())
        except Exception as e:
            print("Unable to create pid file: %s" % str(e), file=sys.stderr)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.filename)
        except Exception:
            pass


executor = None


def atexit_fn(*args, **kwargs):
    global executor
    if executor:
        executor.terminate()
    executor = None


def reload(signal, stackframe):
    if executor:
        executor.reload()
        raise ReloadRequest()
    exit(1, status="virt-who cannot reload, exiting")


def main():
    logger = effective_config = None
    try:
        logger, effective_config = parse_options()
        # We now have the effective_config
    except OptionError as e:
        print(str(e), file=sys.stderr)
        exit(1, status="virt-who can't be started: %s" % str(e))

    lock = PIDLock(PIDFILE)
    if lock.is_locked():
        msg = "virt-who seems to be already running. If not, remove %s" % \
              PIDFILE
        print(msg, file=sys.stderr)
        exit(1, status=msg)

    if not effective_config[VW_GLOBAL].is_valid():
        message = "Required section 'global' is invalid:\n"
        message += "\n".join([msg for (level, msg) in effective_config[VW_GLOBAL].validation_messages])
        message += "\n"
        exit(1, "virt-who can't be started: %s" % message)

    valid_virt_sections = [(name, section) for (name, section) in effective_config.virt_sections()
                           if section.is_valid()]

    if not valid_virt_sections:
        err = "virt-who can't be started: no valid configuration found"
        logger.error(err)
        exit(1, err)

    global executor
    has_error = False
    try:
        executor = Executor(logger, effective_config)
    except (InvalidKeyFile, InvalidPasswordFormat) as e:
        logger.error(str(e))
        exit(1, "virt-who can't be started: %s" % str(e))

    if len(executor.dest_to_source_mapper.dests) == 0:
        if has_error:
            err = "virt-who can't be started: no valid destination found"
            logger.error(err)
            exit(1, err)

    for name, config in executor.dest_to_source_mapper.configs:
        logger.info('Using configuration "%s" ("%s" mode)', name,
                    config['type'])

    logger.info("Using reporter_id='%s'", effective_config[VW_GLOBAL]['reporter_id'])
    log.closeLogger(logger)

    with lock:
        signal.signal(signal.SIGHUP, reload)
        signal.signal(signal.SIGTERM, atexit_fn)

        executor.logger = logger = log.getLogger(name='main', queue=True)

        sd_notify("READY=1\nMAINPID=%d" % os.getpid())
        while True:
            try:
                return _main(executor)
            except ReloadRequest:
                logger.info("Reloading")
                continue
            except ExitRequest as e:
                exit(e.code, status=e.message)


def _main(executor):
    if executor.options[VW_GLOBAL]['oneshot']:
        result = executor.run_oneshot()

        if executor.options[VW_GLOBAL]['print']:
            if not result:
                executor.logger.error("No hypervisor reports found")
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
                            ('guests',
                             [guest.toDict() for guest in hypervisor.guestIds])
                        ))
                        if hypervisor.facts:
                            h['facts'] = hypervisor.facts
                        if hypervisor.name:
                            h['name'] = hypervisor.name
                        hypervisors.append(h)
            data = json.dumps({
                'hypervisors': hypervisors
            })
            executor.logger.debug("Associations found: %s", json.dumps({
                'hypervisors': hypervisors
            }, indent=4, sort_keys=True))
            print(data)
        return 0

    # We'll get here only if we're not in oneshot or print_ mode (which
    # implies oneshot)

    # There should not be a way for us to leave this method unless it is time
    #  to exit
    executor.run()

    return 0


def exit(code, status=None):
    """
    exits with the code provided, properly disposing of resources

    If status is not None, use sd_notify to report the status to systemd
    """
    if status is not None and status != "":
        sd_notify("STATUS=%s" % status)

    if executor:
        try:
            executor.terminate()
        except KeyboardInterrupt:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            for v in executor.virts:
                v.stop()
                if v.ident:
                    v.join()
            for d in executor.destinations:
                d.stop()
                if d.ident:
                    d.join()
    if log.hasQueueLogger():
        queueLogger = log.getQueueLogger()
        queueLogger.terminate()
    sys.exit(code)

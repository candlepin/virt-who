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
from virtwho.executor import Executor, ReloadRequest, ExitRequest
from virtwho.parser import parse_options, OptionError
from virtwho.password import InvalidKeyFile
from virtwho.pid_lock import PIDLock, PIDFILE
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

executor = None


def atexit_fn(*args, **kwargs):
    global executor
    if executor:
        executor.terminate()
    executor = None


def reload(sig, stackframe):
    if executor:
        # Ignore signal SIGHUP during reloading executor
        # See bug: https://bugzilla.redhat.com/show_bug.cgi?id=1506167
        signal.signal(signal.SIGHUP, lambda _sig, _stack: None)
        executor.reload()
        signal.signal(signal.SIGHUP, reload)
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

    if len(effective_config[VW_GLOBAL]['configs']) > 0:
        # When config file is provided using -c or --config, then other config
        # files in /etc/virt-who.d are ignored. When it is not possible to read
        # any configuration file, then virt-who should be terminated
        cli_config_file_readable = False
        for file_name in effective_config[VW_GLOBAL]['configs']:
            if os.path.isfile(file_name):
                cli_config_file_readable = True

        if cli_config_file_readable is False:
            err = 'No valid configuration file provided using -c/--config'
            logger.error(err)
            exit(1, "virt-who can't be started: %s" % str(err))

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
                        'guestIds': [guest.toDict() for guest in report.guests]
                    })
                elif isinstance(report, HostGuestAssociationReport):
                    for hypervisor in report.association['hypervisors']:
                        h = {}
                        h['hypervisorId'] = {'hypervisorId': hypervisor.hypervisorId}
                        if hypervisor.name:
                            h['name'] = hypervisor.name
                        h['guestIds']= [guest.toDict() for guest in hypervisor.guestIds];
                        if hypervisor.facts:
                            h['facts'] = hypervisor.facts
                        hypervisors.append(h)
            print( json.dumps({
                'hypervisors': hypervisors
            }, indent=4, sort_keys=False))
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
        executor.logger.debug(str(status))
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

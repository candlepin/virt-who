"""
Module for abstraction of all virtualization backends, part of virt-who

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
import time
import logging
from operator import itemgetter
from datetime import datetime
from multiprocessing import Process, Event
import json
import hashlib
import signal

try:
    from collections import OrderedDict
except ImportError:
    # Python 2.6 doesn't have OrderedDict, we need to have our own
    from virtwho.util import OrderedDict


class VirtError(Exception):
    pass


class Guest(object):
    """
    This class represents one virtualization guest running on some
    host/hypervisor.
    """

    STATE_UNKNOWN = 0      # unknown state
    STATE_RUNNING = 1      # running
    STATE_BLOCKED = 2      # blocked on resource
    STATE_PAUSED = 3       # paused by user
    STATE_SHUTINGDOWN = 4  # guest is being shut down
    STATE_SHUTOFF = 5      # shut off
    STATE_CRASHED = 6      # crashed
    STATE_PMSUSPENDED = 7  # suspended by guest power management

    def __init__(self,
                 uuid,
                 virt,
                 state,
                 hypervisorType=None):
        """
        Create new guest instance that will be sent to the subscription manager.

        `uuid` is unique identification of the guest.

        `virt` is a `Virt` class instance that represents virtualization hypervisor
        that owns the guest.

        `state` is a number that represents the state of the guest (stopped, running, ...)
        """
        self.uuid = uuid
        self.virtWhoType = virt.CONFIG_TYPE
        self.state = state

    def __repr__(self):
        return 'Guest({0.uuid!r}, {0.virtWhoType!r}, {0.state!r})'.format(self)

    def toDict(self):
        d = OrderedDict((
            ('guestId', self.uuid),
            ('state', self.state),
            ('attributes', {
                'virtWhoType': self.virtWhoType,
                'active': 1 if self.state in (self.STATE_RUNNING, self.STATE_PAUSED) else 0
            }),
        ))
        return d


class Hypervisor(object):
    """
    A model for information about a hypervisor
    """

    CPU_SOCKET_FACT = 'cpu.cpu_socket(s)'
    HYPERVISOR_TYPE_FACT = 'hypervisor.type'
    HYPERVISOR_VERSION_FACT = 'hypervisor.version'

    def __init__(self, hypervisorId, guestIds=None, name=None, facts=None):
        """
        Create a new Hypervisor that will be sent to subscription manager

        'hypervisorId': the unique identifier for this hypervisor

        'guestIds': a list of Guests

        'name': the hostname, if available
        """
        self.hypervisorId = hypervisorId
        self.guestIds = guestIds or []
        self.name = name
        self.facts = facts

    def __repr__(self):
        return 'Hypervisor({0.hypervisorId!r}, {0.guestIds!r}, {0.name!r}, {0.facts!r})'.format(self)

    def toDict(self):
        d = OrderedDict((
            ('hypervisorId', {'hypervisorId': self.hypervisorId}),
            ('name', self.name),
            ('guestIds', sorted([g.toDict() for g in self.guestIds], key=itemgetter('guestId')))
        ))
        if self.name is None:
            del d['name']
        if self.facts is not None:
            d['facts'] = self.facts
        return d

    def __str__(self):
        return str(self.toDict())

    def getHash(self):
        sortedRepresentation = json.dumps(self.toDict(), sort_keys=True)
        return hashlib.sha256(sortedRepresentation).hexdigest()


class AbstractVirtReport(object):
    '''
    An abstract report from virt backend.
    '''
    # The report was just collected, but is not yet being reported
    STATE_CREATED = 1
    # The report is being processed by server
    STATE_PROCESSING = 2
    # The report has been processed by server
    STATE_FINISHED = 3
    # Failed to process the report by server
    STATE_FAILED = 4
    # Processing the report on server was canceled
    STATE_CANCELED = 5

    def __init__(self, config, state=STATE_CREATED):
        self._config = config
        self._state = state

    def __repr__(self):
        return '{1}({0.config!r}, {0.state!r})'.format(self, self.__class__.__name__)

    @property
    def config(self):
        return self._config

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value


class ErrorReport(AbstractVirtReport):
    '''
    Report that virt backend fails. Used in oneshot mode to inform
    main process that no data are coming.
    '''


class DomainListReport(AbstractVirtReport):
    '''
    Report from virt backend about list of virtual guests on given system.
    '''
    def __init__(self, config, guests, hypervisor_id=None, state=AbstractVirtReport.STATE_CREATED):
        super(DomainListReport, self).__init__(config, state)
        self._guests = guests
        self._hypervisor_id = hypervisor_id

    def __repr__(self):
        return 'DomainListReport({0.config!r}, {0.guests!r}, {0.hypervisor_id!r}, {0.state!r})'.format(self)

    @property
    def guests(self):
        return self._guests

    @property
    def hypervisor_id(self):
        return self._hypervisor_id

    @property
    def hash(self):
        return hashlib.sha256(
            json.dumps(
                sorted([g.toDict() for g in self.guests], key=itemgetter('guestId')),
                sort_keys=True) +
            str(self.hypervisor_id)
        ).hexdigest()


class HostGuestAssociationReport(AbstractVirtReport):
    '''
    Report from virt backend about host/guest association on given hypervisor.
    '''
    def __init__(self, config, assoc, state=AbstractVirtReport.STATE_CREATED):
        super(HostGuestAssociationReport, self).__init__(config, state)
        self._assoc = assoc

    def __repr__(self):
        return 'HostGuestAssociationReport({0.config!r}, {0._assoc!r}, {0.state!r})'.format(self)

    @property
    def association(self):
        # Apply filter
        logger = logging.getLogger("virtwho")
        assoc = []
        for host in self._assoc['hypervisors']:
            if self._config.exclude_hosts is not None and host.hypervisorId in self._config.exclude_hosts:
                logger.debug("Skipping host '%s' because its uuid is excluded", host.hypervisorId)
                continue

            if self._config.filter_hosts is not None and host.hypervisorId not in self._config.filter_hosts:
                logger.debug("Skipping host '%s' because its uuid is not included", host.hypervisorId)
                continue
            assoc.append(host)
        return {'hypervisors': assoc}

    @property
    def serializedAssociation(self):
        return {
            'hypervisors': sorted([h.toDict() for h in self.association['hypervisors']], key=itemgetter('hypervisorId'))
        }

    @property
    def hash(self):
        return hashlib.sha256(json.dumps(self.serializedAssociation, sort_keys=True)).hexdigest()


class Virt(Process):
    '''
    Virtualization backend abstract class.

    This class must be inherited for each of the virtualization backends.

    Run `start` method to start obtaining data about virtual guests. The data
    will be pushed to the `queue` that is parameter of the `start` method.

    Note that this class is a subclass of `multiprocessing.Process` class.
    '''
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self._internal_terminate_event = Event()
        super(Virt, self).__init__()
        self.daemon = True

    def __repr__(self):
        return '{1}({0.logger!r}, {0.config!r})'.format(self, self.__class__.__name__)

    @classmethod
    def fromConfig(cls, logger, config):
        """
        Create instance of inherited class based on the config.
        """

        # Imports can't be top-level, it would be circular dependency
        import virtwho.virt.libvirtd  # flake8: noqa
        import virtwho.virt.esx  # flake8: noqa
        import virtwho.virt.xen  # flake8: noqa
        import virtwho.virt.rhevm  # flake8: noqa
        import virtwho.virt.vdsm  # flake8: noqa
        import virtwho.virt.hyperv  # flake8: noqa
        import virtwho.virt.fakevirt  # flake8: noqa

        for subcls in cls.__subclasses__():
            if config.type == subcls.CONFIG_TYPE:
                return subcls(logger, config)
        raise KeyError("Invalid config type: %s" % config.type)

    def start(self, queue, terminate_event, interval=None, oneshot=False):  # pylint: disable=W0221
        '''
        Start obtaining data from the hypervisor/host system. The data will
        be fetched (as instances of AbstractVirtReport subclasses) to the
        `queue` parameter (which should be instance of `Queue.Queue` object.

        `terminate_event` is `multiprocessing.Event` instance and will be set when
        the process should be terminated.

        `interval` parameter determines maximal interval, how ofter should
        the data be reported. If the virt backend supports events, it might
        be less often.

        If `oneshot` parameter is True, the data will be reported only once
        and the process will be terminated after that.
        '''
        self._queue = queue
        self._terminate_event = terminate_event
        if interval is not None:
            self._interval = interval
        else:
            # TODO: get this value from somewhere
            self._interval = 3600
        self._oneshot = oneshot
        super(Virt, self).start()

    def start_sync(self, queue, terminate_event, interval=None, oneshot=False):
        '''
        This method is same as `start()` but runs synchronously, it does NOT
        create new process.

        Use it only in specific cases!
        '''
        self._queue = queue
        self._terminate_event = terminate_event
        if interval is not None:
            self._interval = interval
        else:
            # TODO: get this value from somewhere
            self._interval = 3600
        self._oneshot = oneshot
        self._run()

    def _get_report(self):
        if self.isHypervisor():
            return HostGuestAssociationReport(self.config, self.getHostGuestMapping())
        else:
            return DomainListReport(self.config, self.listDomains())

    def wait(self, wait_time):
        '''
        Wait `wait_time` seconds, could be interrupted by setting _terminate_event or _internal_terminate_event.
        '''
        for i in range(wait_time):
            if self.is_terminated():
                break
            time.sleep(1)

    def stop(self):
        self._internal_terminate_event.set()

    def is_terminated(self):
        return self._internal_terminate_event.is_set() or self._terminate_event.is_set()

    def enqueue(self, report):
        if self.is_terminated():
            sys.exit(0)
        self.logger.debug('Report for config "%s" gathered, putting to queue for sending', report.config.name)
        self._queue.put(report)

    def run(self):
        '''
        Wrapper around `_run` method that just catches the error messages.
        '''
        self.logger.debug("Virt backend '%s' started", self.config.name)
        # Reset the signal handlers, we'll handle them only in the main thread
        signal.signal(signal.SIGHUP, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, lambda *a: self.cleanup())
        try:
            while not self.is_terminated():
                has_error = False
                try:
                    self._run()
                except VirtError as e:
                    if not self.is_terminated():
                        self.logger.error("Virt backend '%s' fails with error: %s", self.config.name, str(e))
                        has_error = True
                except Exception:
                    if not self.is_terminated():
                        self.logger.exception("Virt backend '%s' fails with exception:", self.config.name)
                        has_error = True

                if self._oneshot:
                    if has_error:
                        self.enqueue(ErrorReport(self.config))
                    self.logger.debug("Virt backend '%s' stopped after sending one report", self.config.name)
                    return

                if self.is_terminated():
                    self.logger.debug("Virt backend '%s' terminated", self.config.name)
                    return

                self.logger.info("Waiting %s seconds before retrying backend '%s'", self._interval, self.config.name)
                self.wait(self._interval)
        except KeyboardInterrupt:
            self.logger.debug("Virt backend '%s' interrupted", self.config.name)
            self.cleanup()
            sys.exit(1)

    def _run(self):
        '''
        Run the endless loop that will fill the `_queue` with reports.

        This method could be reimplemented in subclass to provide
        it's own way of waiting for changes (like event monitoring)
        '''
        self.prepare()
        while not self.is_terminated():
            start_time = datetime.now()
            report = self._get_report()
            self.enqueue(report)
            if self._oneshot:
                break
            end_time = datetime.now()

            delta = end_time - start_time
            # for python2.6, 2.7 has total_seconds method
            delta_seconds = ((delta.days * 86400 + delta.seconds) * 10**6 + delta.microseconds) / 10**6

            wait_time = self._interval - int(delta_seconds)

            if wait_time < 0:
                self.logger.debug("Getting the host/guests association took too long, interval waiting is skipped")
                continue

            self.wait(wait_time)

    def prepare(self):
        '''
        Do pre-mainloop initialization of the backend, for example logging in.
        '''
        pass

    def isHypervisor(self):
        """
        Return True if the virt instance represents hypervisor environment
        otherwise it represents just one virtual server.
        """
        return True

    def getHostGuestMapping(self):
        '''
        If subclass doesn't reimplement the `_run` method, it should
        reimplement either this method or `listDomains` method, based on
        return value of isHypervisor method.
        '''
        raise NotImplementedError('This should be reimplemented in subclass')

    def listDomains(self):
        '''
        If subclass doesn't reimplement the `_run` method, it should
        reimplement either this method or `getHostGuestMapping` method, based on
        return value of isHypervisor method.
        '''
        raise NotImplementedError('This should be reimplemented in subclass')

    def cleanup(self):
        '''
        Perform cleaning up actions before termination.
        '''
        pass

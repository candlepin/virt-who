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
import log
from datetime import datetime
from multiprocessing import Process, Event
import json
import hashlib

try:
    from collections import OrderedDict
except ImportError:
    # Python 2.6 doesn't have OrderedDict, we need to have our own
    from util import OrderedDict


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

    def __init__(self, uuid, virt, state, hypervisorType=None):
        """
        Create new guest instance that will be sent to the subscription manager.

        `uuid` is unique identification of the guest.

        `virt` is a `Virt` class instance that represents virtualization hypervisor
        that owns the guest.

        `hypervisorType` is additional type of the virtualization, used in libvirt.

        `state` is a number that represents the state of the guest (stopped, running, ...)
        """
        self.uuid = uuid
        self.virtWhoType = virt.CONFIG_TYPE
        self.hypervisorType = hypervisorType
        self.state = state

    def toDict(self):
        d = OrderedDict((
            ('guestId', self.uuid),
            ('state', self.state),
            ('attributes', {
                'virtWhoType': self.virtWhoType,
                'active': 1 if self.state == self.STATE_RUNNING else 0
            }),
        ))

        if self.hypervisorType is not None:
            d['attributes']['hypervisorType'] = self.hypervisorType
        return d


class Hypervisor(object):
    """
    A model for information about a hypervisor
    """
    def __init__(self, hypervisorId,  guestIds=None, name=None, facts=None):
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


    def toDict(self):
        d = OrderedDict((
            ('hypervisorId', {'hypervisorId': self.hypervisorId}),
            ('name', self.name),
            ('guestIds', [g.toDict() for g in self.guestIds])
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
        return hashlib.md5(sortedRepresentation).hexdigest()


class AbstractVirtReport(object):
    '''
    An abstract report from virt backend.
    '''
    def __init__(self, config):
        self._config = config

    @property
    def config(self):
        return self._config


class ErrorReport(AbstractVirtReport):
    '''
    Report that virt backend fails. Used in oneshot mode to inform
    main process that now data are coming.
    '''


class DomainListReport(AbstractVirtReport):
    '''
    Report from virt backend about list of virtual guests on given system.
    '''
    def __init__(self, config, guests):
        super(DomainListReport, self).__init__(config)
        self._guests = guests

    @property
    def guests(self):
        return self._guests

    @property
    def hash(self):
        return hashlib.md5(json.dumps([g.toDict() for g in self.guests], sort_keys=True)).hexdigest()


class HostGuestAssociationReport(AbstractVirtReport):
    '''
    Report from virt backend about host/guest association on given hypervisor.
    '''
    def __init__(self, config, assoc):
        super(HostGuestAssociationReport, self).__init__(config)
        self._assoc = assoc

    @property
    def association(self):
        # Apply filter
        logger = logging.getLogger("virtwho")
        assoc = []
        for host in self._assoc['hypervisors']:
            if self._config.exclude_host_uuids is not None and host.hypervisorId in self._config.exclude_host_uuids:
                logger.debug("Skipping host '%s' because its uuid is excluded" % host.hypervisorId)
                continue

            if self._config.filter_host_uuids is not None and host.hypervisorId not in self._config.filter_host_uuids:
                logger.debug("Skipping host '%s' because its uuid is not included" % host.hypervisorId)
                continue
            assoc.append(host)
        return {'hypervisors': assoc}

    @property
    def serializedAssociation(self):
        return {'hypervisors': [h.toDict() for h in self.association['hypervisors']]}

    @property
    def hash(self):
        return hashlib.md5(json.dumps(self.serializedAssociation, sort_keys=True)).hexdigest()


class HypervisorInfoReport(AbstractVirtReport):
    '''
    Report from virt backend with info about the hypervisor itself.
    '''
    def __init__(self, config, info):
        super(HypervisorInfoReport, self).__init__(config)
        self._info = info

    @property
    def info(self):
        return self._info


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
        #super(Virt, self).__init__(name=config.name)
        super(Virt, self).__init__()
        self.daemon = True

    @classmethod
    def fromConfig(cls, logger, config):
        """
        Create instance of inherited class based on the config.
        """

        # Imports can't be top-level, it would be circular dependency
        import libvirtd
        import esx
        import rhevm
        import vdsm
        import hyperv
        import fakevirt

        for subcls in cls.__subclasses__():
            if config.type == subcls.CONFIG_TYPE:
                return subcls(logger, config)
        raise KeyError("Invalid config type: %s" % config.type)

    def start(self, queue, terminate_event, interval=None, oneshot=False):  # pylint: disable=W0221
        '''
        Start obtaining data from the hypervisor/host system. The data will
        be fetched (as instances of AbstracVirtReport subclasses) to the
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

    def run(self):
        '''
        Wrapper around `_run` method that just catches the error messages.
        '''
        try:
            while not self.is_terminated():
                try:
                    self._run()
                except VirtError as e:
                    self.logger.error("Virt backend '%s' fails with error: %s" % (self.config.name, str(e)))
                except Exception:
                    self.logger.exception("Virt backend '%s' fails with exception:" % self.config.name)

                if self._oneshot:
                    self._queue.put(ErrorReport(self.config))
                    return

                if self.is_terminated():
                    return

                self.logger.info("Waiting %s seconds before retrying backend '%s'", self._interval, self.config.name)
                self.wait(self._interval)
        except KeyboardInterrupt:
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
            self._queue.put(report)
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

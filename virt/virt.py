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
from datetime import datetime
from multiprocessing import Process

class VirtError(Exception):
    pass


class Domain(dict):
    def __init__(self, virt, domain):
        self['guestId'] = domain.UUIDString()
        self['attributes'] = {
            'hypervisorType': virt.getType(),
            'virtWhoType': "libvirt",
            'active': 0
        }
        if domain.isActive():
            self['attributes']['active'] = 1
        try:
            self['state'] = domain.state(0)[0]
        except AttributeError:
            # Some versions of libvirt doesn't have domain.state() method,
            # use first value from info instead
            self['state'] = domain.info()[0]

class AbstractVirtReport(object):
    '''
    An abstract report from virt backend.
    '''
    def __init__(self, config):
        self._config = config

    @property
    def config(self):
        return self._config

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
        assoc = {}
        logger = logging.getLogger("rhsm-app")
        for host, guests in self._assoc.items():
            if host in self._config.exclude_host_uuids:
                logger.debug("Skipping host '%s' because its uuid is excluded" % host)
                continue
            if len(self._config.filter_host_uuids) > 0 and host not in self._config.filter_host_uuids:
                logger.debug("Skipping host '%s' because its uuid is not included" % host)
                continue
            assoc[host] = guests
        return assoc

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
        super(Virt, self).__init__()

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

    def start(self, queue, terminate_event, interval=None, oneshot=False): # pylint: disable=W0221
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
        and the process will be terminated after that. `interval` and
        `terminate_event` parameters won't be used in that case.
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
        Wait `wait_time` seconds, could be interrupted by setting _terminate_event.
        '''
        for i in range(wait_time):
            if self._terminate_event.is_set():
                break
            time.sleep(1)

    def run(self):
        '''
        Wrapper around `_run` method that just catches the error messages.
        '''
        try:
            while self._oneshot or not self._terminate_event.is_set():
                try:
                    self._run()
                except VirtError as e:
                    self.logger.error("Virt backend '%s' fails with error: %s" % (self.config.name, str(e)))
                except Exception:
                    self.logger.exception("Virt backend '%s' fails with exception:" % self.config.name)

                if self._oneshot:
                    self._queue.put(None)
                    return

                if self._terminate_event.is_set():
                    return

                self.logger.info("Waiting %s seconds before retrying backend '%s'" % (self._interval, self.config.name))
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
        while self._oneshot or not self._terminate_event.is_set():
            start_time = datetime.now()
            report = self._get_report()
            self._queue.put(report)
            end_time = datetime.now()

            delta = end_time - start_time
            # for python2.6, 2.7 has total_seconds method
            delta_seconds = ((delta.days * 86400 + delta.seconds) * 10**6 + delta.microseconds) / 10**6

            wait_time = self._interval - int(delta_seconds)

            if wait_time <= 0:
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

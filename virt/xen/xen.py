#!/usr/bin/env python

import sys
from time import time
import XenAPI
from XenAPI import NewMaster
from collections import defaultdict
import virt


class Xen(virt.Virt):
    CONFIG_TYPE = "xen"
    # if no events occur the call to event_from will return after this interval
    # if events do occur the call will return sooner
    EVENT_FROM_TIMEOUT = 30.0

    # if the token parameter is set to an empty string, the return from event_from will contain all
    # events that have occurred, you probably want to use this the first time you use event_from
    token_from = ''

    # Register for events on all classes
    event_types = ["*"]

    def __init__(self, logger, config):
        super(Xen, self).__init__(logger, config)
        self.url = config.server
        self.username = config.username
        self.password = config.password
        self.config = config

        # Url must contain protocol (usualy https://)
        if "://" not in self.url:
            self.url = "https://%s" % self.url

        self.filter = None

    def _prepare(self):
        """ Prepare for obtaining information from Xen server. """
        self.logger.debug("Log into XEN pools %s" % self.url)
        self.login()

    def login(self):
        # Login to server using given credentials
        try:
            # Don't log message containing password
            self.session = XenAPI.Session(self.url)
            self.session.xenapi.login_with_password(self.username, self.password)
            self.logger.debug("I'm in XEN pools! with user %s" % self.username)

        except NewMaster as nm:
            self.logger.debug("Do I have a new master?")
            try:
                self.session = XenAPI.Session('http://%s' % nm.new_master())
                self.session.xenapi.login_with_password(self.username, self.password)
                self.logger.debug("I'm in XEN pools with new master %s! with user %s" % (nm.new_master(), self.username))

            except Exception:
                self.logger.exception("Unable to login to XENserver %s" % self.url)
                raise

        except Exception:
            self.logger.exception("Unable to login to XENserver %s" % self.url)
            raise

    def getHostGuestMapping(self):
        hosts = self.session.xenapi.host.get_all()

        mapping = {}

        for host in hosts:

            record = self.session.xenapi.host.get_record(host)
            guests = []

            for resident in self.session.xenapi.host.get_resident_VMs(host):
                vm = self.session.xenapi.VM.get_record(resident)

                if vm.get('is_control_domain', False):
                    self.logger.debug("Control Domain %s is ignored", vm['uuid'])
                    continue

                if vm.get('is_a_snapshot', False) or vm.get('is_a_template', False):
                    self.logger.debug("Guest %s is snapshot or template, ignoring", vm['uuid'])
                    continue

                if vm['power_state'] == 'Running':
                    state = virt.Guest.STATE_RUNNING
                elif vm['power_state'] == 'Suspended':
                    state = virt.Guest.STATE_PAUSED
                elif vm['power_state'] == 'Paused':
                    state = virt.Guest.STATE_PAUSED
                elif vm['power_state'] == 'Halted':
                    state = virt.Guest.STATE_SHUTOFF
                else:
                    state = virt.Guest.STATE_UNKNOWN

                guests.append(
                    virt.Guest(
                        uuid=vm["uuid"],
                        virt=self,
                        state=state,
                        hypervisorType=None
                    )
                )

            mapping['hypervisors'] = Hypervisor(hypervisorId=record["uuid"],
                                                guestIds=guests,
                                                name=record["hostname"],
                                                facts=None)
        return mapping

    def _run(self):
        self._prepare()

        self.hosts = defaultdict(Host)
        self.vms = defaultdict(VM)
        start_time = end_time = time()
        initial = True

        while self._oneshot or not self.is_terminated():
            delta = end_time - start_time
            try:
                event_from_ret = self.session.xenapi.event_from(
                    self.event_types,
                    self.token_from,
                    self.EVENT_FROM_TIMEOUT)
                events = event_from_ret['events']
            except:
                events = []

            if initial:
                # We want to read the update asap
                max_wait_seconds = 0
            else:
                if delta - self._interval > 2.0:
                    # The update took longer than it should, don't wait so long next time
                    max_wait_seconds = max(self._interval - int(delta - self._interval), 0)
                    self.logger.debug(
                        "Getting the host/guests association took too long,"
                        "interval waiting is shortened to %s", max_wait_seconds)
                else:
                    max_wait_seconds = self._interval

            start_time = time()

            if len(events) > 0:
                assoc = self.getHostGuestMapping()
                self._queue.put(virt.HostGuestAssociationReport(self.config, assoc))

                event_from_ret = self.session.xenapi.event_from(self.event_types,
                                                                self.token_from,
                                                                self.EVENT_FROM_TIMEOUT)
                events = event_from_ret['events']
                initial = False

            end_time = time()

            if self._oneshot:
                break

            self.logger.debug("Waiting for XEN changes")


if __name__ == "__main__":  # pragma: no cover
    # First acquire a valid session by logging in:
    from config import Config
    config = Config('xen', 'xen', url, username, password)
    xenserver = Xen(logger, config)
    from Queue import Queue
    from threading import Event, Thread
    q = Queue()

    class Printer(Thread):
        def run(self):
            while True:
                print q.get(True).association
    p = Printer()
    p.daemon = True
    p.start()
    try:
        xenserver.start_sync(q, Event())
    except KeyboardInterrupt:
        sys.exit(1)

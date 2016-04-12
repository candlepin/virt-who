#!/usr/bin/env python

import sys
from time import time
import XenAPI
from XenAPI import NewMaster, Failure
from collections import defaultdict
import virt
import logging


class Xen(virt.Virt):
    CONFIG_TYPE = "xen"
    # if no events occur the call to event_from will return after this interval
    # if events do occur the call will return sooner
    EVENT_FROM_TIMEOUT = 30.0

    # if the token parameter is set to an empty string, the return from event_from will contain all
    # events that have occurred, you probably want to use this the first time you use event_from
    token_from = ''

    # Register for events on all classes
    event_types = ["host", "vm"]

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
        self.logger.debug("Logging into XEN pools %s" % self.url)
        self.login()

    def login(self, url=None):
        """ Login to server using given credentials. """
        url = url or self.url
        try:
            # Don't log message containing password
            self.session = XenAPI.Session(url)
            self.session.xenapi.login_with_password(self.username, self.password)
            self.logger.debug("XEN pool login successful with user %s" % self.username)
        except NewMaster as nm:
            url = nm.new_master()
            if "://" not in url:
                url = '%s://%s' % (self.url.partition(":")[0], url)
            self.logger.debug("Switching to new master: %s", url)
            return self.login(url)
        except Exception as e:
            self.logger.exception("Unable to login to XENserver %s" % self.url)
            raise virt.VirtError(str(e))

    def getHostGuestMapping(self):
        assert hasattr(self, 'session'), "Login was not called"
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

            facts = {}
            sockets = record.get('cpu_info', {}).get('socket_count', None)
            if sockets is not None:
                facts['cpu.cpu_socket(s)'] = sockets

            mapping['hypervisors'] = [
                virt.Hypervisor(
                    hypervisorId=record["uuid"],
                    guestIds=guests,
                    name=record["hostname"],
                    facts=facts)
            ]
        return mapping

    def _wait(self, token, timeout):
        try:
            return self.session.xenapi.event_from(
                self.event_types,
                token,
                float(timeout))
        except Failure as e:
            if 'timeout' not in e.details:
                self.logger.exception("Waiting on XEN events failed: ")
        except Exception:
            self.logger.exception("Waiting on XEN events failed: ")
        return None

    def _run(self):
        self._prepare()

        self.hosts = defaultdict(virt.Hypervisor)
        self.vms = defaultdict(virt.Guest)
        next_update = time()
        initial = True
        token = ''

        while self._oneshot or not self.is_terminated():
            delta = next_update - time()
            if initial or delta > 0:
                # Wait for update
                wait_result = self._wait(token, 60 if initial else delta)
                if wait_result:
                    events = wait_result['events']
                    token = wait_result['token']
                else:
                    events = []
                    token = ''
            else:
                events = []

            if initial or len(events) > 0 or delta > 0:
                assoc = self.getHostGuestMapping()
                self.enqueue(virt.HostGuestAssociationReport(self.config, assoc))
                next_update = time() + self._interval
                initial = False

            if self._oneshot:
                break

        self.cleanup()


if __name__ == "__main__":  # pragma: no cover
    # First acquire a valid session by logging in:
    from config import Config
    if len(sys.argv) < 4:
        print("Usage: %s url username password" % sys.argv[0])
        sys.exit(0)
    logger = logging.getLogger('virtwho.xen')
    logger.addHandler(logging.StreamHandler())
    url, username, password = sys.argv[1:4]
    config = Config('xen', 'xen', server=url, username=username, password=password)
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

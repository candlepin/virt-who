#!/usr/bin/env python

import sys
from time import time
import XenAPI
from XenAPI import NewMaster, Failure
from collections import defaultdict
import logging
import requests

from virtwho import virt
from virtwho.util import RequestsXmlrpcTransport


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

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(Xen, self).__init__(logger, config, dest,
                                  terminate_event=terminate_event,
                                  interval=interval,
                                  oneshot=oneshot)
        self.url = config.server
        self.username = config.username
        self.password = config.password
        self.config = config
        self.ignored_guests = set()

        # Url must contain protocol (usually https://)
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
            self.session = XenAPI.Session(url, transport=RequestsXmlrpcTransport(url))
            self.session.xenapi.login_with_password(self.username, self.password)
            self.logger.debug("XEN pool login successful with user %s" % self.username)
        except NewMaster as nm:
            url = nm.new_master()
            if "://" not in url:
                url = '%s://%s' % (self.url.partition(":")[0], url)
            self.logger.debug("Switching to new master: %s", url)
            return self.login(url)
        except requests.ConnectionError as e:
            raise virt.VirtError(str(e))
        except Exception as e:
            self.logger.exception("Unable to login to XENserver %s" % self.url)
            raise virt.VirtError(str(e))

    def getHostGuestMapping(self):
        assert hasattr(self, 'session'), "Login was not called"
        hosts = self.session.xenapi.host.get_all()

        mapping = {
            'hypervisors': [],
        }

        for host in hosts:

            record = self.session.xenapi.host.get_record(host)
            guests = []

            for resident in self.session.xenapi.host.get_resident_VMs(host):
                vm = self.session.xenapi.VM.get_record(resident)
                uuid = vm['uuid']

                if vm.get('is_control_domain', False):
                    if uuid not in self.ignored_guests:
                        self.ignored_guests.add(uuid)
                        self.logger.debug("Control Domain %s is ignored", uuid)
                    continue

                if vm.get('is_a_snapshot', False) or vm.get('is_a_template', False):
                    if uuid not in self.ignored_guests:
                        self.ignored_guests.add(uuid)
                        self.logger.debug("Guest %s is snapshot or template, ignoring", uuid)
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

                guests.append(virt.Guest(uuid=uuid, virt=self, state=state))

            facts = {}
            sockets = record.get('cpu_info', {}).get('socket_count')
            if sockets is not None:
                facts[virt.Hypervisor.CPU_SOCKET_FACT] = str(sockets)
            brand = record.get('software_version', {}).get('product_brand')
            if brand:
                facts[virt.Hypervisor.HYPERVISOR_TYPE_FACT] = brand
            version = record.get('software_version', {}).get('product_version')
            if version:
                facts[virt.Hypervisor.HYPERVISOR_VERSION_FACT] = version

            if self.config.hypervisor_id == 'uuid':
                uuid = record["uuid"]
            elif self.config.hypervisor_id == 'hostname':
                uuid = record["hostname"]
            else:
                raise virt.VirtError(
                    'Invalid option %s for hypervisor_id, use one of: uuid or hostname' %
                    self.config.hypervisor_id)

            mapping['hypervisors'].append(
                virt.Hypervisor(
                    hypervisorId=uuid,
                    guestIds=guests,
                    name=record["hostname"],
                    facts=facts))
        return mapping

    def _wait(self, token, timeout):
        try:
            # Do an active waiting because current thread might get terminated
            end_time = time() + timeout
            while time() < end_time and not self.is_terminated():
                try:
                    response = self.session.xenapi.event_from(
                        self.event_types,
                        token,
                        1.0)
                    token = response['token']
                    if len(response['events']) == 0:
                        # No events, continue to wait
                        continue
                    return response
                except Failure as e:
                    if 'timeout' not in e.details:
                        raise
        except Exception:
            self.logger.exception("Waiting on XEN events failed: ")
        return {
            'events': [],
            'token': token
        }

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
                self._send_data(virt.HostGuestAssociationReport(self.config, assoc))
                next_update = time() + self.interval
                initial = False

            if self._oneshot:
                break

        self.cleanup()


if __name__ == "__main__":  # pragma: no cover
    # First acquire a valid session by logging in:
    from virtwho.config import Config
    if len(sys.argv) < 4:
        print("Usage: %s url username password" % sys.argv[0])
        sys.exit(0)
    logger = logging.getLogger('virtwho.xen')
    logger.addHandler(logging.StreamHandler())
    url, username, password = sys.argv[1:4]
    config = Config('xen', 'xen', server=url, username=username, password=password)
    from virtwho.datastore import Datastore
    from threading import Event, Thread
    printer_terminate_event = Event()
    datastore = Datastore()

    xenserver = Xen(logger, config, datastore)

    class Printer(Thread):
        def run(self):
            last_hash = None
            while not printer_terminate_event.is_set():
                try:
                    report = datastore.get(config.name)
                    if report and report.hash != last_hash:
                        print report.association
                        last_hash = report.hash
                except KeyError:
                    pass
    p = Printer()
    p.daemon = True
    p.start()
    try:
        xenserver.start_sync()
    except KeyboardInterrupt:
        printer_terminate_event.set()
        p.join()
        sys.exit(1)

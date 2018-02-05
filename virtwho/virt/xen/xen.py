#!/usr/bin/env python
# # -*- coding: utf-8 -*-
from __future__ import print_function


#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

from __future__ import absolute_import
from time import time
from . import XenAPI
from .XenAPI import NewMaster, Failure
from collections import defaultdict
import requests

from virtwho import virt
from virtwho.util import RequestsXmlrpcTransport
from virtwho.config import VirtConfigSection


class XenConfigSection(VirtConfigSection):
    """
    This class is used for validation of Xen virtualization backend
    section(s). It tries to validate options and combination of options that
    are specific for this virtualization backend.
    """
    VIRT_TYPE = 'xen'
    HYPERVISOR_ID = ('uuid', 'hostname')

    def __init__(self, section_name, wrapper, *args, **kwargs):
        super(XenConfigSection, self).__init__(section_name, wrapper, *args, **kwargs)
        self.add_key('server', validation_method=self._validate_server, required=True)
        self.add_key('username', validation_method=self._validate_username, required=True)
        self.add_key('password', validation_method=self._validate_unencrypted_password, required=True)

    def _validate_server(self, key):
        """
        Do validation of server option specific for this virtualization backend
        return: None or info-warning/error
        """

        result = []

        # Url must contain protocol (usually https://)
        url = self._values[key]
        if "://" not in url:
            url = "https://%s" % url
            result.append((
                'info',
                "The original server URL was incomplete. It has been enhanced to %s" % url
            ))
            self._values[key] = url

        if len(result) > 0:
            return result
        else:
            return None


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
        self.session = None
        self.url = config['server']
        self.username = config['username']
        self.password = config['password']
        self.config = config
        self.ignored_guests = set()
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

                guests.append(virt.Guest(uuid=uuid, virt_type=self.CONFIG_TYPE, state=state))

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

            if self.config['hypervisor_id'] == 'uuid':
                uuid = record["uuid"]
            elif self.config['hypervisor_id'] == 'hostname':
                uuid = record["hostname"]

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
                initial = False

            if self._oneshot:
                break
            else:
                next_update = time() + self.interval

        self.cleanup()

# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for communication with vCenter/ESX, part of virt-who

Copyright (C) 2012 Radek Novacek <rnovacek@redhat.com>

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

import os
import suds
import suds.transport
import suds.client
import requests
import errno
import stat
from six import BytesIO
import io
import logging
from time import time
from six.moves.urllib.error import URLError
import socket
from collections import defaultdict
from six.moves.http_client import HTTPException

from virtwho import virt
from virtwho.config import VirtConfigSection


class FileAdapter(requests.adapters.BaseAdapter):
    '''Add handler from downloading local files.

    This is necessary because we want suds to use local wsdl file.
    '''
    def send(self, request, **kwargs):
        resp = requests.Response()

        filename = request.url.replace('file://', '')
        if not os.path.isabs(filename):
            raise ValueError("Expected absolute path: %s" % request.url)

        try:
            resp.raw = io.open(filename, "rb")
            resp.raw.release_conn = resp.raw.close
        except IOError as e:
            if e.errno == errno.EACCES:
                resp.status_code = requests.codes.forbidden
            elif e.errno == errno.ENOENT:
                resp.status_code = requests.codes.not_found
            else:
                resp.status_code = requests.codes.bad_request
        else:
            resp_stat = os.fstat(resp.raw.fileno())
            if stat.S_ISREG(resp_stat.st_mode):
                resp.headers['Content-Length'] = resp_stat.st_size
            resp.status_code = requests.codes.ok
        return resp

    def close(self):
        pass


class RequestsTransport(suds.transport.Transport):
    '''
    Transport for suds that uses Requests instead of urllib2.

    This unifies network handling with other backends. For example
    proxy support will be same as for other modules.
    '''
    def __init__(self, session=None):
        suds.transport.Transport.__init__(self)
        self._session = session or requests.Session()
        self._session.mount('file://', FileAdapter())

    def open(self, request):
        resp = self._session.get(request.url, headers=request.headers, verify=False)
        resp.raise_for_status()
        return BytesIO(resp.content)

    def send(self, request):
        resp = self._session.post(
            request.url,
            data=request.message,
            headers=request.headers,
            timeout=self.options.timeout,
            verify=False
        )
        ct = resp.headers.get('content-type')
        if 'application/soap+xml' not in ct and 'text/xml' not in ct:
            resp.raise_for_status()
        return suds.transport.Reply(
            resp.status_code,
            resp.headers,
            resp.content,
        )


class Esx(virt.Virt):
    CONFIG_TYPE = "esx"
    MAX_WAIT_TIME = 300  # 5 minutes

    def __init__(self, logger, config, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(Esx, self).__init__(logger, config, dest,
                                  terminate_event=terminate_event,
                                  interval=interval,
                                  oneshot=oneshot)
        self.url = self.config['server']
        self.username = self.config['username']
        self.password = self.config['password']

        self.filter = None
        self.sc = None

    def _prepare(self):
        """ Prepare for obtaining information from ESX server. """
        self.logger.debug("Log into ESX")
        self.login()

        self.logger.debug("Creating ESX event filter")
        self.filter = self.createFilter()

    def _cancel_wait(self):
        try:
            self.client.service.CancelWaitForUpdates(_this=self.sc.propertyCollector)
        except Exception:
            pass

    def _run(self):
        self._prepare()

        version = ''
        last_version = 'last_version'  # Bogus value so version != last_version from the start
        self.hosts = defaultdict(Host)
        self.vms = defaultdict(VM)
        self.clusters = defaultdict(Cluster)
        initial = True
        next_update = time()

        while self._oneshot or not self.is_terminated():

            delta = next_update - time()
            if initial or delta < 0:
                # We want to read the update asap
                options = {}
                timeout = 60
            else:
                max_wait_seconds = int(delta)
                options = {'maxWaitSeconds': max_wait_seconds}
                timeout = max_wait_seconds + 5

            if version == '':
                # also, clean all data we have
                self.hosts.clear()
                self.vms.clear()

            try:
                # Make sure that WaitForUpdatesEx finishes even
                # if the ESX shuts down in the middle of waiting
                self.client.set_options(timeout=timeout)

                updateSet = self.client.service.WaitForUpdatesEx(
                    _this=self.sc.propertyCollector,
                    version=version,
                    options=options)
                initial = False
            except (socket.error, URLError, requests.exceptions.Timeout):
                self.logger.debug("Wait for ESX event finished, timeout")
                self._cancel_wait()
                # Get the initial update again
                version = ''
                initial = True
                continue
            except (suds.WebFault, HTTPException) as e:
                suppress_exception = False
                try:
                    if hasattr(e, 'fault'):
                        if e.fault.faultstring == 'The session is not authenticated.':
                            # Do not print the exception if we get 'not authenticated',
                            # it's quite normal behaviour and nothing to worry about
                            suppress_exception = True
                        if e.fault.faultstring == 'The task was canceled by a user.':
                            # Do not print the exception if we get 'canceled by user',
                            # this happens when the wait is terminated when
                            # virt-who is being stopped
                            continue
                except Exception:
                    pass
                if not suppress_exception:
                    self.logger.exception("Waiting for ESX events fails:")
                self._cancel_wait()
                version = ''
                self._prepare()
                continue

            if updateSet is not None:
                version = updateSet.version
                self.applyUpdates(updateSet)

            if hasattr(updateSet, 'truncated') and updateSet.truncated:
                continue

            if last_version != version or time() > next_update:
                assoc = self.getHostGuestMapping()
                self._send_data(virt.HostGuestAssociationReport(self.config, assoc))
                next_update = time() + self.interval
                last_version = version

            if self._oneshot:
                break

        self.cleanup()

    def _format_hostname(self, host, domain):
        return u'{0}.{1}'.format(host, domain)

    def stop(self):
        # We need to ensure that when we stop the thread, we clean up and exit the wait
        self.cleanup()
        super(Esx, self).stop()

    def cleanup(self):
        self._cancel_wait()

        if self.filter is not None:
            try:
                self.client.service.DestroyPropertyFilter(self.filter)
            except suds.WebFault:
                pass
            self.filter = None

        self.logout()

    def getHostGuestMapping(self):
        mapping = {'hypervisors': []}
        for host_id, host in list(self.hosts.items()):
            parent = host['parent'].value
            if self.config['exclude_host_parents'] is not None and parent in self.config['exclude_host_parents']:
                self.logger.debug("Skipping host '%s' because its parent '%s' is excluded", host_id, parent)
                continue
            if self.config['filter_host_parents'] is not None and parent not in self.config['filter_host_parents']:
                self.logger.debug("Skipping host '%s' because its parent '%s' is not included", host_id, parent)
                continue
            guests = []

            try:
                if self.config['hypervisor_id'] == 'uuid':
                    uuid = host['hardware.systemInfo.uuid']
                elif self.config['hypervisor_id'] == 'hwuuid':
                    uuid = host_id
                elif self.config['hypervisor_id'] == 'hostname':
                    uuid = host['config.network.dnsConfig.hostName']
                    domain_name = host['config.network.dnsConfig.domainName']
                    if domain_name:
                        uuid = self._format_hostname(uuid, domain_name)
            except KeyError:
                self.logger.debug("Host '%s' doesn't have hypervisor_id property", host_id)
                continue

            if host['vm']:
                for vm_id in host['vm'].ManagedObjectReference:
                    if vm_id.value not in self.vms:
                        self.logger.debug("Host '%s' references non-existing guest '%s'", host_id, vm_id.value)
                        continue
                    vm = self.vms[vm_id.value]
                    if 'config.uuid' not in vm:
                        self.logger.debug("Guest '%s' doesn't have 'config.uuid' property", vm_id.value)
                        continue
                    if not vm['config.uuid'].strip():
                        self.logger.debug("Guest '%s' has empty 'config.uuid' property", vm_id.value)
                        continue
                    state = virt.Guest.STATE_UNKNOWN
                    try:
                        if vm['runtime.powerState'] == 'poweredOn':
                            state = virt.Guest.STATE_RUNNING
                        elif vm['runtime.powerState'] == 'suspended':
                            state = virt.Guest.STATE_PAUSED
                        elif vm['runtime.powerState'] == 'poweredOff':
                            state = virt.Guest.STATE_SHUTOFF
                    except KeyError:
                        self.logger.debug("Guest '%s' doesn't have 'runtime.powerState' property", vm_id.value)
                    guests.append(virt.Guest(vm['config.uuid'], self.CONFIG_TYPE, state))
            try:
                name = host['config.network.dnsConfig.hostName']
                domain_name = host['config.network.dnsConfig.domainName']
                if domain_name:
                    name = self._format_hostname(name, domain_name)
            except KeyError:
                self.logger.debug("Unable to determine hostname for host '%s'", uuid)
                name = ''

            facts = {
                virt.Hypervisor.CPU_SOCKET_FACT: str(host['hardware.cpuInfo.numCpuPackages']),
                virt.Hypervisor.HYPERVISOR_TYPE_FACT: host.get('config.product.name', 'vmware'),
            }

            if host['parent'] and host['parent']._type == 'ClusterComputeResource':
                cluster_id = host['parent'].value
                # print('', self.clusters, cluster_id)
                cluster = self.clusters[cluster_id]
                facts[virt.Hypervisor.HYPERVISOR_CLUSTER] = cluster['name']

            version = host.get('config.product.version', None)
            if version:
                facts[virt.Hypervisor.HYPERVISOR_VERSION_FACT] = version

            mapping['hypervisors'].append(virt.Hypervisor(hypervisorId=uuid, guestIds=guests, name=name, facts=facts))
        return mapping

    def login(self):
        """
        Log into ESX
        """

        kwargs = {'transport': RequestsTransport()}
        # Connect to the vCenter server
        if self.config['simplified_vim']:
            wsdl = 'file://%s/vimServiceMinimal.wsdl' % os.path.dirname(os.path.abspath(__file__))
            kwargs['cache'] = None
        else:
            wsdl = self.url + '/sdk/vimService.wsdl'
        try:
            self.client = suds.client.Client(wsdl, location="%s/sdk" % self.url, **kwargs)
        except requests.RequestException as e:
            raise virt.VirtError(str(e))

        self.client.set_options(timeout=self.MAX_WAIT_TIME)

        # Get Meta Object Reference to ServiceInstance which is the root object of the inventory
        self.moRef = suds.sudsobject.Property('ServiceInstance')
        self.moRef._type = 'ServiceInstance'  # pylint: disable=W0212

        # Service Content object defines properties of the ServiceInstance object
        try:
            self.sc = self.client.service.RetrieveServiceContent(_this=self.moRef)
        except requests.RequestException as e:
            raise virt.VirtError(str(e))

        # Login to server using given credentials
        try:
            # Don't log message containing password
            logging.getLogger('suds.client').setLevel(logging.CRITICAL)
            self.client.service.Login(
                _this=self.sc.sessionManager,
                userName=self.username,
                password=self.password
            )
            logging.getLogger('suds.client').setLevel(logging.ERROR)
        except requests.RequestException as e:
            raise virt.VirtError(str(e))
        except suds.WebFault as e:
            self.logger.exception("Unable to login to ESX")
            raise virt.VirtError(str(e))

    def logout(self):
        """ Log out from ESX. """
        try:
            if self.sc:
                self.client.service.Logout(_this=self.sc.sessionManager)
                self.sc = None
        except Exception as e:
            self.logger.info("Can't log out from ESX: %s", str(e))

    def createFilter(self):
        oSpec = self.objectSpec()
        oSpec.obj = self.sc.rootFolder
        oSpec.selectSet = self.buildFullTraversal()

        pfs = self.propertyFilterSpec()
        pfs.objectSet = [oSpec]
        pfs.propSet = [
            self.createPropertySpec("VirtualMachine", ["config.uuid", "runtime.powerState"]),
            self.createPropertySpec("ClusterComputeResource", ["name"]),
            self.createPropertySpec("HostSystem", ["name",
                                                   "vm",
                                                   "hardware.systemInfo.uuid",
                                                   "hardware.cpuInfo.numCpuPackages",
                                                   "parent",
                                                   "config.product.name",
                                                   "config.product.version",
                                                   "config.network.dnsConfig.hostName",
                                                   "config.network.dnsConfig.domainName"])
        ]

        try:
            return self.client.service.CreateFilter(_this=self.sc.propertyCollector, spec=pfs, partialUpdates=0)
        except requests.RequestException as e:
            raise virt.VirtError(str(e))

    def applyUpdates(self, updateSet):
        for filterSet in updateSet.filterSet:
            for objectSet in filterSet.objectSet:
                if objectSet.obj._type == 'VirtualMachine':  # pylint: disable=W0212
                    self.applyVirtualMachineUpdate(objectSet)
                elif objectSet.obj._type == 'HostSystem':  # pylint: disable=W0212
                    self.applyHostSystemUpdate(objectSet)
                elif objectSet.obj._type == 'ClusterComputeResource':
                    self.applyClusterComputeResource(objectSet)

    def applyClusterComputeResource(self, objectSet):
        if objectSet.kind in ['enter', 'kind']:
            cluster = self.clusters[objectSet.obj.value]
            for change in objectSet.changeSet:
                if change.op == 'assign' and hasattr(change, 'val'):
                    cluster[change.name] = change.val
        elif objectSet.kind == 'leave':
            del self.clusters[objectSet.obj.value]
        else:
            self.logger.error("Unknown update objectSet type: %s", objectSet.kind)

    def applyVirtualMachineUpdate(self, objectSet):
        if objectSet.kind in ['enter', 'modify']:
            vm = self.vms[objectSet.obj.value]
            for change in objectSet.changeSet:
                if change.op == 'assign' and hasattr(change, 'val'):
                    vm[change.name] = change.val
                elif change.op in ['remove', 'indirectRemove']:
                    try:
                        del vm[change.name]
                    except KeyError:
                        pass
                elif change.op == 'add':
                    vm[change.name].append(change.val)
                else:
                    self.logger.error("Unknown change operation: %s", change.op)
        elif objectSet.kind == 'leave':
            del self.vms[objectSet.obj.value]
        else:
            self.logger.error("Unknown update objectSet type: %s", objectSet.kind)

    def applyHostSystemUpdate(self, objectSet):
        if objectSet.kind in ['enter', 'modify']:
            host = self.hosts[objectSet.obj.value]
            for change in objectSet.changeSet:
                if change.op == 'indirectRemove':
                    # Host has been added but without sufficient data
                    # It will be filled in next update
                    pass
                elif change.op == 'assign' and hasattr(change, 'val'):
                    host[change.name] = change.val
        elif objectSet.kind == 'leave':
            del self.hosts[objectSet.obj.value]
        else:
            self.logger.error("Unknown update objectSet type: %s", objectSet.kind)

    def objectSpec(self):
        return self.client.factory.create('ns0:ObjectSpec')

    def traversalSpec(self):
        return self.client.factory.create('ns0:TraversalSpec')

    def selectionSpec(self):
        return self.client.factory.create('ns0:SelectionSpec')

    def propertyFilterSpec(self):
        return self.client.factory.create('ns0:PropertyFilterSpec')

    def buildFullTraversal(self):
        rpToRp = self.createTraversalSpec("rpToRp", "ResourcePool", "resourcePool", ["rpToRp", "rpToVm"])
        rpToVm = self.createTraversalSpec("rpToVm", "ResourcePool", "vm", [])
        crToRp = self.createTraversalSpec("crToRp", "ComputeResource", "resourcePool", ["rpToRp", "rpToVm"])
        crToH = self.createTraversalSpec("crToH", "ComputeResource", "host", [])
        dcToHf = self.createTraversalSpec("dcToHf", "Datacenter", "hostFolder", ["visitFolders"])
        dcToVmf = self.createTraversalSpec("dcToVmf", "Datacenter", "vmFolder", ["visitFolders"])
        hToVm = self.createTraversalSpec("HToVm", "HostSystem", "vm", ["visitFolders"])
        visitFolders = self.createTraversalSpec("visitFolders", "Folder", "childEntity", [
            "visitFolders", "dcToHf", "dcToVmf", "crToH", "crToRp", "HToVm", "rpToVm"])
        return [visitFolders, dcToVmf, dcToHf, crToH, crToRp, rpToRp, hToVm, rpToVm]

    def createPropertySpec(self, type, pathSet, all=False):
        pSpec = self.client.factory.create('ns0:PropertySpec')
        pSpec.all = all
        pSpec.type = type
        pSpec.pathSet = pathSet
        return pSpec

    def createTraversalSpec(self, name, type, path, selectSet):
        ts = self.traversalSpec()
        ts.name = name
        ts.type = type
        ts.path = path
        if len(selectSet) > 0 and isinstance(selectSet[0], str):
            selectSet = self.createSelectionSpec(selectSet)
        ts.selectSet = selectSet
        return ts

    def createSelectionSpec(self, names):
        sss = []
        for name in names:
            ss = self.selectionSpec()
            ss.name = name
            sss.append(ss)
        return sss


class Host(dict):
    def __init__(self):
        self.uuid = None
        self.vms = []


class VM(dict):
    def __init__(self):
        self.uuid = None


class Cluster(dict):
    def __init__(self):
        self.name = None
        self.hosts = []


class EsxConfigSection(VirtConfigSection):
    VIRT_TYPE = 'esx'
    HYPERVISOR_ID = ('uuid', 'hwuuid', 'hostname')

    def __init__(self, *args, **kwargs):
        super(EsxConfigSection, self).__init__(*args, **kwargs)
        self.add_key('server', validation_method=self._validate_server, required=True)
        self.add_key('username', validation_method=self._validate_username, required=True)
        self.add_key('password', validation_method=self._validate_unencrypted_password, required=True)
        self.add_key('is_hypervisor', validation_method=self._validate_str_to_bool, default=True)
        self.add_key('simplified_vim', validation_method=self._validate_str_to_bool, default=True)
        self.add_key('filter_host_parents', validation_method=self._validate_filter, default=None)
        self.add_key('exclude_host_parents', validation_method=self._validate_filter, default=None)

    def _validate_server(self, key):
        error = super(EsxConfigSection, self)._validate_server(key)
        if error is None:
            # Url must contain protocol (usually https://)
            if "://" not in self._values[key]:
                self._values[key] = "https://%s" % self._values[key]
        return error

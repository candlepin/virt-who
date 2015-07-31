"""
Module for communcating with vCenter/ESX, part of virt-who

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
import sys
import suds
import logging
from time import time
from urllib2 import URLError
import socket
from collections import defaultdict
from httplib import HTTPException

import virt

from virt import Hypervisor, Guest


class Esx(virt.Virt):
    CONFIG_TYPE = "esx"
    MAX_WAIT_TIME = 1800  # 30 minutes

    def __init__(self, logger, config):
        super(Esx, self).__init__(logger, config)
        self.url = config.server
        self.username = config.username
        self.password = config.password
        self.config = config

        # Url must contain protocol (usualy https://)
        if "://" not in self.url:
            self.url = "https://%s" % self.url

        self.filter = None

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
        start_time = end_time = time()
        initial = True

        while self._oneshot or not self.is_terminated():
            delta = end_time - start_time

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

            if version == '':
                # also, clean all data we have
                self.hosts.clear()
                self.vms.clear()

            start_time = time()
            try:
                updateSet = self.client.service.WaitForUpdatesEx(
                    _this=self.sc.propertyCollector,
                    version=version,
                    options={'maxWaitSeconds': max_wait_seconds})
                initial = False
            except (socket.error, URLError):
                self.logger.debug("Wait for ESX event finished, timeout")
                self._cancel_wait()
                # Get the initial update again
                version = ''
                continue
            except (suds.WebFault, HTTPException) as e:
                suppress_exception = False
                try:
                    if e.fault.faultstring == 'The session is not authenticated.':
                        # Do not print the exception if we get 'not authenticated',
                        # it's quite normal behaviour and nothing to worry about
                        suppress_exception = True
                except Exception:
                    pass
                if not suppress_exception:
                    self.logger.exception("Waiting for ESX events fails:")
                self._cancel_wait()
                version = ''
                self._prepare()
                start_time = end_time = time()
                continue

            if updateSet is not None:
                version = updateSet.version
                self.applyUpdates(updateSet)

            if hasattr(updateSet, 'truncated') and updateSet.truncated:
                continue

            if last_version != version:
                assoc = self.getHostGuestMapping()
                self._queue.put(virt.HostGuestAssociationReport(self.config, assoc))
                last_version = version

            end_time = time()

            if self._oneshot:
                break

            self.logger.debug("Waiting for ESX changes")

        self._cancel_wait()

        if self.filter is not None:
            self.client.service.DestroyPropertyFilter(self.filter)

    def getHostGuestMapping(self):
        mapping = {'hypervisors': []}
        for host_id, host in self.hosts.items():
            parent = host['parent'].value
            if self.config.exclude_host_parents is not None and parent in self.config.exclude_host_parents:
                self.logger.debug("Skipping host '%s' because its parent '%s' is excluded" % (host_id, parent))
                continue
            if self.config.filter_host_parents is not None and parent not in self.config.filter_host_parents:
                self.logger.debug("Skipping host '%s' because its parent '%s' is not included" % (host_id, parent))
                continue
            guests = []

            try:
                if self.config.hypervisor_id == 'uuid':
                    uuid = host['hardware.systemInfo.uuid']
                elif self.config.hypervisor_id == 'hwuuid':
                    uuid = host_id
                elif self.config.hypervisor_id == 'hostname':
                    uuid = host['name']
                else:
                    raise virt.VirtError('Reporting of hypervisor %s is not implemented in %s backend' % (
                        self.config.hypervisor_id,
                        self.CONFIG_TYPE))
            except KeyError:
                self.logger.debug("Host '%s' doesn't have hypervisor_id property" % host_id)
                continue
            if host['vm']:
                for vm_id in host['vm'].ManagedObjectReference:
                    if vm_id.value not in self.vms:
                        self.logger.debug("Host '%s' references non-existing guest '%s'" % (host_id, vm_id.value))
                        continue
                    vm = self.vms[vm_id.value]
                    if 'config.uuid' not in vm:
                        self.logger.debug("Guest '%s' doesn't have 'config.uuid' property" % vm_id.value)
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
                        self.logger.debug("Guest '%s' doesn't have 'runtime.powerState' property" % vm_id.value)
                    guests.append(virt.Guest(vm['config.uuid'], self, state))
            mapping['hypervisors'].append(Hypervisor(hypervisorId=uuid, guestIds=guests, name=host.get('name', None)))
        return mapping

    def login(self):
        """
        Log into ESX
        """

        kwargs = {}
        for env in ['https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY']:
            if env in os.environ:
                self.logger.debug("ESX module using proxy: %s" % os.environ[env])
                kwargs['proxy'] = {'https': os.environ[env]}
                break

        # Connect to the vCenter server
        if self.config.esx_simplified_vim:
            wsdl = 'file://%s/vimServiceMinimal.wsdl' % os.path.dirname(os.path.abspath(__file__))
            kwargs['cache'] = None
        else:
            wsdl = self.url + '/sdk/vimService.wsdl'
        try:
            self.client = suds.client.Client(wsdl, location="%s/sdk" % self.url, **kwargs)
        except URLError as e:
            self.logger.exception("Unable to connect to ESX")
            raise virt.VirtError(str(e))

        self.client.set_options(timeout=self.MAX_WAIT_TIME)

        # Get Meta Object Reference to ServiceInstance which is the root object of the inventory
        self.moRef = suds.sudsobject.Property('ServiceInstance')
        self.moRef._type = 'ServiceInstance'  # pylint: disable=W0212

        # Service Content object defines properties of the ServiceInstance object
        self.sc = self.client.service.RetrieveServiceContent(_this=self.moRef)

        # Login to server using given credentials
        try:
            # Don't log message containing password
            logging.getLogger('suds.client').setLevel(logging.CRITICAL)
            self.client.service.Login(_this=self.sc.sessionManager, userName=self.username, password=self.password)
            logging.getLogger('suds.client').setLevel(logging.ERROR)
        except suds.WebFault as e:
            self.logger.exception("Unable to login to ESX")
            raise virt.VirtError(str(e))

    def createFilter(self):
        oSpec = self.objectSpec()
        oSpec.obj = self.sc.rootFolder
        oSpec.selectSet = self.buildFullTraversal()

        pfs = self.propertyFilterSpec()
        pfs.objectSet = [oSpec]
        pfs.propSet = [
            self.createPropertySpec("VirtualMachine", ["config.uuid", "runtime.powerState"]),
            self.createPropertySpec("HostSystem", ["name", "vm", "hardware.systemInfo.uuid", "parent"])
        ]

        return self.client.service.CreateFilter(_this=self.sc.propertyCollector, spec=pfs, partialUpdates=0)

    def applyUpdates(self, updateSet):
        for filterSet in updateSet.filterSet:
            for objectSet in filterSet.objectSet:
                if objectSet.kind in ['enter', 'modify']:
                    if objectSet.obj._type == 'VirtualMachine':  # pylint: disable=W0212
                        vm = self.vms[objectSet.obj.value]
                        for change in objectSet.changeSet:
                            if change.op == 'assign':
                                vm[change.name] = change.val
                            elif change.op in ['remove', 'indirectRemove']:
                                try:
                                    del vm[change.name]
                                except KeyError:
                                    pass
                            elif change.op == 'add':
                                vm[change.name].append(change.val)
                            else:
                                self.logger.error("Unknown change operation: %s" % change.op)
                    elif objectSet.obj._type == 'HostSystem':  # pylint: disable=W0212
                        host = self.hosts[objectSet.obj.value]
                        for change in objectSet.changeSet:
                            if change.op == 'indirectRemove':
                                # Host has been added but without sufficient data
                                # It will be filled in next update
                                pass
                            elif change.op == 'assign':
                                host[change.name] = change.val
                elif objectSet.kind == 'leave':
                    if objectSet.obj._type == 'VirtualMachine':  # pylint: disable=W0212
                        del self.vms[objectSet.obj.value]
                    elif objectSet.obj._type == 'HostSystem':  # pylint: disable=W0212
                        del self.hosts[objectSet.obj.value]
                else:
                    self.logger.error("Unkown update objectSet type: %s" % objectSet.kind)

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
        if len(selectSet) > 0 and isinstance(selectSet[0], basestring):
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

if __name__ == '__main__':
    # TODO: read from config
    if len(sys.argv) < 4:
        print("Usage: %s url username password" % sys.argv[0])
        sys.exit(0)

    logger = logging.getLogger('virtwho.esx')
    logger.addHandler(logging.StreamHandler())
    from config import Config
    config = Config('esx', 'esx', sys.argv[1], sys.argv[2], sys.argv[3])
    vsphere = Esx(logger, config)
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
        vsphere.start_sync(q, Event())
    except KeyboardInterrupt:
        sys.exit(1)

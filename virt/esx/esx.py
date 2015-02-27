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
from suds.transport.http import HttpTransport as SudsHttpTransport
import logging
from datetime import datetime
from urllib2 import URLError
import socket
from collections import defaultdict

import virt

class WellBehavedHttpTransport(SudsHttpTransport):
    """
    HttpTransport which properly obeys the ``*_proxy`` environment variables.

    Taken from https://gist.github.com/rbarrois/3721801
    """
    def u2handlers(self):
        return []


class Esx(virt.Virt):
    CONFIG_TYPE = "esx"
    MAX_WAIT_TIME = 1800 # 30 minutes

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

    def _run(self):
        self.logger.debug("Log into ESX")
        self.login()

        self.logger.debug("Creating ESX event filter")
        self.filter = self.createFilter()

        version = ''
        self.hosts = defaultdict(Host)
        self.vms = defaultdict(VM)
        start_time = end_time = datetime.now()

        while self._oneshot or not self._terminate_event.is_set():
            delta = end_time - start_time
            # for python2.6, 2.7 has total_seconds method
            delta_seconds = ((delta.days * 86400 + delta.seconds) * 10**6 + delta.microseconds) / 10**6
            wait_time = self._interval - int(delta_seconds)
            if wait_time <= 0:
                self.logger.debug("Getting the host/guests association took too long, interval waiting is skipped")
                version = ''

            start_time = datetime.now()
            if version == '':
                # We want to read the update no matter how long it will take
                self.client.set_options(timeout=self.MAX_WAIT_TIME)
                # also, clean all data we have
                self.hosts.clear()
                self.vms.clear()
            else:
                self.client.set_options(timeout=wait_time)

            try:
                updateSet = self.client.service.WaitForUpdatesEx(_this=self.sc.propertyCollector, version=version)
            except socket.error:
                self.logger.debug("Wait for ESX event finished, timeout")
                # Cancel the update
                try:
                    self.client.service.CancelWaitForUpdates(_this=self.sc.propertyCollector)
                except Exception:
                    pass
                # Get the initial update again
                version = ''
                continue
            except suds.WebFault:
                self.logger.exception("Waiting for ESX events fails:")
                try:
                    self.client.service.CancelWaitForUpdates(_this=self.sc.propertyCollector)
                except Exception:
                    pass
                version = ''
                continue

            if updateSet is not None:
                version = updateSet.version
                self.applyUpdates(updateSet)

            assoc = self.getHostGuestMapping()
            self._queue.put(virt.HostGuestAssociationReport(self.config, assoc))
            end_time = datetime.now()

            if self._oneshot:
                break

            self.logger.debug("Waiting for ESX changes")

        try:
            self.client.service.CancelWaitForUpdates(_this=self.sc.propertyCollector)
        except Exception:
            pass

        if self.filter is not None:
            self.client.service.DestroyPropertyFilter(self.filter)

    def getHostGuestMapping(self):
        mapping = {}
        for host_id, host in self.hosts.items():
            parent = host['parent'].value
            if parent in self.config.exclude_host_parents:
                self.logger.debug("Skipping host '%s' because its parent '%s' is excluded" % (host_id, parent))
                continue
            if len(self.config.filter_host_parents) > 0 and parent not in self.config.filter_host_parents:
                self.logger.debug("Skipping host '%s' because its parent '%s' is not included" % (host_id, parent))
                continue

            guests = []
            uuid = host['hardware.systemInfo.uuid']
            mapping[uuid] = guests
            if not host['vm']:
                continue
            for vm_id in host['vm'].ManagedObjectReference:
                if vm_id.value not in self.vms:
                    self.logger.debug("Host '%s' references non-existing guest '%s'" % (host_id, vm_id.value))
                    continue
                vm = self.vms[vm_id.value]
                if 'config.uuid' not in vm:
                    self.logger.debug("Guest '%s' doesn't have 'config.uuid' property" % vm_id.value)
                    continue
                guests.append(vm['config.uuid'])
            mapping[uuid] = guests
        return mapping

    def login(self):
        """
        Log into ESX
        """

        # Connect to the vCenter server
        if self.config.esx_simplified_vim:
            wsdl = 'file://%s/vimServiceMinimal.wsdl' % os.path.dirname(os.path.abspath(__file__))
            kwargs = {'cache': None}
        else:
            wsdl = self.url + '/sdk/vimService.wsdl'
            kwargs = {}
        try:
            self.client = suds.client.Client(wsdl, location="%s/sdk" % self.url, transport=WellBehavedHttpTransport(), **kwargs)
        except URLError as e:
            self.logger.exception("Unable to connect to ESX")
            raise virt.VirtError(str(e))

        # Get Meta Object Reference to ServiceInstance which is the root object of the inventory
        self.moRef = suds.sudsobject.Property('ServiceInstance')
        self.moRef._type = 'ServiceInstance' # pylint: disable=W0212

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
            #self.propertySpec("ManagedEntity", ["name"]),
            self.createPropertySpec("VirtualMachine", ["config.uuid"]), #"config.guestFullName", "config.guestId", "config.instanceUuid"]),
            self.createPropertySpec("HostSystem", ["name", "vm", "hardware.systemInfo.uuid", "parent"]) #, "hardware.systemInfo.vendor", "hardware.systemInfo.model"])
        ]

        return self.client.service.CreateFilter(_this=self.sc.propertyCollector, spec=pfs, partialUpdates=0)

    def applyUpdates(self, updateSet):
        for filterSet in updateSet.filterSet:
            for objectSet in filterSet.objectSet:
                if objectSet.kind in ['enter', 'modify']:
                    if objectSet.obj._type == 'VirtualMachine': # pylint: disable=W0212
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
                    elif objectSet.obj._type == 'HostSystem': # pylint: disable=W0212
                        host = self.hosts[objectSet.obj.value]
                        for change in objectSet.changeSet:
                            host[change.name] = change.val
                elif objectSet.kind == 'leave':
                    if objectSet.obj._type == 'VirtualMachine': # pylint: disable=W0212
                        del self.vms[objectSet.obj.value]
                    elif objectSet.obj._type == 'HostSystem': # pylint: disable=W0212
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
        visitFolders = self.createTraversalSpec("visitFolders", "Folder", "childEntity",
                ["visitFolders", "dcToHf", "dcToVmf", "crToH", "crToRp", "HToVm", "rpToVm"])
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

    import log
    logger = log.getLogger(True, False)
    from config import Config
    config = Config('esx', 'esx', sys.argv[1], sys.argv[2], sys.argv[3])
    #config.esx_simplified_vim = False
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

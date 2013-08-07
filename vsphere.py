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

import sys
import suds

def get_search_filter_spec(client, begin_entity, property_spec):
    """ Build a PropertyFilterSpec capable of full inventory traversal.

    By specifying all valid traversal specs we are creating a PFS that
    can recursively select any object under the given enitity.
    """

    # The selection spec for additional objects we want to filter
    ss_strings = ['resource_pool_traversal_spec',
                  'resource_pool_vm_traversal_spec',
                  'folder_traversal_spec',
                  'datacenter_host_traversal_spec',
                  'datacenter_vm_traversal_spec',
                  'compute_resource_rp_traversal_spec',
                  'compute_resource_host_traversal_spec',
                  'host_vm_traversal_spec']

    # Create a selection spec for each of the strings specified above
    selection_specs = []
    for ss_string in ss_strings:
        sp = client.factory.create('ns0:SelectionSpec')
        sp.name = ss_string
        selection_specs.append(sp)

    rpts = client.factory.create('ns0:TraversalSpec')
    rpts.name = 'resource_pool_traversal_spec'
    rpts.type = 'ResourcePool'
    rpts.path = 'resourcePool'
    rpts.selectSet = [selection_specs[0], selection_specs[1]]

    rpvts = client.factory.create('ns0:TraversalSpec')
    rpvts.name = 'resource_pool_vm_traversal_spec'
    rpvts.type = 'ResourcePool'
    rpvts.path = 'vm'

    crrts = client.factory.create('ns0:TraversalSpec')
    crrts.name = 'compute_resource_rp_traversal_spec'
    crrts.type = 'ComputeResource'
    crrts.path = 'resourcePool'
    crrts.selectSet = [selection_specs[0], selection_specs[1]]

    crhts = client.factory.create('ns0:TraversalSpec')
    crhts.name = 'compute_resource_host_traversal_spec'
    crhts.type = 'ComputeResource'
    crhts.path = 'host'

    dhts = client.factory.create('ns0:TraversalSpec')
    dhts.name = 'datacenter_host_traversal_spec'
    dhts.type = 'Datacenter'
    dhts.path = 'hostFolder'
    dhts.selectSet = [selection_specs[2]]

    dvts = client.factory.create('ns0:TraversalSpec')
    dvts.name = 'datacenter_vm_traversal_spec'
    dvts.type = 'Datacenter'
    dvts.path = 'vmFolder'
    dvts.selectSet = [selection_specs[2]]

    hvts = client.factory.create('ns0:TraversalSpec')
    hvts.name = 'host_vm_traversal_spec'
    hvts.type = 'HostSystem'
    hvts.path = 'vm'
    hvts.selectSet = [selection_specs[2]]

    fts = client.factory.create('ns0:TraversalSpec')
    fts.name = 'folder_traversal_spec'
    fts.type = 'Folder'
    fts.path = 'childEntity'
    fts.selectSet = [selection_specs[2], selection_specs[3],
                     selection_specs[4], selection_specs[5],
                     selection_specs[6], selection_specs[7],
                     selection_specs[1]]

    obj_spec = client.factory.create('ns0:ObjectSpec')
    obj_spec.obj = begin_entity
    obj_spec.selectSet = [fts, dvts, dhts, crhts, crrts, rpts, hvts, rpvts]

    pfs = client.factory.create('ns0:PropertyFilterSpec')
    pfs.propSet = [property_spec]
    pfs.objectSet = [obj_spec]
    return pfs


class VSphere:
    def __init__(self, logger, url, username, password):
        self.logger = logger
        self.url = url

        # Url must contain protocol (usualy https://)
        if not "://" in self.url:
            self.url = "https://%s" % self.url

        # Connect to the vCenter server
        self.client = suds.client.Client("%s/sdk/vimService.wsdl" % self.url)

        self.client.set_options(location="%s/sdk" % self.url)

        # Get Meta Object Reference to ServiceInstance which is the root object of the inventory
        self.moRef = suds.sudsobject.Property('ServiceInstance')
        self.moRef._type = 'ServiceInstance'

        # Service Content object defines properties of the ServiceInstance object
        self.sc = self.client.service.RetrieveServiceContent(_this=self.moRef)

        # Login to server using given credentials
        self.client.service.Login(_this=self.sc.sessionManager, userName=username, password=password)

        self.clusters = {}
        self.hosts = {}
        self.vms = {}

    def scan(self):
        """
        Scan method does full inventory traversal on the vCenter machine. It finds
        all ComputeResources, Hosts and VirtualMachines.
        """

        # Clear results from last run
        self.clusters = {}
        self.hosts = {}
        self.vms = {}

        # Find all ComputeResources in whole vsphere tree
        ts = self.client.factory.create('ns0:PropertySpec')
        ts.type = 'ComputeResource'
        ts.pathSet = 'name'
        ts.all = True
        try:
            retrieve_result = self.client.service.RetrievePropertiesEx(_this=self.sc.propertyCollector,
                    specSet=[get_search_filter_spec(self.client, self.sc.rootFolder, [ts])])
            if retrieve_result is None:
                object_content = []
            else:
                object_content = retrieve_result[0]
        except suds.MethodNotFound:
            object_content = self.client.service.RetrieveProperties(_this=self.sc.propertyCollector,
                    specSet=[get_search_filter_spec(self.client, self.sc.rootFolder, [ts])])

        # Get properties of each cluster
        clusterObjs = [] # List of objs for 'ComputeResource' query
        for cluster in object_content:
            if not hasattr(cluster, 'propSet'):
                continue
            for propSet in cluster.propSet:
                if propSet.name == "name":
                    self.clusters[cluster.obj.value] = Cluster(propSet.val)
                    clusterObjs.append(cluster.obj)

        if len(clusterObjs) == 0:
            return

        # Get list of hosts from cluster
        object_contents = self.RetrieveProperties('ComputeResource', ['host'], clusterObjs)
        hostObjs = [] # List of objs for 'HostSystem' query
        for cluster in object_contents:
            if not hasattr(cluster, 'propSet'):
                continue
            for propSet in cluster.propSet:
                if propSet.name == 'host':
                    try:
                        for host in propSet.val.ManagedObjectReference:
                            h = Host()
                            self.hosts[host.value] = h
                            self.clusters[cluster.obj.value].hosts.append(h)
                            hostObjs.append(host)
                    except AttributeError:
                        # This means that there is no host on given cluster
                        pass

        if len(hostObjs) == 0:
            return

        # Get list of host uuids, names and virtual machines
        object_contents = self.RetrieveProperties('HostSystem', ['vm', 'hardware'], hostObjs)
        vmObjs = [] # List of objs for 'VirtualMachine' query
        for host in object_contents:
            if not hasattr(host, 'propSet'):
                continue
            for propSet in host.propSet:
                if propSet.name == "hardware":
                    self.hosts[host.obj.value].uuid = propSet.val.systemInfo.uuid
                elif propSet.name == "vm":
                    try:
                        for vm in propSet.val.ManagedObjectReference:
                            vmObjs.append(vm)
                            v = VM()
                            self.vms[vm.value] = v
                            self.hosts[host.obj.value].vms.append(v)
                    except AttributeError:
                        # This means that there is no guest on given host
                        pass

        if len(vmObjs) == 0:
            return

        # Get list of virtual machine uuids
        object_contents = self.RetrieveProperties('VirtualMachine', ['config'], vmObjs)
        for obj in object_contents:
            if not hasattr(obj, 'propSet'):
                continue
            for propSet in obj.propSet:
                if propSet.name == 'config':
                    # We need some uuid, let's try a couple of options
                    if propSet.val.uuid is not None:
                        self.vms[obj.obj.value].uuid = propSet.val.uuid
                    elif propSet.val.instanceUuid is not None:
                        self.vms[obj.obj.value].uuid = propSet.val.instanceUuid
                    else:
                        self.logger.error("No UUID for virtual machine %s", self.vms[obj.obj.value].name)
                        self.vms[obj.obj.value].uuid = None

    def ping(self):
        return True

    def RetrieveProperties(self, propSetType, propSetPathSet, objects):
        """
        Retrieve properties (defined by propSetPathSet) of objects of type propSetType.

        propSetType - name of the type to query
        propSetPathSet - property or list of properties to obtain
        objects - get properties of each object from this list

        return - object_properties struct
        """

        # PropertyFilterSpec is constructed from PropertySpec and ObjectSpec
        propSet = self.client.factory.create('ns0:PropertySpec')
        propSet.type = propSetType
        propSet.all = False
        propSet.pathSet = propSetPathSet

        objectSets = []
        for obj in objects:
            objectSet = self.client.factory.create('ns0:ObjectSpec')
            objectSet.obj = obj
            objectSets.append(objectSet)

        pfs = self.client.factory.create('ns0:PropertyFilterSpec')
        pfs.propSet = [propSet]
        pfs.objectSet = objectSets

        # Query the VSphere server
        try:
            retrieve_result = self.client.service.RetrievePropertiesEx(_this=self.sc.propertyCollector, specSet=[pfs])
            if retrieve_result is None:
                return []
            else:
                return retrieve_result[0]
        except suds.MethodNotFound:
            return self.client.service.RetrieveProperties(_this=self.sc.propertyCollector, specSet=[pfs])

    def getHostGuestMapping(self):
        """
        Returns dictionary with host to guest mapping, e.g.:

        { 'host_id_1': ['guest1', 'guest2'],
          'host_id_2': ['guest3', 'guest4'],
        }
        """
        self.scan()
        mapping = {}
        for cluster in self.clusters.values():
            for host in cluster.hosts:
                l = []
                for vm in host.vms:
                    # Stopped machine doesn't have any uuid
                    if vm.uuid is not None:
                        l.append(vm.uuid)
                mapping[host.uuid] = l
        return mapping

    def printLayout(self):
        """
        Prints the layout of vCenter.
        """
        for cluster in self.clusters.values():
            print "ComputeResource: %s" % cluster.name
            for host in cluster.hosts:
                print "\tHostSystem: %s" % host.uuid
                for vm in host.vms:
                    print "\t\tVirtualMachine: %s" % vm.uuid

class Cluster:
    def __init__(self, name):
        self.name = name
        self.hosts = []

class Host:
    def __init__(self):
        self.uuid = None
        self.vms = []

class VM:
    def __init__(self):
        self.uuid = None

if __name__ == '__main__':
    # TODO: read from config
    if len(sys.argv) < 4:
        print "Usage: %s url username password"
        sys.exit(0)

    import logging
    logger = logging.Logger("")
    vsphere = VSphere(logger, sys.argv[1], sys.argv[2], sys.argv[3])
    vsphere.scan()
    vsphere.printLayout()

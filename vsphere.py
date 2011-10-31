
import sys
import suds

#import logging
#logging.basicConfig(level=logging.INFO)
#logging.getLogger('suds.client').setLevel(logging.DEBUG)

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
    def __init__(self, url, username, password):
        self.url = url

        # Connect to the vCenter server
        self.client = suds.client.Client("%s/sdk/vimService.wsdl" % url)

        self.client.set_options(location="%s/sdk" % url)

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

        # Find all ComputeResources in whole vsphere tree
        ts = self.client.factory.create('ns0:PropertySpec')
        ts.type = 'ComputeResource'
        ts.pathSet = 'name'
        ts.all = True
        object_content = self.client.service.RetrieveProperties(_this=self.sc.propertyCollector,
                specSet=[get_search_filter_spec(self.client, self.sc.rootFolder, [ts])])

        # Get properties of each cluster
        clusterObjs = []
        for cluster in object_content:
            for propSet in cluster.propSet:
                if propSet.name == "name":
                    self.clusters[cluster.obj.value] = Cluster(cluster.obj, propSet.val)
                    clusterObjs.append(cluster.obj)

        # Get list of hosts from cluster
        object_contents = self.RetrieveProperties('ComputeResource', 'host', clusterObjs)
        hostObjs = []
        for cluster in object_contents:
            for propSet in cluster.propSet:
                if propSet.name == 'host':
                    for host in propSet.val.ManagedObjectReference:
                        h = Host(host)
                        self.hosts[host.value] = h
                        self.clusters[cluster.obj.value].hosts.append(h)
                        hostObjs.append(host)

        # Get list of host uuids, names and virtual machines
        object_contents = self.RetrieveProperties('HostSystem', ['name', 'vm', 'hardware'], hostObjs)
        vmObjs = []
        for host in object_contents:
            for propSet in host.propSet:
                if propSet.name == "name":
                    self.hosts[host.obj.value].name = propSet.val
                elif propSet.name == "hardware":
                    self.hosts[host.obj.value].uuid = propSet.val.systemInfo.uuid
                elif propSet.name == "vm":
                    for vm in propSet.val.ManagedObjectReference:
                        vmObjs.append(vm)
                        v = VM(vm)
                        self.vms[vm.value] = v
                        self.hosts[host.obj.value].vms.append(v)

        # Get list of virtual machine uuids
        object_contents = self.RetrieveProperties('VirtualMachine', ['name', 'config'], vmObjs)
        for obj in object_contents:
            for propSet in obj.propSet:
                if propSet.name == 'name':
                    self.vms[obj.obj.value].name = propSet.val
                elif propSet.name == 'config':
                    self.vms[obj.obj.value].uuid = propSet.val.uuid


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
        return self.client.service.RetrieveProperties(_this=self.sc.propertyCollector, specSet=[pfs])

    def printLayout(self):
        """
        Prints the layout of vCenter.
        """
        for cluster in self.clusters.values():
            print "ComputeResource: %s" % cluster.name
            for host in cluster.hosts:
                print "\tHostSystem: %s (%s)" % (host.name, host.uuid)
                for vm in host.vms:
                    print "\t\tVirtualMachine: %s (%s)" % (vm.name, vm.uuid)

class Cluster:
    def __init__(self, obj, name=None):
        self.obj = obj
        self._type = obj._type
        self.value = obj.value
        self.name = name
        self.uuid = None

        self.hosts = []

class Host:
    def __init__(self, obj, name=None):
        self.obj = obj
        self._type = obj._type
        self.value = obj.value
        self.name = name
        self.uuid = None

        self.vms = []

class VM:
    def __init__(self, obj, name=None):
        self.obj = obj
        self.value = obj.value
        self._type = obj._type
        self.name = name
        self.uuid = None

if __name__ == '__main__':
    # TODO: read from config
    if len(sys.argv) < 4:
        print "Usage: %s url username password"
        sys.exit(0)

    vsphere = VSphere(sys.argv[1], sys.argv[2], sys.argv[3])
    vsphere.scan()
    vsphere.printLayout()

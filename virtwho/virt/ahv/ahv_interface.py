#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

import json
import time
from requests import Session
from requests.exceptions import ConnectionError, ReadTimeout
from functools import reduce

from virtwho import virt


class AhvInterface(object):
    """
    AHV REST API interface class
    """

    NO_RETRY_HTTP_CODES = [400, 404, 500, 502, 503]

    def __init__(self, logger, url, username, password, port, **kwargs):
        """
        Args:
            logger (Log): Logger.
            url (str): Rest server url.
            username (str): Username.
            password (str): Password for rest client.
            port (int): Port number for ssp.
            kwargs(dict): Accepts following arguments:
                timeout(optional, int): Max seconds to wait before HTTP connection
                times-out. Default 30 seconds.
                retries (optional, int): Maximum number of retires. Default: 5.
                retry_interval (optional, int): Time to sleep between retry intervals.
                ahv_internal_debug (optional, bool): Detail log of the rest calls.
                Default: 5 seconds.
        """
        self._session = Session()
        self._timeout = kwargs.get('timeout', 30)
        self._retries = kwargs.get('retries', 5)
        self._retry_interval = kwargs.get('retry_interval', 30)
        self._logger = logger
        self._url = url
        self._user = username.encode('utf-8')
        self._password = password.encode('utf-8')
        self._port = port
        self._ahv_internal_debug = kwargs.get('ahv_internal_debug', False)
        self._create_session(self._user, self._password)

    def _create_session(self, user=None, password=None):
        """
        Creates rest session.
        Args:
            user (bytes): Username.
            password (bytes): Password for rest session.
        Returns:
            None.
        """
        if user is None:
            user = self._user
        if password is None:
            password = self._password
        self._session.auth = (user, password)

    def _make_url(self, uri, *args):
        """
        Creates base url.
        uri would always begin with a slash
        Args:
            uri (str): Uri.
            args (list): Args.
        Returns:
            url (str): Url with uri.
        """
        if not uri.startswith("/"):
            uri = "/%s" % uri
        url = "%s%s" % (self._url, uri)
        for arg in args:
            url += "/%s" % str(arg)
        return url

    def get(self, uri, *args, **kwargs):
        """
        Args are appended to the url as components.
        /arg1/arg2/arg3
        Send a get request with kwargs to the server.
        Args:
            uri (str): Uri.
            args (list): Args.
            kwargs (dict): Dictionary of params.
        Returns:
            Response (requests.Response): rsp.
        """
        url = self._make_url(uri, *args)
        return self._send('get', url, **kwargs)

    def post(self, uri, **kwargs):
        """
        Send a Post request to the server.
        Body can be either the dict or passed as kwargs
        headers is a dict.
        Args:
            uri (str): Uri.
            kwargs (dict): Dictionary of params.
        Returns:
            Response (requests.Response): rsp.
        """
        url = self._make_url(uri)
        return self._send('post', url, **kwargs)

    def make_rest_call(self, method, uri, *args, **kwargs):
        """This method calls the appropriate rest method based on the arguments.

        Args:
            method (str): HTTP method.
            uri (str): Relative_uri.
            args(any): Arguments.
            kwargs(dict): Key value pair for the additional args.

        Returns:
            rsp (dict): The response content loaded as a JSON.
        """
        func = getattr(self, method)
        return func(uri, *args, **kwargs)

    def _send(self, method, url, **kwargs):
        """This private method acting as proxy for all http methods.
        Args:
            method (str): The http method type.
            url (str): The URL to for the Request
            kwargs (dict): Keyword args to be passed to the requests call.
                retries (int): The retry count in case of HTTP errors.
                                             Except the codes in the list NO_RETRY_HTTP_CODES.

        Returns:
            Response (requests.Response): The response object.
        """
        kwargs['verify'] = kwargs.get('verify', False)
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self._timeout
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs['json'])
            del kwargs['json']
        else:
            body = {}
            kwargs['data'] = json.dumps(body)

        content_dict = {'content-type': 'application/json'}
        kwargs.setdefault('headers', {})
        kwargs['headers'].update(content_dict)

        func = getattr(self._session, method)
        response = None

        retries = kwargs.pop("retries", None)
        retry_interval = kwargs.pop("retry_interval", self._retry_interval)
        retry_count = retries if retries else self._retries
        for ii in range(retry_count):
            try:
                response = func(url, **kwargs)
                if self._ahv_internal_debug:
                    self._logger.debug("%s method The request url sent: %s" % (
                        method.upper(), response.request.url))
                    self._logger.debug('Response status: %d' % response.status_code)
                    self._logger.debug('Response: %s' % json.dumps(response.json(), indent=4))

            except (ConnectionError, ReadTimeout) as e:
                self._logger.warning("Request failed with error: %s" % e)
                if ii != retry_count - 1:
                    time.sleep(retry_interval)
                continue
            if response.ok:
                return response
            if response.status_code in [401, 403]:
                raise virt.VirtError(
                    'HTTP Auth Failed %s %s. \n res: response: %s' % (method, url, response)
                )
            elif response.status_code == 409:
                raise virt.VirtError(
                    'HTTP conflict with the current state of the '
                    'target resource %s %s. \n res: %s' % (method, url, response)
                )
            elif response.status_code in self.NO_RETRY_HTTP_CODES:
                break
            if ii != retry_count - 1:
                time.sleep(retry_interval)

        if response is not None:
            msg = 'HTTP %s %s failed: ' % (method, url)
            if hasattr(response, "text") and response.text:
                msg = "\n".join([msg, response.text]).encode('utf-8')
                self._logger.error(msg)
        else:
            self._logger.error("Failed to make the HTTP request (%s, %s)" % (method, url))


class AhvInterface2(AhvInterface):
    """
    AHV interface support version 2 of REST API
    """

    VERSION = 'v2.0'

    def get_vm_entities(self):
        """
        Returns the list of vms uuid.
        Returns:
            vm_uuid_list (list): list of vm's uuid.
        """
        self._logger.info("Getting the list of available vms")
        vm_uuid_list = []

        res = self.make_rest_call(method="get", uri="/vms")

        if res is None:
            self._logger.error("Unable to get list of VMs")
            return vm_uuid_list

        vm_entities = res.json()

        self._logger.info("Total number of vms uuids found and saved for processing %s" % len(vm_entities))
        return vm_entities["entities"]

    def get_host_list(self):
        """
        Returns the list of hosts.
        Returns:
            host_list (list): list of hosts.
        """
        host_list = []

        res = self.make_rest_call(method="get", uri="/hosts")

        # FIXME: when there is lot of hosts, then there is risk that not all hosts are returned
        # in one response (more details are in "metadata").

        data = res.json()
        if "entities" in data:
            host_list = data["entities"]
        return host_list

    def get_host_cluster_name(self, host_info, cluster_ids):
        """
        Returns host's cluster identifier if one exists.
        Args:
            host_info (dict): Host info dict.
            cluster_ids: List of tuples (UUID, name) of clusters
        Returns:
            host_cluster_name: The host's cluster name. If no name exists, then
                               the host's uuid will be returned. Otherwise, None
        """
        try:
            cluster_uuid = host_info['cluster_uuid']
        except (TypeError, KeyError):
            self._logger.error("No cluster UUID found for host.")
            return None

        for uuid, name in cluster_ids:
            if cluster_uuid == uuid:
                return name

        if cluster_uuid:
            self._logger.warning("No name found for host with uuid: %s. Using uuid." % cluster_uuid)

        return cluster_uuid

    def get_ahv_cluster_uuid_name_list(self):
        """
        Returns list of tuples with cluster uuids and names.
        Returns:
            ahv_host_cluster_uuids (List): Returns list of tuples with cluster uuids and names.
        """
        ahv_host_cluster_uuid_names = []

        res = self.make_rest_call(method="get", uri="/clusters")
        data = res.json()

        # FIXME: It is also possible that the list could not be complete, when the list of clusters
        # is too long. Information about number of gathered clusters is in metadata section too.
        # I cannot implement it ATM, because I don't know how this situation looks like and I
        # don't have system with more than one cluster.

        for cluster in data["entities"]:
            try:
                cluster_uuid = cluster['uuid']
                cluster_name = cluster["name"]
            except (TypeError, KeyError):
                self._logger.warning("cluster info does not contain metadata->uuid or spec->name")
                continue
            cluster_uuid_name = (cluster_uuid, cluster_name)
            if cluster_uuid not in ahv_host_cluster_uuid_names:
                ahv_host_cluster_uuid_names.append(cluster_uuid_name)

        return ahv_host_cluster_uuid_names

    def get_host_version(self, host_info):
        """
        Returns host's version.
        Args:
            host_info (dict): Host info dict.
        Returns:
            host_version (Str): Host version if found, None otherwise.
        """
        host_version = None
        if 'hypervisor_full_name' in host_info:
            host_version = host_info['hypervisor_full_name']
        else:
            self._logger.warning("Cannot get host version for %s" % host_info['uuid'])

        return host_version

    def get_host_uuid_from_vm(self, vm_entity):
        """
        Get the host uuid from the vm_entity response
        Args:
            vm_entity (dict): Vm info.
        Returns:
            host uuid (str): Vm host uuid if found, none otherwise.
        """
        if 'host_uuid' in vm_entity:
            vm_uuid = vm_entity['host_uuid']
            self._logger.debug(f"Host UUID {vm_uuid} found for VM: {vm_entity['uuid']}")
            return vm_uuid
        else:
            # Vm is off therefore no host is assigned to it.
            self._logger.debug(
                'Cannot get the host uuid of the VM: %s.' % vm_entity['uuid']
            )
        return None

    def build_host_to_uvm_map(self):
        """
        Builds a dictionary of every ahv host along with the vms they are hosting
        Returns:
            host_uvm_map (dict): Dict of ahv host with its uvms.
        """
        host_uvm_map = {}

        host_list = self.get_host_list()

        def reduce_host_vm_map(_host_uvm_map, _vm_entity):
            """
            This function is used by reduce() and it reduces generated list of entities
            to dictionary. Key is host UUID containing list of VMs running on this host
            """
            _host_uuid = None
            if _vm_entity:
                _host_uuid = self.get_host_uuid_from_vm(_vm_entity)
            if _host_uuid:
                if _host_uuid not in _host_uvm_map:
                    for _host in host_list:
                        if _host["uuid"] == _host_uuid:
                            _host_uvm_map[_host_uuid] = _host
                            _host_uvm_map[_host_uuid]['guest_list'] = []
                _host_uvm_map[_host_uuid]['guest_list'].append(_vm_entity)
            return _host_uvm_map

        vm_entities = self.get_vm_entities()

        host_uvm_map = reduce(reduce_host_vm_map, vm_entities, host_uvm_map)

        if len(host_uvm_map) > 0:
            return host_uvm_map
        else:
            self._logger.warning("No available VMs found. Trying to get list of hosts...")
            if len(host_list) > 0:
                for host in host_list:
                    host_uuid = host["uuid"]
                    if host_uuid not in host_uvm_map:
                        host_uvm_map[host_uuid] = host
                        host_uvm_map[host_uuid]['guest_list'] = []
            else:
                self._logger.warning("No Available AHV host found")
            return host_uvm_map


class AhvInterface3(AhvInterface):
    """
    AHV interface supporting version 3 of REST API
    """

    VERSION = 'v3'

    NUM_OF_REQUESTED_VMS = 20

    def get_vm_entities(self):
        """
        Try to get list of VM entities
        """
        self._logger.info("Getting the list of available VM entities")
        vm_entities = []
        length = self.NUM_OF_REQUESTED_VMS
        offset = 0

        kwargs = {
            "method": "post",
            "uri": "/vms/list",
            "json": {
                'length': length,
                'offset': offset
            }
        }

        while True:
            res = self.make_rest_call(**kwargs)

            if res is None:
                self._logger.error("Unable to get list of VMs")
                break

            data = res.json()

            # Try to get entities from the response
            if 'entities' in data:
                if len(data["entities"]) > 0:
                    vm_entities.extend(data["entities"])
                else:
                    # When the list of entities is empty, then we have gathered all
                    # entities, and we can break the loop
                    self._logger.debug("Gathered all VM entities")
                    break
            else:
                self._logger.error("No entities in the list of VMs")
                break

            if "metadata" in data:
                if "length" in data["metadata"]:
                    length = data["metadata"]["length"]
            else:
                self._logger.error("No metadata in the list of VMs")
                break

            kwargs["json"]['offset'] = kwargs["json"]['offset'] + length
            self._logger.debug('Next vm list call has this body: %s' % kwargs["json"])

        self._logger.info("Total number of vms uuids found and saved for processing %s" % len(vm_entities))
        return vm_entities

    def get_host_list(self):
        """
        Returns the list of hosts.
        Returns:
            host_list (list): list of hosts.
        """
        host_list = []

        res = self.make_rest_call(method="post", uri="/hosts/list")

        # FIXME: when there is lot of hosts, then there is risk that not all hosts are returned
        # in one response (more details are in "metadata")

        data = res.json()
        if "entities" in data:
            host_list = data["entities"]
        return host_list

    def get_host_cluster_name(self, host_info, cluster_uuid_name_list):
        """
        Returns host's cluster identifier if one exists.
        Args:
            host_info (dict): Host info dict.
            cluster_uuid_name_list: List of tuples (UUID, name) of clusters
        Returns:
            host_cluster_name: The host's cluster name. If no name exists, then
                               the host's uuid will be returned. Otherwise, None
        """
        try:
            host_cluster_uuid = host_info["status"]['cluster_reference']['uuid']
        except (TypeError, KeyError):
            self._logger.warning("host info does not contain status->cluster_reference->uuid")
            return None

        for uuid, name in cluster_uuid_name_list:
            if host_cluster_uuid == uuid:
                return name

        if host_cluster_uuid:
            self._logger.warning("No name found for host with uuid: %s. Using uuid." % host_cluster_uuid)

        return host_cluster_uuid

    def get_ahv_cluster_uuid_name_list(self):
        """
        Returns list of tuples with cluster uuids and names.
        Returns:
            ahv_host_cluster_uuids (List): Returns list of tuples with cluster uuids and names.
        """
        ahv_host_cluster_uuid_names = []

        res = self.make_rest_call(method="post", uri="/clusters/list")
        data = res.json()

        # FIXME: It is also possible that the list could not be complete, when the list of clusters
        # is too long. Information about number of gathered clusters is in metadata section too.
        # I cannot implement it ATM, because I don't know how this situation looks like and I
        # don't have system with more than one cluster.

        for cluster in data["entities"]:
            try:
                cluster_uuid = cluster["metadata"]['uuid']
                cluster_name = cluster["spec"]["name"]
            except (TypeError, KeyError):
                self._logger.warning("cluster info does not contain metadata->uuid or spec->name")
                continue
            cluster_uuid_name = (cluster_uuid, cluster_name)
            if cluster_uuid not in ahv_host_cluster_uuid_names:
                ahv_host_cluster_uuid_names.append(cluster_uuid_name)

        return ahv_host_cluster_uuid_names

    def get_host_version(self, host_info):
        """
        Returns host's version.
        Args:
            host_info (dict): Host info dict.
        Returns:
            host_version (Str): Host version if found, None otherwise.
        """
        host_version = None
        if "status" in host_info:
            if 'resources' in host_info["status"]:
                host_resources = host_info["status"]['resources']
                if 'hypervisor' in host_resources:
                    if 'hypervisor_full_name' in host_resources['hypervisor']:
                        host_version = host_resources['hypervisor']['hypervisor_full_name']
        else:
            self._logger.warning("Cannot get host version for %s" % host_info['uuid'])

        return host_version

    def get_host_uuid_from_vm(self, vm_entity):
        """
        Try to get the host uuid from the vm_entity
        Args:
            vm_entity (dict): Vm info.
        Returns:
            host uuid (str): Vm host uuid if found, None otherwise.
        """
        try:
            vm_uuid = vm_entity['metadata']['uuid']
        except KeyError:
            self._logger.warning("Did not find VM UUID in information for VM")
            vm_uuid = None

        if "status" not in vm_entity:
            self._logger.warning("Did not find status section in information for VM")
            return None

        if "resources" not in vm_entity["status"]:
            self._logger.warning("Did not find resources sub-section in information for VM")
            return None

        if "host_reference" in vm_entity["status"]["resources"]:
            host_uuid = vm_entity["status"]['resources']['host_reference']['uuid']
            self._logger.debug(f"Host UUID {host_uuid} found for VM: {vm_uuid}")
            return host_uuid
        else:
            self._logger.debug(f"Did not find any host information for VM: {vm_uuid}")

        return None

    def build_host_to_uvm_map(self):
        """
        Builds a dictionary of every ahv host along with the vms they are hosting
        Returns:
            host_uvm_map (dict): Dict of ahv host with its uvms.
        """
        host_uvm_map = {}

        host_list = self.get_host_list()

        def reduce_host_vm_map_v3(_host_uvm_map, _vm_entity):
            """
            This function is used by reduce() and it reduces generated list of entities
            to dictionary. Key is host UUID containing list of VMs running on this host
            """
            _host_uuid = None
            if _vm_entity and "status" in _vm_entity:
                _host_uuid = self.get_host_uuid_from_vm(_vm_entity)
            if _host_uuid:
                if _host_uuid not in _host_uvm_map:
                    for _host in host_list:
                        if _host["metadata"]["uuid"] == _host_uuid:
                            _host_uvm_map[_host_uuid] = _host
                            _host_uvm_map[_host_uuid]['guest_list'] = []
                _host_uvm_map[_host_uuid]['guest_list'].append(_vm_entity)
            return _host_uvm_map

        vm_entities = self.get_vm_entities()

        host_uvm_map = reduce(reduce_host_vm_map_v3, vm_entities, host_uvm_map)

        if len(host_uvm_map) > 0:
            return host_uvm_map
        else:
            self._logger.warning("No available VMs found. Trying to get list of hosts...")
            if len(host_list) > 0:
                for host in host_list:
                    host_uuid = host["metadata"]["uuid"]
                    if host_uuid not in host_uvm_map:
                        host_uvm_map[host_uuid] = host
                        host_uvm_map[host_uuid]['guest_list'] = []
            else:
                self._logger.warning("No Available AHV host found")
            return host_uvm_map


class Failure(Exception):
    def __init__(self, details):
        self.details = details

    def __str__(self):
        try:
            return str(self.details)
        except Exception as exn:
            print(exn)
            return "AHV-API failure: %s" % str(self.details)

    def _details_map(self):
        return dict([(str(i), self.details[i]) for i in range(len(self.details))])

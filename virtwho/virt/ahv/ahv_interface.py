import json
import math
import time
import sys
from . import ahv_constants
from requests import Session
from requests.exceptions import ConnectionError, ReadTimeout
from virtwho import virt


class AhvInterface(object):
    """ AHV REST Api interface class"""
    NO_RETRY_HTTP_CODES = [400, 404, 500, 502, 503]
    event_types = ['node', 'vm']

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
            user (str): Username.
            password (str): Password for rest session.
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

    def _format_response(self, data):
        """
        Format the data based on the response's version.
        Args:
            data (dict): Data dictionary.
        Returns:
            formatted_data (dict): Formatted dictionary.
        """
        if 'entities' in data:
            return self._process_entities_list(data['entities'])
        else:
            return self._process_dict_response(data)

    def _process_dict_response(self, data):
        """
        Format the data when we only have a dictionary.
        Args:
            data (dict): Data dictionary.
        Returns:
            formatted_data (dict): Formatted data.
        """
        formatted_data = data
        if 'status' in data and 'metadata' in data:
            formatted_data = dict(data['status'], **data['metadata'])

        if 'resources' in formatted_data:
            if 'power_state' in formatted_data['resources']:
                formatted_data['power_state'] = \
                    formatted_data['resources']['power_state']
            if 'num_cpu_sockets' in formatted_data['resources']:
                formatted_data['num_cpu_sockets'] = \
                    formatted_data['resources']['num_cpu_sockets']

        return formatted_data

    def _process_entities_list(self, data):
        """
        Format data for the list of entities.
        Args:
            data (list): List of entities dictionary.
        Returns:
            formatted_data (dict): Formatted data after processing list fo entities.
        """
        formatted_data = data
        initial = True
        for entity in data:
            if 'status' in entity and 'metadata' in entity:
                if initial:
                    formatted_data = []
                    initial = False
                formatted_data.append(dict(entity['status'], **entity['metadata']))

        for ent_obj in formatted_data:
            if 'resources' in ent_obj:
                if 'nodes' in ent_obj['resources']:
                    nodes = ent_obj['resources']['nodes']
                    if 'hypervisor_server_list' in nodes:
                        ent_obj['hypervisor_types'] = []
                        for server in nodes['hypervisor_server_list']:
                            ent_obj['hypervisor_types'].append(server['type'])

            if 'kind' in ent_obj:
                if ent_obj['kind'] == 'cluster':
                    if 'uuid' in ent_obj:
                        ent_obj['cluster_uuid'] = ent_obj['uuid']

        return formatted_data

    def _progressbar(self, it, prefix="", size=60, file=sys.stderr, total=0, is_pc=False):
        count = total
        cursor = 0

        def show(j):
            x = int(size*j/count)
            file.write("%s[%s%s] %i/%i\r" % (prefix, "#"*x, "."*(size-x), j, count))
            file.flush()
        show(0)

        for i, item in enumerate(it):
            if is_pc:
                yield item
                for i in range(20):
                    show(cursor+1)
                    cursor += 1
                    if cursor == count:
                        break
                    time.sleep(0.1)
            else:
                show(i+1)

        yield item
        file.write("\n")
        file.flush()

    def login(self, version):
        """
        Login to the rest server and ensure connection succeeds.
        Args:
            version (Str): Interface version.
        Returns:
            None.
        """
        (url, cmd_method) = self.get_diff_ver_url_and_method(
            cmd_key='list_clusters', intf_version=version)
        self.make_rest_call(method=cmd_method, uri=url)
        self._logger.info("Successfully logged into the AHV REST server")

    def get_hypervisor_type(self, version, host_entity=None, vm_entity=None):
        """
        Get the hypervisor type of the guest vm.
        Args:
            version (Str): API version.
            host_entity (Dict): Host info dict.
            vm_entity (Dict): Vm info dict.
        Returns:
            hypervisor_type (str): Vm hypervisor type.
        """
        hypervisor_type = None
        if version == 'v2.0':
            if host_entity:
                hypervisor_type = host_entity['hypervisor_type']
            else:
                self._logger.warning("Cannot retrieve the host type. Version:%s" % version)
        else:
            if vm_entity:
                if 'resources' in vm_entity:
                    if 'hypervisor_type' in vm_entity['resources']:
                        hypervisor_type = vm_entity['resources']['hypervisor_type']
                    else:
                        self._logger.debug("Hypervisor type of the %s is not available" % vm_entity['uuid'])
            else:
                self._logger.warning(
                    "No vm entity is provided for version %s. "
                    "Therefore it's unable to retrieve host type" % version
                )
        return hypervisor_type

    def get_common_ver_url_and_method(self, cmd_key):
        """
        Gets the correct cmd name based on its corresponding version.
        Args:
            cmd_key (str): Key name to search for in the command dict.
        Returns:
            (str, str) : Tuple of (command, rest_type).
        """
        return (
            ahv_constants.CMN_RST_CMD[cmd_key]['url'],
            ahv_constants.CMN_RST_CMD[cmd_key]['method']
        )

    def get_diff_ver_url_and_method(self, cmd_key, intf_version):
        """
        Gets the correct cmd name based on its corresponding version
        Args:
            cmd_key (str): Key name to search for in the command dict.
            intf_version (str): Interface version.
        Returns:
            (str, str) : Tuple of (command, rest_type).
        """
        return (
            ahv_constants.REST_CMD[intf_version][cmd_key]['url'],
            ahv_constants.REST_CMD[intf_version][cmd_key]['method']
        )

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
            finally:
                self._session.close()
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

    def get_tasks(self, timestamp, version, is_pc=False):
        """
        Returns a list of AHV tasks which happened after timestamp.
        Args:
            timestamp (int): Current timestamp.
            version (str): Interface version.
            is_pc (bool): Flag to determine f we need to poll for PC tasks.
        Returns:
            Task list (list): list of tasks.
        """
        ahv_clusters = self.get_ahv_cluster_uuid_map(version)
        (uri, cmd_method) = self.get_common_ver_url_and_method(cmd_key='get_tasks')
        # For task return. Use fv2.0 for now. update the url to use v2.0.
        url = self._url[:(self._url).rfind('v')] + 'v2.0' + uri

        body = {"entity_list": [{"entity_type": "kVm"}]}
        res = self._send(method=cmd_method, url=url, json=body)
        data = res.json()

        if is_pc:
            return self.get_pc_tasks(data, timestamp, ahv_clusters)
        else:
            return self.get_pe_tasks(data, timestamp, ahv_clusters)

    def get_pc_tasks(self, data, timestamp, ahv_clusters):
        """
        Returns a list of AHV tasks on PC which happened after timestamp.
        Args:
            data (json): Rest response in json format.
            timestamp (str): Current timestamp.
            ahv_clusters (list): List of ahv clusters uuid.
        Returns:
            task_list (list): list of tasks on PC.
        """
        (uri, cmd_method) = self.get_common_ver_url_and_method(cmd_key='get_task')
        # For task return. Use fv2.0 for now. update the url to use v2.0.
        url = self._url[:(self._url).rfind('v')] + 'v2.0' + uri

        task_completed = False
        task_list = []
        if 'entities' in data:
            for task in data['entities']:
                if 'start_time_usecs' in task:
                    if task['start_time_usecs'] > timestamp:

                        if 'progress_status' in task:
                            if task['progress_status'] in ahv_constants.TASK_COMPLETE_MSG:
                                task_completed = True
                        elif 'status' in task:
                            if task['status'] in ahv_constants.TASK_COMPLETE_MSG:
                                task_completed = True

                        if task_completed:
                            task_completed = False
                            if 'subtask_uuid_list' in task:
                                for subtask in task['subtask_uuid_list']:
                                    url = url % subtask
                                    subtask_resp = self._send(cmd_method, url)
                                    subtask_data = subtask_resp.json()

                                    if 'progress_status' in subtask_data:
                                        if subtask_data['progress_status'] in ahv_constants.TASK_COMPLETE_MSG:

                                            if 'cluster_uuid' in subtask_data:
                                                cluster_uuid = subtask_data['cluster_uuid']
                                            else:
                                                # Task does not have any cluster associated with it,
                                                # skip it.
                                                continue

                                            if cluster_uuid in ahv_clusters:
                                                if 'entity_list' in task:
                                                    entity_type_list = task['entity_list']
                                                else:
                                                    # Task doesn't have any entity list, skip it.
                                                    continue

                                            if entity_type_list:
                                                for ent_type in entity_type_list:
                                                    if 'entity_type' in ent_type:
                                                        if (str(ent_type['entity_type'])).lower() \
                                                                        in self.event_types:
                                                            task_list.append(task)
                                                            task_list.append(subtask_data)

                                        else:
                                            # Task has not finished or it failed, skip it and continue
                                            # the loop
                                            continue

        return task_list

    def get_pe_tasks(self, data, timestamp, ahv_clusters):
        """
        Returns a list of AHV tasks on PE which happened after timestamp.
        Args:
            data (json): rest response in json format.
            timestamp (str): Current timestamp.
            ahv_clusters (list): list of ahv clusters uuid.
        Returns:
            task_list (list): list of tasks on PE.
        """
        task_completed = False
        task_list = []

        if 'entities' in data:
            for task in data['entities']:
                if 'start_time_usecs' in task:
                    if task['start_time_usecs'] > timestamp:

                        if 'progress_status' in task:
                            if task['progress_status'] in ahv_constants.TASK_COMPLETE_MSG:
                                task_completed = True
                        elif 'status' in task:
                            if task['status'] in ahv_constants.TASK_COMPLETE_MSG:
                                task_completed = True

                        if task_completed:
                            task_completed = False
                            if 'cluster_reference' in task:
                                if 'uuid' in task['cluster_reference']:
                                    cluster_uuid = task['cluster_reference']['uuid']
                            elif 'cluster_uuid' in task:
                                cluster_uuid = task['cluster_uuid']
                            else:
                                # Task does not have any cluster associated with it, skip it.
                                continue

                            if cluster_uuid in ahv_clusters:
                                if 'entity_list' in task:
                                    entity_type_list = task['entity_list']
                                elif 'entity_reference_list' in task:
                                    entity_type_list = task['entity_reference_list']
                                else:
                                    # Task doesn't have any entity list, skip it.
                                    continue

                                for ent_type in entity_type_list:
                                    if 'entity_type' in ent_type:
                                        if (str(ent_type['entity_type'])).lower() \
                                                        in self.event_types:
                                            task_list.append(task)
                                    elif 'kind' in ent_type:
                                        if (str(ent_type['kind'])).lower() in self.event_types:
                                            task_list.append(task)
                                    else:
                                        # Task doesn't have any event type associated to it.
                                        continue
        return task_list

    def get_vms_uuid(self, version):
        """
        Returns the list of vms uuid.
        Args:
            version (str): Interface version.
        Returns:
            vm_uuid_list (list): list of vm's uuid.
        """
        self._logger.info("Getting the list of available vms")
        is_pc = True if version == 'v3' else False
        vm_uuid_list = []
        length = ahv_constants.NUM_OF_REQUESTED_VMS
        initial_offset = 0
        offset = 0
        total_matches = 0
        count = 1
        current = 0
        (url, cmd_method) = self.get_diff_ver_url_and_method(
            cmd_key='list_vms', intf_version=version)
        if cmd_method == 'post':
            body = {
                'length': length,
                'offset': initial_offset
            }
            res = self.make_rest_call(method=cmd_method, uri=url, json=body)
        else:
            res = self.make_rest_call(method=cmd_method, uri=url)
        data = res.json()
        if "metadata" in data:
            if "total_matches" in data["metadata"] and "length" in data["metadata"]:
                length = data["metadata"]["length"]
                total_matches = data["metadata"]["total_matches"]
            elif (
                "count" in data["metadata"]
                and "grand_total_entities" in data["metadata"]
                and "total_entities" in data["metadata"]
            ):
                total_matches = data["metadata"]["grand_total_entities"]
                count = data["metadata"]["count"]
                length = data["metadata"]["total_entities"]

        if length < total_matches:
            self._logger.debug(
                'Number of vms %s returned from REST is less than the total'
                'number: %s. Adjusting the offset and iterating over all'
                'vms until evry vm is returned from the server.' % (length, total_matches)
            )
            count = math.ceil(total_matches/float(length))

        body = {'length': length, 'offset': offset}
        for i in self._progressbar(range(int(count)), "Finding vms uuid: ", total=int(total_matches), is_pc=is_pc):
            if 'entities' in data:
                for vm_entity in data['entities']:
                    if 'metadata' in vm_entity:
                        vm_uuid_list.append(vm_entity['metadata']['uuid'])
                    elif 'uuid' in vm_entity:
                        vm_uuid_list.append(vm_entity['uuid'])
                    else:
                        self._logger.warning(
                            "Cannot access the uuid for the vm %s. "
                            "vm object: %s" % (vm_entity['name'], vm_entity)
                        )

            body['offset'] = body['offset'] + length
            self._logger.debug('next vm list call has this body: %s' % body)
            res = self.make_rest_call(method=cmd_method, uri=url, json=body)
            data = res.json()
            current += 1

        self._logger.info("Total number of vms uuids found and saved for processing %s" % len(vm_uuid_list))
        return vm_uuid_list

    def get_hosts_uuid(self, version):
        """
        Returns the list of host uuid.
        Args:
            version (str): Interface version.
        Returns:
            host_uuid_list (list): list of host's uuid.
        """
        host_uuid_list = []
        (url, cmd_method) = self.get_diff_ver_url_and_method(
            cmd_key='list_hosts', intf_version=version)

        res = self.make_rest_call(method=cmd_method, uri=url)
        data = res.json()
        if 'entities' in data:
            for host_entity in data['entities']:
                if 'status' in host_entity and 'metadata' in host_entity:
                    # Check if a physical host, not a cluster.
                    if 'cpu_model' in host_entity['status']:
                        host_uuid_list.append(host_entity['metadata']['uuid'])
                elif 'uuid' in host_entity:
                    host_uuid_list.append(host_uuid_list['uuid'])
                else:
                    self._logger.warning(
                        "Cannot access the uuid for the. "
                        "host object: %s" % (host_entity)
                    )

    def get_host_cluster_name(self, host_info, cluster_ids):
        """
        Returns host's cluster identifier if one exists.
        Args:
            host_info (dict): Host info dict.
            cluster_ids: Map of UUID to name for clusters
        Returns:
            host_cluster_name: The host's cluster name. If no name exists, then
                               the host's uuid will be returned. Otherwise, None
        """
        this_uuid = None
        if 'cluster_uuid' in host_info:
            this_uuid = host_info['cluster_uuid']
        elif 'cluster_reference' in host_info:
            this_uuid = host_info['cluster_reference']['uuid']

        for uuid, name in cluster_ids:
            if this_uuid == uuid and name:
                return name
        if this_uuid:
            self._logger.warning("No name found for host with uuid: %s. Using uuid." % this_uuid)
        return this_uuid

    def get_ahv_cluster_uuid_map(self, version):
        """
        Returns list of tuples with cluster uuids and names.
        Args:
            version (str): Interface version.
        Returns:
            ahv_host_cluster_uuids (List): Returns list of tuples with cluster uuids and names.
        """
        ahv_host_cluster_uuids = []
        seen = set(ahv_host_cluster_uuids)

        (url, cmd_method) = self.get_diff_ver_url_and_method(
            cmd_key='list_clusters', intf_version=version)
        res = self.make_rest_call(method=cmd_method, uri=url)
        data = res.json()

        formatted_data = self._format_response(data)

        for cluster in formatted_data:
            if 'hypervisor_types' in cluster and 'cluster_uuid' in cluster:
                for hypevirsor_type in cluster['hypervisor_types']:
                    if hypevirsor_type in ahv_constants.AHV_HYPERVIRSOR:
                        cluster_uuid = (cluster['cluster_uuid'], cluster['name'])
                        if cluster_uuid not in seen:
                            seen.add(cluster_uuid)
                            ahv_host_cluster_uuids.append(cluster_uuid)
                            break

        return ahv_host_cluster_uuids

    def get_host_version(self, host_info):
        """
        Returns host's version.
        Args:
            host_info (dict): Host info dict.
        Returns:
            host_version (Str): Host version if found, None otherwise.
        """
        host_version = None
        if 'resources' in host_info:
            host_resources = host_info['resources']
            if 'hypervisor' in host_resources:
                if 'hypervisor_full_name' in host_resources['hypervisor']:
                    host_version = host_resources['hypervisor']['hypervisor_full_name']
        elif 'hypervisor_full_name' in host_info:
            host_version = host_info['hypervisor_full_name']
        else:
            self._logger.warning("Cannot get host version for %s" % host_info['uuid'])

        return host_version

    def get_vm(self, uuid):
        """
        Returns vm information
        Args:
            uuid (str): Vm uuid.
        Return:
            data (dict): Vm information.
        """
        (url, cmd_method) = self.get_common_ver_url_and_method(cmd_key='get_vm')
        url = url % uuid
        res = self.make_rest_call(method=cmd_method, uri=url)
        if res:
            data = res.json()
            return self._format_response(data)
        return None

    def get_host(self, uuid):
        """
        Returns host information
        Args:
            uuid (str): Host uuid.
        Return:
            data (dict): Host information.
        """
        (url, cmd_method) = self.get_common_ver_url_and_method(cmd_key='get_host')
        url = url % uuid
        res = self.make_rest_call(method=cmd_method, uri=url)
        if res:
            data = res.json()
            return self._format_response(data)
        else:
            return None

    def get_vm_host_uuid_from_vm(self, vm_entity):
        """
        Get the host uuid from the vm_entity response
        Args:
            vm_entity (dict): Vm info.
        Returns:
            host uuid (str): Vm host uuid if found, none otherwise.
        """
        if 'resources' in vm_entity:
            if 'host_reference' in vm_entity['resources']:
                return vm_entity['resources']['host_reference']['uuid']
            else:
                self._logger.warning(
                    "Did not find any host information for vm:%s" % vm_entity['uuid']
                )
        elif 'host_uuid' in vm_entity:
            return vm_entity['host_uuid']
        else:
            # Vm is off therefore no host is assigned to it.
            self._logger.debug(
                'Cannot get the host uuid of the vm:%s. '
                'perhaps the vm is powered off' % vm_entity['uuid']
            )
        return None

    def is_ahv_host(self, version, host_uuid, vm_entity=None):
        """
        Determine if a given host is a AHV host.
        host uuid should match the host uuid in vm_entity.
        Args:
            version (str): API version.
            host_uuid (str): uuid of a host.
            vm_entity (dict): For v3
        Returns:
            bool : True if host is ahv; false otehrwise.
        """
        if version == 'v2.0':
            host = self.get_host(host_uuid)
            if 'hypervisor_type' in host:
                return host['hypervisor_type'] in ahv_constants.AHV_HYPERVIRSOR
        else:
            if 'resources' in vm_entity:
                if 'hypervisor_type' in vm_entity['resources']:
                    return vm_entity['resources']['hypervisor_type'] in \
                                 ahv_constants.AHV_HYPERVIRSOR
        self._logger.debug(
            'Hypervisor type not found. \nversion:%s, '
            '\nhost_uuid:%s, \nvm_entity:%s' % (version, host_uuid, vm_entity)
        )
        return False

    def build_host_to_uvm_map(self, version):
        """
        Builds a dictionary of every ahv host along with the vms they are hosting
        Args:
            version (Str): API version
        Returns:
            host_uvm_map (dict): Dict of ahv host with its uvms.
        """
        host_uvm_map = {}
        vm_entity = None
        host_uuid = None
        vm_uuids = self.get_vms_uuid(version)

        self._logger.info("Processing hosts for each vm.")
        if len(vm_uuids) > 0:
            for vm_uuid in vm_uuids:
                vm_entity = self.get_vm(vm_uuid)
                if vm_entity:
                    host_uuid = self.get_vm_host_uuid_from_vm(vm_entity)
                    if host_uuid:
                        if self.is_ahv_host(version, host_uuid, vm_entity):
                            host = self.get_host(host_uuid)
                            if host:
                                if host_uuid not in host_uvm_map:
                                    host_uvm_map[host_uuid] = host
                                if 'guest_list' in host_uvm_map[host_uuid]:
                                    host_uvm_map[host_uuid]['guest_list'].append(vm_entity)
                                else:
                                    host_uvm_map[host_uuid]['guest_list'] = []
                                    host_uvm_map[host_uuid]['guest_list'].append(vm_entity)
                            else:
                                self._logger.warning("unable to read information for host %s" % host_uuid)
                                continue
                        else:
                            self._logger.debug("Host %s is not ahv, skipping it." % host_uuid)
                            continue
                        host_type = self.get_hypervisor_type(version, host, vm_entity)
                        host_uvm_map[host_uuid]['hypervisor_type'] = host_type
        else:
            self._logger.warning("No available vms found")
            try:
                host_uuids = self.get_hosts_uuid(version)
                if len(host_uuids) > 0:
                    for host_uuid in host_uuids:
                        host = self.get_host(host_uuid)
                        if host_uuid not in host_uvm_map:
                            host_uvm_map[host_uuid] = host
                            host_uvm_map[host_uuid]['guest_list'] = []

                else:
                    self._logger.warning("No Available AHV host found")
            except TypeError:
                # In case there is no cluster registered to the PC.
                self._logger.warning("Unable to find any AHV hosts.")

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

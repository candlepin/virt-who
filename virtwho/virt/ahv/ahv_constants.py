SERVER_BASE_URIL = 'https://%s:%d/api/nutanix/%s'
AHV_HYPERVIRSOR = ['kKvm', 'AHV', 'ahv', 'kvm']
TASK_COMPLETE_MSG = ['SUCCEEDED', 'Succeeded']
DEFAULT_PORT = 9440
VERSION_2 = 'v2.0'
VERSION_3 = 'v3'
NUM_OF_REQUESTED_VMS = 100

CMN_RST_CMD = {
    'get_vm': {'url': '/vms/%s', 'method': 'get'},
    'get_host': {'url': '/hosts/%s', 'method': 'get'},
    'get_tasks': {'url': '/tasks/list', 'method': 'post'},
    'get_task': {'url': '/tasks/%s', 'method': 'get'},
}

REST_CMD = {
    VERSION_2: {
        'list_vms': {'url': '/vms', 'method': 'get'},
        'list_hosts': {'url': '/hosts', 'method': 'get'},
        'list_clusters': {'url': '/clusters', 'method': 'get'},
    },
    VERSION_3: {
        'list_vms': {'url': '/vms/list', 'method': 'post'},
        'list_hosts': {'url': '/hosts/list', 'method': 'post'},
        'list_clusters': {'url': '/clusters/list', 'method': 'post'},
    },
}
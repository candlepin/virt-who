from __future__ import print_function
import socket
import xmlrpc.client
import requests
from abc import ABCMeta
import uuid

from string import digits
from string import ascii_letters as letters


__all__ = ('decode', 'generate_reporter_id', 'clean_filename', 'RequestsXmlrpcTransport')


class Singleton(ABCMeta):
    """
    As Metaclasses are responsible for the creation of classes, class attributes
    declared on the metaclass will end up as an attribute on the resultant classes.
    This Metaclass enables all classes that use it to share the '_instances' dict.
    Actual instances of each such class are maintained there.

    See https://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
    for an explanation of why we want to create a metaclass for Singletons in python
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Registers an instance of the given class to the shared _instances class attribute.
        Creates the instance required if not already existant.
        Please note any class that is already initialized will ignore new args and kwargs.
        Returns: The one instance of the given class.
        """
        if cls not in cls._instances:
            # Create the actual instance of the class and add it to those we are tracking
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class RequestsXmlrpcTransport(xmlrpc.client.SafeTransport):
    """
    Transport for xmlrpclib that uses Requests instead of httplib.

    This unifies network handling with other backends. For example
    proxy support will be same as for other modules.
    """
    # change our user agent to reflect Requests
    user_agent = "Python XMLRPC with Requests"

    def __init__(self, url, *args, **kwargs):
        self._url = url
        xmlrpc.client.SafeTransport.__init__(self, *args, **kwargs)

    def request(self, host, handler, request_body, verbose):
        """
        Make an xmlrpc request.
        """
        headers = {'User-Agent': self.user_agent}
        resp = requests.post(self._url, data=request_body, headers=headers, verify=False)
        try:
            resp.raise_for_status()
        except requests.RequestException as e:
            raise xmlrpc.client.ProtocolError(self._url, resp.status_code, str(e), resp.headers)
        else:
            return self.parse_response(resp)

    def parse_response(self, resp):
        """
        Parse the xmlrpc response.
        """
        p, u = self.getparser()
        p.feed(resp.content)
        p.close()
        return u.close()


# A list of desired characters allowed in filenames
VALID_FILENAME_CHARS = set([char for char in letters + digits + '_-'])


def decode(input):
    if isinstance(input, dict):
        return dict((decode(key), decode(value)) for key, value in input.items())
    elif isinstance(input, list):
        return [decode(element) for element in input]
    else:
        return input


def clean_filename(name):
    return ''.join([char for char in name if char in VALID_FILENAME_CHARS])


def get_machine_id():
    try:
        with open('/etc/machine-id') as machine_id_file:
            machine_id = machine_id_file.readline().strip()
    except IOError:
        machine_id = None
    return machine_id


def generate_reporter_id():
    hostname = socket.gethostname()
    machine_id = get_machine_id()
    if not machine_id or len(machine_id) == 0:
        return hostname
    else:
        return hostname + '-' + machine_id


class DictItemsIter(object):
    """
    A dictionary iterator that is compatible with python3.
    Iterates over the items in the dictionary it is initialized with
    """
    def __init__(self, items):
        self.items = items
        self.keys = sorted(self.items.keys())

    def __iter__(self):
        return self

    def __next__(self):
        if len(self.keys) == 0:
            raise StopIteration
        key = self.keys.pop()
        return key, self.items[key]

    def next(self):
        return self.__next__()


def generate_correlation_id():
    return str(uuid.uuid4()).replace('-', '')  # FIXME cp should accept -

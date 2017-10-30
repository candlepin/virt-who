import socket
import xmlrpclib
import requests
from abc import ABCMeta

try:
    from thread import get_ident as _get_ident
except ImportError:  # pragma: no cover
    from dummy_thread import get_ident as _get_ident

try:
    from _abcoll import KeysView, ValuesView, ItemsView
except ImportError:  # pragma: no cover
    pass
from string import letters, digits


__all__ = ('OrderedDict', 'decode', 'generateReporterId', 'clean_filename', 'RequestsXmlrpcTransport')


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



class RequestsXmlrpcTransport(xmlrpclib.SafeTransport):
    """
    Transport for xmlrpclib that uses Requests instead of httplib.

    This unifies network handling with other backends. For example
    proxy support will be same as for other modules.
    """
    # change our user agent to reflect Requests
    user_agent = "Python XMLRPC with Requests"

    def __init__(self, url, *args, **kwargs):
        self._url = url
        xmlrpclib.SafeTransport.__init__(self, *args, **kwargs)

    def request(self, host, handler, request_body, verbose):
        """
        Make an xmlrpc request.
        """
        headers = {'User-Agent': self.user_agent}
        resp = requests.post(self._url, data=request_body, headers=headers, verify=False)
        try:
            resp.raise_for_status()
        except requests.RequestException as e:
            raise xmlrpclib.ProtocolError(self._url, resp.status_code, str(e), resp.headers)
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


# Taken from http://code.activestate.com/recipes/576693/

# Backport of OrderedDict() class that runs on Python 2.4, 2.5, 2.6, 2.7 and pypy.
# Passes Python2.7's test suite and incorporates all the latest updates.
class OrderedDict(dict):  # pragma: no cover
    'Dictionary that remembers insertion order'
    # An inherited dict maps keys to values.
    # The inherited dict provides __getitem__, __len__, __contains__, and get.
    # The remaining methods are order-aware.
    # Big-O running times for all methods are the same as for regular dictionaries.

    # The internal self.__map dictionary maps keys to links in a doubly linked list.
    # The circular doubly linked list starts and ends with a sentinel element.
    # The sentinel element never gets deleted (this simplifies the algorithm).
    # Each link is stored as a list of length three:  [PREV, NEXT, KEY].

    def __init__(self, *args, **kwds):
        '''Initialize an ordered dictionary.  Signature is the same as for
        regular dictionaries, but keyword arguments are not recommended
        because their insertion order is arbitrary.

        '''
        if len(args) > 1:
            raise TypeError('expected at most 1 arguments, got %d' % len(args))
        try:
            self.__root
        except AttributeError:
            self.__root = root = []                     # sentinel node
            root[:] = [root, root, None]
            self.__map = {}
        self.__update(*args, **kwds)

    def __setitem__(self, key, value, dict_setitem=dict.__setitem__):
        'od.__setitem__(i, y) <==> od[i]=y'
        # Setting a new item creates a new link which goes at the end of the linked
        # list, and the inherited dictionary is updated with the new key/value pair.
        if key not in self:
            root = self.__root
            last = root[0]
            last[1] = root[0] = self.__map[key] = [last, root, key]
        dict_setitem(self, key, value)

    def __delitem__(self, key, dict_delitem=dict.__delitem__):
        'od.__delitem__(y) <==> del od[y]'
        # Deleting an existing item uses self.__map to find the link which is
        # then removed by updating the links in the predecessor and successor nodes.
        dict_delitem(self, key)
        link_prev, link_next, key = self.__map.pop(key)
        link_prev[1] = link_next
        link_next[0] = link_prev

    def __iter__(self):
        'od.__iter__() <==> iter(od)'
        root = self.__root
        curr = root[1]
        while curr is not root:
            yield curr[2]
            curr = curr[1]

    def __reversed__(self):
        'od.__reversed__() <==> reversed(od)'
        root = self.__root
        curr = root[0]
        while curr is not root:
            yield curr[2]
            curr = curr[0]

    def clear(self):
        'od.clear() -> None.  Remove all items from od.'
        try:
            for node in self.__map.itervalues():
                del node[:]
            root = self.__root
            root[:] = [root, root, None]
            self.__map.clear()
        except AttributeError:
            pass
        dict.clear(self)

    def popitem(self, last=True):
        '''od.popitem() -> (k, v), return and remove a (key, value) pair.
        Pairs are returned in LIFO order if last is true or FIFO order if false.

        '''
        if not self:
            raise KeyError('dictionary is empty')
        root = self.__root
        if last:
            link = root[0]
            link_prev = link[0]
            link_prev[1] = root
            root[0] = link_prev
        else:
            link = root[1]
            link_next = link[1]
            root[1] = link_next
            link_next[0] = root
        key = link[2]
        del self.__map[key]
        value = dict.pop(self, key)
        return key, value

    # -- the following methods do not depend on the internal structure --

    def keys(self):
        'od.keys() -> list of keys in od'
        return list(self)

    def values(self):
        'od.values() -> list of values in od'
        return [self[key] for key in self]

    def items(self):
        'od.items() -> list of (key, value) pairs in od'
        return [(key, self[key]) for key in self]

    def iterkeys(self):
        'od.iterkeys() -> an iterator over the keys in od'
        return iter(self)

    def itervalues(self):
        'od.itervalues -> an iterator over the values in od'
        for k in self:
            yield self[k]

    def iteritems(self):
        'od.iteritems -> an iterator over the (key, value) items in od'
        for k in self:
            yield (k, self[k])

    def update(*args, **kwds):
        '''od.update(E, **F) -> None.  Update od from dict/iterable E and F.

        If E is a dict instance, does:           for k in E: od[k] = E[k]
        If E has a .keys() method, does:         for k in E.keys(): od[k] = E[k]
        Or if E is an iterable of items, does:   for k, v in E: od[k] = v
        In either case, this is followed by:     for k, v in F.items(): od[k] = v

        '''
        if len(args) > 2:
            raise TypeError('update() takes at most 2 positional '
                            'arguments (%d given)' % (len(args),))
        elif not args:
            raise TypeError('update() takes at least 1 argument (0 given)')
        self = args[0]
        # Make progressively weaker assumptions about "other"
        other = ()
        if len(args) == 2:
            other = args[1]
        if isinstance(other, dict):
            for key in other:
                self[key] = other[key]
        elif hasattr(other, 'keys'):
            for key in other.keys():
                self[key] = other[key]
        else:
            for key, value in other:
                self[key] = value
        for key, value in kwds.items():
            self[key] = value

    __update = update  # let subclasses override update without breaking __init__

    __marker = object()

    def pop(self, key, default=__marker):
        '''od.pop(k[,d]) -> v, remove specified key and return the corresponding value.
        If key is not found, d is returned if given, otherwise KeyError is raised.

        '''
        if key in self:
            result = self[key]
            del self[key]
            return result
        if default is self.__marker:
            raise KeyError(key)
        return default

    def setdefault(self, key, default=None):
        'od.setdefault(k[,d]) -> od.get(k,d), also set od[k]=d if k not in od'
        if key in self:
            return self[key]
        self[key] = default
        return default

    def __repr__(self, _repr_running={}):
        'od.__repr__() <==> repr(od)'
        call_key = id(self), _get_ident()
        if call_key in _repr_running:
            return '...'
        _repr_running[call_key] = 1
        try:
            if not self:
                return '%s()' % (self.__class__.__name__,)
            return '%s(%r)' % (self.__class__.__name__, self.items())
        finally:
            del _repr_running[call_key]

    def __reduce__(self):
        'Return state information for pickling'
        items = [[k, self[k]] for k in self]
        inst_dict = vars(self).copy()
        for k in vars(OrderedDict()):
            inst_dict.pop(k, None)
        if inst_dict:
            return self.__class__, (items,), inst_dict
        return self.__class__, (items,)

    def copy(self):
        'od.copy() -> a shallow copy of od'
        return self.__class__(self)

    @classmethod
    def fromkeys(cls, iterable, value=None):
        '''OD.fromkeys(S[, v]) -> New ordered dictionary with keys from S
        and values equal to v (which defaults to None).

        '''
        d = cls()
        for key in iterable:
            d[key] = value
        return d

    def __eq__(self, other):
        '''od.__eq__(y) <==> od==y.  Comparison to another OD is order-sensitive
        while comparison to a regular mapping is order-insensitive.

        '''
        if isinstance(other, OrderedDict):
            return len(self) == len(other) and self.items() == other.items()
        return dict.__eq__(self, other)

    def __ne__(self, other):
        return not self == other

    # -- the following methods are only used in Python 2.7 --

    def viewkeys(self):
        "od.viewkeys() -> a set-like object providing a view on od's keys"
        return KeysView(self)

    def viewvalues(self):
        "od.viewvalues() -> an object providing a view on od's values"
        return ValuesView(self)

    def viewitems(self):
        "od.viewitems() -> a set-like object providing a view on od's items"
        return ItemsView(self)


def decode(input):
    if isinstance(input, dict):
        return dict((decode(key), decode(value)) for key, value in input.iteritems())
    elif isinstance(input, list):
        return [decode(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input


def clean_filename(name):
    return ''.join([char for char in name if char in VALID_FILENAME_CHARS])


def getMachineId():
    try:
        with open('/etc/machine-id') as machine_id_file:
            machine_id = machine_id_file.readline().strip()
    except IOError:
        machine_id = None
    return machine_id


def generateReporterId():
    hostname = socket.gethostname()
    machine_id = getMachineId()
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

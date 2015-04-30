
from virt import Virt, VirtError

import json

def _decode_dict(data):
    rv = {}
    for key, value in data.iteritems():
        if isinstance(key, unicode):
            key = key.encode('utf-8')
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        rv[key] = value
    return rv

class FakeVirt(Virt):
    CONFIG_TYPE = 'fake'

    def __init__(self, logger, config):
        super(FakeVirt, self).__init__(logger, config)
        self.logger = logger
        self.config = config

    def _get_data(self):
        # TODO: do some checking of the file content
        try:
            with open(self.config.fake_file, 'r') as f:
                return json.load(f, object_hook=_decode_dict)
        except (IOError, ValueError) as e:
            raise VirtError("Can't read fake '%s' virt data: %s" % (self.config.fake_file, str(e)))


    def isHypervisor(self):
        return self.config.fake_is_hypervisor

    def getHostGuestMapping(self):
        assoc = {}
        try:
            for hypervisor in self._get_data()['hypervisors']:
                guests = []
                assoc[hypervisor['uuid']] = guests
                for guest in hypervisor['guests']:
                    guests.append(guest)
        except KeyError as e:
            raise VirtError("Fake virt file '%s' is not properly formed: %s" % (self.config.fake_file, str(e)))
        return assoc

    def listDomains(self):
        hypervisor = self._get_data()['hypervisors'][0]
        return hypervisor['guests']

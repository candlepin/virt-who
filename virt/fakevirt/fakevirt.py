
from virt import Virt, VirtError, Guest

import json

def _decode(input):
    if isinstance(input, dict):
        return dict((_decode(key), _decode(value)) for key, value in input.iteritems())
    elif isinstance(input, list):
        return [_decode(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input

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
                return json.load(f, object_hook=_decode)
        except (IOError, ValueError) as e:
            raise VirtError("Can't read fake '%s' virt data: %s" % (self.config.fake_file, str(e)))


    def isHypervisor(self):
        return self.config.fake_is_hypervisor

    def getHostGuestMapping(self):
        assoc = {}
        try:
            for hypervisor in self._get_data()['hypervisors']:
                guests = []
                assoc[hypervisor['hypervisorId']] = guests
                for guest in hypervisor['guestIds']:
                    guests.append(Guest(guest['guestId'], self, guest['state']))
        except KeyError as e:
            raise VirtError("Fake virt file '%s' is not properly formed: %s" % (self.config.fake_file, str(e)))
        return assoc

    def listDomains(self):
        hypervisor = self._get_data()['hypervisors'][0]
        return hypervisor['guests']

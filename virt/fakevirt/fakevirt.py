
from virt import Virt, VirtError, Guest, Hypervisor

import json
from util import decode


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
                return json.load(f, object_hook=decode)
        except (IOError, ValueError) as e:
            raise VirtError("Can't read fake '%s' virt data: %s" % (self.config.fake_file, str(e)))


    def isHypervisor(self):
        return self.config.fake_is_hypervisor

    def getHostGuestMapping(self):
        assoc = {'hypervisors': []}
        try:
            for hypervisor in self._get_data()['hypervisors']:
                guests = []
                for guest in hypervisor['guestIds']:
                    guests.append(Guest(guest['guestId'], self, guest['state']))
                new_host = Hypervisor(hypervisor['hypervisorId'],
                                      guests,
                                      hypervisor.get('name')
                                      )
                assoc['hypervisors'].append(new_host)
        except KeyError as e:
            raise VirtError("Fake virt file '%s' is not properly formed: %s" % (self.config.fake_file, str(e)))
        return assoc

    def listDomains(self):
        hypervisor = self._get_data()['hypervisors'][0]
        return hypervisor['guestIds']

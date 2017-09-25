
import json

from virtwho.virt import Virt, VirtError, Guest, Hypervisor
from virtwho.util import decode


class FakeVirt(Virt):
    CONFIG_TYPE = 'fake'

    def __init__(self, logger, config, shared_data, dest, terminate_event=None,
                 interval=None, oneshot=False):
        super(FakeVirt, self).__init__(logger, config, shared_data, dest,
                                       terminate_event=terminate_event,
                                       interval=interval,
                                       oneshot=oneshot)
        self.logger = logger
        self.config = config

    def _read_data(self):
        # TODO: do some checking of the file content
        try:
            with open(self.config.file, 'r') as f:
                return json.load(f, object_hook=decode)
        except (IOError, ValueError) as e:
            raise VirtError("Can't read fake '%s' virt data: %s" % (self.config.file, str(e)))

    def isHypervisor(self):
        if self.config.is_hypervisor is None:
            return True
        return self.config.is_hypervisor

    def _process_guest(self, guest):
        attributes = guest.get('attributes', {})
        self.CONFIG_TYPE = attributes.get('virtWhoType', 'fake')
        return Guest(guest['guestId'], self, guest['state'])

    def _process_hypervisor(self, hypervisor):
        guests = []
        for guest in hypervisor['guests']:
            guests.append(self._process_guest(guest))
        return Hypervisor(hypervisor['uuid'],
                          guests,
                          hypervisor.get('name'),
                          hypervisor.get('facts'))

    def getHostGuestMapping(self):
        assoc = {'hypervisors': []}
        try:
            for hypervisor in self._read_data()['hypervisors']:
                assoc['hypervisors'].append(self._process_hypervisor(hypervisor))
        except KeyError as e:
            raise VirtError("Fake virt file '%s' is not properly formed: %s" % (self.config.file, str(e)))
        return assoc

    def listDomains(self):
        hypervisor = self._read_data()['hypervisors'][0]
        if 'uuid' in hypervisor:
            raise VirtError("Fake virt file '%s' is not properly formed: "
                            "uuid key shouldn't be present, try to check is_hypervisor value" %
                            self.config.file)
        guests = []
        for guest in hypervisor['guests']:
            guests.append(self._process_guest(guest))
        return guests

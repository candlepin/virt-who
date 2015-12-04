#!/usr/bin/env python

import sys
from time import time
import XenAPI
from XenAPI import Failure, NewMaster
from collections import defaultdict, OrderedDict
import virt

class Guest(object):
    """
    This class represents one virtualization guest running on some
    host/hypervisor.
    """

    STATE_UNKNOWN = 0      # unknown state
    STATE_RUNNING = 1      # running
    STATE_BLOCKED = 2      # blocked on resource
    STATE_PAUSED = 3       # paused by user
    STATE_SHUTINGDOWN = 4  # guest is being shut down
    STATE_SHUTOFF = 5      # shut off
    STATE_CRASHED = 6      # crashed
    STATE_PMSUSPENDED = 7  # suspended by guest power management

    def __init__(self,
                 uuid,
                 virt,
                 state,
                 hypervisorType=None,
                 hypervisorVersion=None):
        """
        Create new guest instance that will be sent to the subscription manager.

        `uuid` is unique identification of the guest.

        `virt` is a `Virt` class instance that represents virtualization hypervisor
        that owns the guest.

        `hypervisorType` is additional type of the virtualization, used in libvirt.

        `state` is a number that represents the state of the guest (stopped, running, ...)

        `hypervisorVersion` is the version of the hypervisor software running on
        the hypervisor, if available. If none is available then the value of
        this attribute will be an empty string ""
            - This attribute is only included in the dictionary representation
              if the hypervisorType is not None.
        """
        self.uuid = uuid
        self.virtWhoType = virt.CONFIG_TYPE
        self.hypervisorType = hypervisorType
        self.state = state
        self.hypervisorVersion = hypervisorVersion or ""

    def toDict(self):
        d = dict((
            ('guestId', self.uuid),
            ('state', self.state),
            ('attributes', {
                'virtWhoType': self.virtWhoType,
                'active': 1 if self.state in (self.STATE_RUNNING, self.STATE_PAUSED) else 0
            }),
        ))

        if self.hypervisorType is not None:
            d['attributes']['hypervisorType'] = self.hypervisorType
            if self.hypervisorVersion is not None or \
               self.hypervisorVersion is not "":
                d['attributes']['hypervisorVersion'] = self.hypervisorVersion
        return d

class Hypervisor(object):
    """
    A model for information about a hypervisor
    """
    def __init__(self, hypervisorId,  guestIds=None, name=None, facts=None):
        """
        Create a new Hypervisor that will be sent to subscription manager

        'hypervisorId': the unique identifier for this hypervisor

        'guestIds': a list of Guests

        'name': the hostname, if available
        """
        self.hypervisorId = hypervisorId
        self.guestIds = guestIds or []
        self.name = name
        self.facts = facts


    def toDict(self):
        d = dict((
            ('hypervisorId', {'hypervisorId': self.hypervisorId}),
            ('name', self.name),
            ('guestIds', [g.toDict() for g in self.guestIds])
        ))
        if self.name is None:
            del d['name']
        if self.facts is not None:
            d['facts'] = self.facts
        return d

    def __str__(self):
        return str(self.toDict())

    def getHash(self):
        sortedRepresentation = json.dumps(self.toDict(), sort_keys=True)
        return hashlib.md5(sortedRepresentation).hexdigest()

class Xen(virt.Virt):
    CONFIG_TYPE = "xen"
    # if no events occur the call to event_from will return after this interval
    # if events do occur the call will return sooner
    EVENT_FROM_TIMEOUT = 30.0

    # if the token parameter is set to an empty string, the return from event_from will contain all
    # events that have occurred, you probably want to use this the first time you use event_from
    token_from =''

    # Register for events on all classes
    event_types = ["*"]

    def __init__(self, logger, config):
        super(Xen, self).__init__(logger, config)
        self.url = config.server
        self.username = config.username
        self.password = config.password
        self.config = config

        # Url must contain protocol (usualy https://)
        if "://" not in self.url:
            self.url = "https://%s" % self.url

        self.filter = None

    def _prepare(self):
        """ Prepare for obtaining information from Xen server. """
        self.logger.debug("Log into XEN pools %s" % self.url)
        self.login()

    def login(self):
        # Login to server using given credentials
        try:
            # Don't log message containing password
            self.session = XenAPI.Session(self.url)
            self.session.xenapi.login_with_password(self.username, self.password)
            self.logger.debug("I'm in XEN pools! with user %s" % self.username)

        except NewMaster as nm:
            self.logger.debug("Tengo un nuevo master?")
            try:
                self.session = XenAPI.Session('http://%s' % nm.new_master())
                self.session.xenapi.login_with_password(self.username, self.password)
                self.logger.debug("I'm in XEN pools with new master %s! with user %s" % (nm.new_master(), self.username))

            except:
                self.logger.exception("Unable to login to XENserver %s" % self.url)
                raise

        except:
            self.logger.exception("Unable to login to XENserver %s" % self.url)
            raise

    def getHostGuestMapping(self):
        hosts= self.session.xenapi.host.get_all()

        mapping = {}

        for host in hosts:

            record= self.session.xenapi.host.get_record(host)
            guests=[]

            for resident in self.session.xenapi.host.get_resident_VMs(host):
                vm= self.session.xenapi.VM.get_record(resident)

                if vm['power_state'] == 'Running':
                    state = virt.Guest.STATE_RUNNING
                elif vm['power_state'] == 'Suspended':
                    state = virt.Guest.STATE_PAUSED
                elif vm['power_state'] == 'Paused':
                    state = virt.Guest.STATE_PAUSED
                elif vm['power_state'] == 'Halted':
                    state = virt.Guest.STATE_SHUTOFF
                else:
                    state = virt.Guest.STATE_UNKNOWN

                guests.append(virt.Guest(
                        uuid= vm["uuid"],
                        virt= self,
                        state= state,
                        hypervisorType=None
                    )
                )

            mapping[record["hostname"]]=guests
        return mapping

    def _run(self):
        self._prepare()

        self.hosts = defaultdict(Host)
        self.vms = defaultdict(VM)
        start_time = end_time = time()
        initial = True


        while self._oneshot or not self.is_terminated():
            delta = end_time - start_time
            try:
                event_from_ret = self.session.xenapi.event_from(self.event_types,
                                                            self.token_from, 
                                                            self.EVENT_FROM_TIMEOUT)
                events = event_from_ret['events']
            except:
                events = []

            if initial:
                # We want to read the update asap
                max_wait_seconds = 0
            else:
                if delta - self._interval > 2.0:
                    # The update took longer than it should, don't wait so long next time
                    max_wait_seconds = max(self._interval - int(delta - self._interval), 0)
                    self.logger.debug(
                        "Getting the host/guests association took too long,"
                        "interval waiting is shortened to %s", max_wait_seconds)
                else:
                    max_wait_seconds = self._interval

            start_time = time()

            if len(events) > 0:
                assoc = self.getHostGuestMapping()
                self._queue.put(virt.HostGuestAssociationReport(self.config, assoc))

                event_from_ret = self.session.xenapi.event_from(self.event_types,
                                                                self.token_from,
                                                                self.EVENT_FROM_TIMEOUT)
                events = event_from_ret['events']
                initial = False

            end_time = time()

            if self._oneshot:
                break

            self.logger.debug("Waiting for XEN changes")

        #self._cancel_wait()

class Host(dict):
    def __init__(self):
        self.uuid = None
        self.vms = []

class VM(dict):
    def __init__(self):
        self.uuid = None

if __name__ == "__main__":
    #if len(sys.argv) <> 4:
        #print "Usage:"
        #print sys.argv[0], " <url> <username> <password>"
        #sys.exit(1)
    #url = sys.argv[1]
    #username = sys.argv[2]
    #password = sys.argv[3]
    #url = 'http://172.17.8.203:80'
    #username = "ggiardullo"
    #password = "wido-arsat02"

    # First acquire a valid session by logging in:
    from config import Config
    config = Config('xen', 'xen', url, username, password)
    xenserver = Xen(logger, config)
    from Queue import Queue
    from threading import Event, Thread
    q = Queue()

    class Printer(Thread):
        def run(self):
            while True:
                print q.get(True).association
    p = Printer()
    p.daemon = True
    p.start()
    try:
        xenserver.start_sync(q, Event())
    except KeyboardInterrupt:
        sys.exit(1)



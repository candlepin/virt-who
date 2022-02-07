import socket
import time as time_func

from . import ahv_constants
from .ahv_interface import AhvInterface, Failure
from time import time
from virtwho import virt
from virtwho.config import VirtConfigSection
from virtwho.virt import Hypervisor, Guest

DefaultUpdateInterval = 1800
MinimumUpdateInterval = 60
DefaultWaitTime = 900
MinWaitTime = 60

class Ahv(virt.Virt):
  "AHV Rest client"
  CONFIG_TYPE = "ahv"
  def __init__(self, logger, config, dest, interval=None,
                terminate_event=None, oneshot=False):
    """
    Args:
      logger (Logger): Framework logger.
      config (onfigSection): Virtwho configuration.
      dest (Datastore): Data store for destination.
      interval (Int): Wait interval for continuous run.
      terminate_event (Event): Event on termination.
      one_shot (bool): Flag to run virtwho as onetime or continuously.
    Returns:
      None.
    """
    super(Ahv, self).__init__(logger, config, dest,
                                  terminate_event=terminate_event,
                                  interval=interval,
                                  oneshot=oneshot)
    self.config = config
    self.version = ahv_constants.VERSION_2
    self.is_pc = False
    if 'prism_central' in self.config:
      if self.config['prism_central']:
        self.version = ahv_constants.VERSION_3
        self.is_pc = True

    self.port = ahv_constants.DEFAULT_PORT
    self.url = ahv_constants.SERVER_BASE_URIL % (self.config['server'],
                                                 self.port, self.version)
    self.port = ahv_constants.DEFAULT_PORT
    self.username = self.config['username']
    self.password = self.config['password']
    self.wait_time = self.config['wait_time_in_sec']
    self._interface = AhvInterface(logger, self.url, self.username,
                                   self.password, self.port,
                                   ahv_internal_debug=self.config['ahv_internal_debug'])

  def prepare(self):
    """
    Prepare for obtaining information from AHV server.
    Args:
      None
    Returns:
      None
    """
    self.logger.debug("Logging into Acropolis server %s" % self.url)
    self._interface.login(self.version)

  def _wait_for_update(self, timeout):
    """
    Wait for an update from AHV.
    Args:
      timeout (int): timeout
    Returns:
      task list (list): List of vm or host related tasks.
    """
    try:
      end_time = time() + timeout
      timestamp = int(time() * 1e6)
      while time() < end_time and not self.is_terminated():
        try:
          response = self._interface.get_tasks(timestamp, self.version,
                                               self.is_pc)
          if len(response) == 0:
            # No events, continue to wait
            self.logger.debug('wait for %s seconds before looking for '
                              'new events\n' % self.wait_time)
            time_func.sleep(self.wait_time)
            continue
          self.logger.debug('AHV event found: %s\n' % response)
          return response
        except Failure as e:
          if 'timeout' not in e.details:
            raise
    except Exception:
      self.logger.exception("Waiting on AHV events failed: ")

    return []

  def getHostGuestMapping(self):
    """
    Get a dict of host to uvm mapping.
    Args:
      None.
    Returns:
      None.
    """
    mapping = {'hypervisors': []}

    host_uvm_map = self._interface.build_host_to_uvm_map(self.version)
    if host_uvm_map:
      cluster_uuid_map = self._interface.get_ahv_cluster_uuid_map(self.version)

    for host_uuid in host_uvm_map:
      host = host_uvm_map[host_uuid]

      try:
        if self.config['hypervisor_id'] == 'uuid':
          hypervisor_id = host_uuid
        elif self.config['hypervisor_id'] == 'hostname':
          hypervisor_id = host['name']

      except KeyError:
        self.logger.debug("Host '%s' doesn't have hypervisor_id property",
                          host_uuid)
        continue

      guests = []
      if 'guest_list' in host and len(host['guest_list']) > 0:
        for guest_vm in host['guest_list']:
          try:
            state = guest_vm['power_state']
            if guest_vm['power_state'] == 'on':
              state = virt.Guest.STATE_RUNNING
            elif guest_vm['power_state'] == 'off':
              state = virt.Guest.STATE_SHUTOFF
            else:
              state = virt.Guest.STATE_UNKNOWN
          except KeyError:
            self.logger.warning("Guest %s is missing power state. Perhaps they"
                                " are powered off", guest_vm['uuid'])
            continue
          guests.append(Guest(guest_vm['uuid'], self.CONFIG_TYPE, state))
      else:
        self.logger.debug("Host '%s' doesn't have any vms", host_uuid)

      cluster_name = self._interface.get_host_cluster_name(host, cluster_uuid_map)
      host_version = self._interface.get_host_version(host)
      host_name = host['name']

      facts = {
        Hypervisor.CPU_SOCKET_FACT: str(host['num_cpu_sockets']),
        Hypervisor.HYPERVISOR_TYPE_FACT: host.get('hypervisor_type', 'AHV'),
        Hypervisor.HYPERVISOR_VERSION_FACT: str(host_version),
        Hypervisor.SYSTEM_UUID_FACT: str(host_uuid)}
      if cluster_name:
        facts[Hypervisor.HYPERVISOR_CLUSTER] = str(cluster_name)

      mapping['hypervisors'].append(virt.Hypervisor(hypervisorId=hypervisor_id,
                                                    guestIds=guests,
                                                    name=host_name,
                                                    facts=facts))
    return mapping

  def _run(self):
    """
    Continuous run loop for virt-who on AHV.
    Args:
      None.
    Returns:
      None.
    """
    self.prepare()
    next_update = time()
    initial = True
    wait_result = None
    while self._oneshot or not self.is_terminated():

      delta = next_update - time()

      if initial:
        assoc = self.getHostGuestMapping()
        self._send_data(virt.HostGuestAssociationReport(self.config, assoc))
        initial = False
        continue

      if delta > 0:
        # Wait for update.
        wait_result = self._wait_for_update(60 if initial else delta)
        if wait_result:
          events = wait_result
        else:
          events = []
      else:
        events = []

      if len(events) > 0 or delta > 0:
        assoc = self.getHostGuestMapping()
        self._send_data(virt.HostGuestAssociationReport(self.config, assoc))

      if self._oneshot:
        break
      else:
        next_update = time() + self.interval

class AhvConfigSection(VirtConfigSection):
  """Class for intializing and processing AHV config"""
  VIRT_TYPE = 'ahv'
  HYPERVISOR_ID = ('uuid', 'hostname')

  def __init__(self, *args, **kwargs):
    """
    Initialize AHV config and add config keys.
    Args:
       args: args
       kwargs : kwargs
     Returns:
       None.
    """
    super(AhvConfigSection, self).__init__(*args, **kwargs)
    self.add_key('server', validation_method=self._validate_server,
                 required=True)
    self.add_key('username', validation_method=self._validate_username,
                 required=True)
    self.add_key('password',
                 validation_method=self._validate_unencrypted_password,
                 required=True)
    self.add_key('is_hypervisor', validation_method=self._validate_str_to_bool,
                 default=True)
    self.add_key('prism_central', validation_method=self._validate_str_to_bool,
                 default=None)
    self.add_key('ahv_internal_debug', validation_method=self._validate_str_to_bool,
                 default=False)
    self.add_key(
            'wait_time_in_sec',
            validation_method=self._validate_wait_time,
            default=DefaultWaitTime)

  def _validate_server(self, key):
    """
    Validate the server IP address.
    Args:
      key (Str): server Ip address.
    Returns:
      Socket error is returned in case of an invalid ip.
    """
    error = super(AhvConfigSection, self)._validate_server(key)
    if error is None:
      try:
        ip = self._values[key]
        socket.inet_aton(ip)
      except socket.error:
        error = (
          'error',
          'Invalid server IP address provided'
        )

    return error

  def _validate_wait_time(self, key):
    """
    Validate the wait time  flag.
    Args:
      key (Int): wait time value.
    Returns:
      A warning is returned in case update time is not valid.
    """
    result = None
    try:
      self._values[key] = int(self._values[key])

      if self._values[key] < MinWaitTime:
        message = (
            "Wait time value can't be lower than {min} seconds. "
            "Default value of {default} "
            "seconds will be used.".format(min=MinWaitTime,
                                          default=DefaultWaitTime)
        )
        result = ("warning", message)
        self._values['interval'] = DefaultWaitTime
    except KeyError:
      result = ('warning', '%s is missing' % key)
    except (TypeError, ValueError) as e:
      result = ('warning', '%s was not set to a valid '
                'integer: %s' % (key, str(e)))
    return result

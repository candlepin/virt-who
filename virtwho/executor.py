# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import time
from threading import Event

from virtwho import log

from virtwho.config import DestinationToSourceMapper, VW_GLOBAL
from virtwho.datastore import Datastore
from virtwho.manager import Manager
from virtwho.virt import Virt, info_to_destination_class

try:
    from collections import OrderedDict
except ImportError:
    # Python 2.6 doesn't have OrderedDict, we need to have our own
    from .util import OrderedDict


class ReloadRequest(Exception):
    ''' Reload of virt-who was requested by sending SIGHUP signal. '''


class ExitRequest(Exception):
    """ Indicates that something that should cause virt-who to exit has occurred"""

    def __init__(self, code=0, message=""):
        self.code = code
        self.message = message


class Executor(object):
    def __init__(self, logger, options):
        """
        Executor class provides bridge between virtualization supervisor and
        Subscription Manager.

        logger - logger instance
        options - options for virt-who, parsed from command line arguments
        """
        self.logger = logger
        self.options = options
        self.terminate_event = Event()
        self.virts = []
        self.destinations = []

        # Queue for getting events from virt backends
        self.datastore = Datastore()
        self.reloading = False

        self.dest_to_source_mapper = DestinationToSourceMapper(options)

        for name, config in self.dest_to_source_mapper.configs:
            logger.info("Using config named '%s'" % name)

    def _create_virt_backends(self):
        """
        Create virts list with virt backend threads
        """
        virts = []
        for name, config in self.dest_to_source_mapper.configs:
            try:
                virt = Virt.from_config(self.logger, config, self.datastore,
                                        terminate_event=self.terminate_event,
                                        interval=self.options[VW_GLOBAL]['interval'],
                                        oneshot=self.options[VW_GLOBAL]['oneshot'])
            except Exception as e:
                self.logger.error('Unable to use configuration "%s": %s', name, str(e))
                continue
            virts.append(virt)
        return virts

    def _create_destinations(self):
        """Populate self.destinations with a list of  list with them

            @param reset: Whether to kill existing destinations or not, defaults
            to false
            @type: bool
        """
        dests = []
        for info in self.dest_to_source_mapper.dests:
            # Dests should already include all destinations we want created
            # at this time. This method will make no assumptions of creating
            # defaults of any kind.
            source_keys = self.dest_to_source_mapper.dest_to_sources_map[info]
            info.name = "destination_%s" % hash(info)
            logger = log.getLogger(name=info.name)
            manager = Manager.fromInfo(logger, self.options, info)
            dest_class = info_to_destination_class[type(info)]
            dest = dest_class(config=info, logger=logger,
                              source_keys=source_keys,
                              options=self.options,
                              source=self.datastore, dest=manager,
                              terminate_event=self.terminate_event,
                              interval=self.options[VW_GLOBAL]['interval'],
                              oneshot=self.options[VW_GLOBAL]['oneshot'])
            dests.append(dest)
        return dests

    @staticmethod
    def wait_on_threads(threads, max_wait_time=None, kill_on_timeout=False):
        """
        Wait for each of the threads in the list to be terminated
        @param threads: A list of IntervalThread objects to wait on
        @type threads: list

        @param max_wait_time: An optional max amount of seconds to wait
        @type max_wait_time: int

        @param kill_on_timeout: An optional arg that, if truthy and
        max_wait_time is defined and exceeded, cause this method to attempt
        to terminate and join the threads given it.
        @type kill_on_timeout: bool

        @return: A list of threads that have not quit yet. Without a
        max_wait_time this list is always empty (or we are stuck waiting).
        With a max_wait_time this list will include those threads that have
        not quit yet.
        @rtype: list
        """
        delta_time = 1.0
        total_waited = 0
        threads_not_terminated = list(threads)
        while len(threads_not_terminated) > 0:
            if max_wait_time is not None and total_waited > max_wait_time:
                if kill_on_timeout:
                    Executor.terminate_threads(threads_not_terminated)
                    return []
                return threads_not_terminated
            for thread in threads_not_terminated:
                if thread.is_terminated():
                    threads_not_terminated.remove(thread)
            if not threads_not_terminated:
                break
            time.sleep(delta_time)
            if max_wait_time is not None:
                total_waited += 1 * 1.0/delta_time
        return threads_not_terminated

    @staticmethod
    def terminate_threads(threads):
        for thread in threads:
            thread.stop()
            if thread.ident:
                thread.join()

    def run_oneshot(self):
        # Start all sources
        self.virts = self._create_virt_backends()

        if len(self.virts) == 0:
            err = "virt-who can't be started: no suitable virt backend found"
            self.logger.error(err)
            raise ExitRequest(code=1, message=err)

        self.destinations = self._create_destinations()

        if len(self.destinations) == 0:
            err = "virt-who can't be started: no suitable destinations found"
            self.logger.error(err)
            raise ExitRequest(code=1, message=err)

        for thread in self.virts:
            thread.start()

        Executor.wait_on_threads(self.virts)

        if self.options[VW_GLOBAL]['print']:
            to_print = {}
            for source in self.dest_to_source_mapper.sources:
                try:
                    report = self.datastore.get(source)
                    config = report.config
                    to_print[config.name] = report
                except KeyError:
                    self.logger.info('Unable to retrieve report for source '
                                     '\"%s\" for printing' % source)
            return to_print

        for thread in self.destinations:
            thread.start()

        Executor.wait_on_threads(self.destinations)

    def run(self):
        self.logger.debug("Starting infinite loop with %d seconds interval",
                          self.options[VW_GLOBAL]['interval'])

        # Need to update the dest to source mapping of the dest_to_source_mapper object
        # here because of the way that main reads the config from the command
        # line
        # TODO: Update dests to source map on addition or removal of configs
        self.dest_to_source_mapper.update_dest_to_source_map()
        # Start all sources
        self.virts = self._create_virt_backends()

        if len(self.virts) == 0:
            err = "virt-who can't be started: no suitable virt backend found"
            self.logger.error(err)
            raise ExitRequest(code=1, message=err)

        self.destinations = self._create_destinations()
        if len(self.destinations) == 0:
            err = "virt-who can't be started: no suitable destinations found"
            self.logger.error(err)
            raise ExitRequest(code=1, message=err)

        for thread in self.virts:
            thread.start()

        for thread in self.destinations:
            thread.start()

        # Interruptibly wait on the other threads to be terminated
        self.wait_on_threads(self.destinations)

        raise ExitRequest(code=0)

    def stop_threads(self):
        self.terminate_event.set()
        self.terminate_threads(self.virts)
        self.terminate_threads(self.destinations)

    def terminate(self):
        self.logger.debug("virt-who is shutting down")
        self.stop_threads()
        self.virts = []
        self.destinations = []
        self.datastore = None

    def reload(self):
        """
        Causes all threads to be terminated in preparation for running again
        """
        self.stop_threads()
        self.terminate_event.clear()
        self.datastore = Datastore()

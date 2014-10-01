"""
Module for communcating with libvirt, part of virt-who

Copyright (C) 2014 Radek Novacek <rnovacek@redhat.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import time
import logging
import libvirt
import threading
import urlparse

import virt


class VirEventLoopThread(threading.Thread):
    def __init__(self, logger, *args, **kwargs):
        self._terminated = threading.Event()
        threading.Thread.__init__(self, *args, **kwargs)

    def run(self):
        while not self._terminated.is_set():
            libvirt.virEventRunDefaultImpl()

    def terminate(self):
        self._terminated.set()


class LibvirtMonitor(object):
    """ Singleton class that performs background event monitoring. """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            print "Creating new instance of LibvirtMonitor"
            cls._instance = super(LibvirtMonitor, cls).__new__(cls, *args, **kwargs)
            cls._instance.logger = logging.getLogger("rhsm-app")
            cls._instance.event = None
            cls._instance.eventLoopThread = None
            cls._instance.domainIds = []
            cls._instance.definedDomains = []
            cls._instance.vc = None
        return cls._instance

    STATUS_NOT_STARTED, STATUS_RUNNING, STATUS_DISABLED = range(3)

    def _prepare(self):
        self.running = threading.Event()
        self.status = LibvirtMonitor.STATUS_NOT_STARTED

    def _loop_start(self):
        libvirt.virEventRegisterDefaultImpl()
        if self.eventLoopThread is not None and self.eventLoopThread.isAlive():
            self.eventLoopThread.terminate()
        self.eventLoopThread = VirEventLoopThread(self.logger, name="libvirtEventLoop")
        self.eventLoopThread.setDaemon(True)
        self.eventLoopThread.start()
        self._create_connection()

    def _create_connection(self):
        try:
            self.vc = libvirt.openReadOnly('')
        except libvirt.libvirtError, e:
            self.logger.warn("Unable to connect to libvirt: %s" % str(e))
            return
        try:
            self.vc.registerCloseCallback(self._close_callback, None)
        except AttributeError:
            self.logger.warn("Can't monitor libvirtd restarts due to bug in libvirt-python")
        self.vc.domainEventRegister(self._callback, None)
        self.vc.setKeepAlive(5, 3)

    def check(self):
        if self.eventLoopThread is None or not self.eventLoopThread.isAlive():
            self.logger.debug("Starting libvirt monitoring event loop")
            self._loop_start()
        if self.vc is None or not self.vc.isAlive():
            self.logger.debug("Reconnecting to libvirtd")
            self._create_connection()

    def _callback(self, *args, **kwargs):
        self.event.set()

    def _close_callback(self, conn, reason, opaque):
        reasonStrings = ("Error", "End-of-file", "Keepalive", "Client")
        self.logger.info("Connection to libvirtd lost: %s, reconnecting" % reasonStrings[reason])
        # it might be just a restart, give it some time to recover
        time.sleep(2)
        try:
            self.vc.close()
        except Exception, e:
            pass
        self.vc = None
        self.event.set()

    def set_event(self, event):
        self.event = event

    def isAlive(self):
        return self.eventLoopThread is not None and self.eventLoopThread.isAlive()


def libvirt_cred_request(credentials, config):
    """ Callback function for requesting credentials from libvirt """
    for credential in credentials:
        if credential[0] == libvirt.VIR_CRED_AUTHNAME:
            credential[4] = config.username
        elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
            credential[4] = config.password
        else:
            return -1
    return 0


class Libvirtd(virt.DirectVirt):
    """ Class for interacting with libvirt. """
    CONFIG_TYPE = "libvirt"

    def __init__(self, logger, config, registerEvents=True):
        self.changedCallback = None
        self.logger = logger
        self.config = config
        self.registerEvents = registerEvents
        libvirt.registerErrorHandler(lambda ctx, error: None, None)

    def _get_url(self):
        if self.config.server:
            scheme = username = netloc = path = None
            url = self.config.server
            if "//" not in url:
                url = "//" + url
            splitted_url = urlparse.urlsplit(url)

            netloc = splitted_url.netloc

            if splitted_url.scheme:
                scheme = splitted_url.scheme
            else:
                self.logger.info("Protocol is not specified in libvirt url, using qemu+ssh://")
                scheme = 'qemu+ssh'

            if self.config.username:
                username = self.config.username
            elif splitted_url.username:
                username = splitted_url.username

            if len(splitted_url.path) > 1:
                path = splitted_url.path
            else:
                self.logger.info("Libvirt path is not specified in the url, using /system")
                path = '/system'

            return "%(scheme)s://%(username)s%(netloc)s%(path)s?no_tty=1" % {
                'username': ("%s@" % username) if username else '',
                'scheme': scheme,
                'netloc': netloc,
                'path': path
            }
        return ''

    def _connect(self):
        url = self._get_url()
        self.logger.info("Using libvirt url: %s", url if url else '""')
        monitor = LibvirtMonitor()
        try:
            if self.config.password:
                auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE], libvirt_cred_request, self.config]
                self.virt = libvirt.openAuth(url, auth, libvirt.VIR_CONNECT_RO)
            else:
                self.virt = libvirt.openReadOnly(url)
        except libvirt.libvirtError, e:
            self.logger.exception("Error in libvirt backend")
            raise virt.VirtError(str(e))

    def listDomains(self):
        """ Get list of all domains. """
        domains = []
        self._connect()

        try:
            # Active domains
            for domainID in self.virt.listDomainsID():
                domain = self.virt.lookupByID(domainID)
                if domain.UUIDString() == "00000000-0000-0000-0000-000000000000":
                    # Don't send Domain-0 on xen (zeroed uuid)
                    continue
                domains.append(virt.Domain(self.virt, domain))
                self.logger.debug("Virtual machine found: %s: %s" % (domain.name(), domain.UUIDString()))

            # Non active domains
            for domainName in self.virt.listDefinedDomains():
                domain = self.virt.lookupByName(domainName)
                domains.append(virt.Domain(self.virt, domain))
                self.logger.debug("Virtual machine found: %s: %s" % (domainName, domain.UUIDString()))
        except libvirt.libvirtError, e:
            self.virt.close()
            raise virt.VirtError(str(e))
        self.virt.close()
        return domains

    def canMonitor(self):
        return True

    def startMonitoring(self, event):
        monitor = LibvirtMonitor()
        monitor.set_event(event)
        monitor.check()


def eventToString(event):
    eventStrings = ("Defined", "Undefined", "Started", "Suspended", "Resumed",
                    "Stopped", "Shutdown")
    try:
        return eventStrings[event]
    except IndexError:
        return "Unknown (%d)" % event


def detailToString(event, detail):
    eventStrings = (
        ("Added", "Updated"), # Defined
        ("Removed", ), # Undefined
        ("Booted", "Migrated", "Restored", "Snapshot", "Wakeup"), # Started
        ("Paused", "Migrated", "IOError", "Watchdog", "Restored", "Snapshot"), # Suspended
        ("Unpaused", "Migrated", "Snapshot"), # Resumed
        ("Shutdown", "Destroyed", "Crashed", "Migrated", "Saved", "Failed", "Snapshot"), # Stopped
        ("Finished",), # Shutdown
    )
    try:
        return eventStrings[event][detail]
    except IndexError:
        return "Unknown (%d)" % detail

"""
Test for Satellite module, part of virt-who

Copyright (C) 2013 Radek Novacek <rnovacek@redhat.com>

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
import os
import sys

from base import unittest

import logging
import threading
import tempfile
import pickle
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler

from manager.satellite import Satellite, SatelliteError

TEST_SYSTEM_ID = 'test-system-id'


class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/XMLRPC',)


class FakeSatellite(SimpleXMLRPCServer):
    def __init__(self):
        SimpleXMLRPCServer.__init__(self, ("localhost", 8080), requestHandler=RequestHandler)
        self.register_function(self.new_system_user_pass, "registration.new_system_user_pass")
        self.register_function(self.refresh_hw_profile, "registration.refresh_hw_profile")
        self.register_function(self.virt_notify, "registration.virt_notify")

    def new_system_user_pass(self, profile_name, os_release_name, version, arch, username, password, options):
        if username != "username":
            raise Exception("Wrong username")
        if password != "password":
            raise Exception("Wrong password")
        print "RPC: new_system_user_pass", profile_name, os_release_name, version, arch, username, password, options
        return {'system_id': TEST_SYSTEM_ID}

    def refresh_hw_profile(self, system_id, profile):
        print "RPC: refresh_hw_profile", system_id, profile
        if system_id != TEST_SYSTEM_ID:
            raise Exception("Wrong system id")
        return ""

    def virt_notify(self, system_id, plan):
        print "RPC: virt_notify", system_id, plan
        if system_id != TEST_SYSTEM_ID:
            raise Exception("Wrong system id")

        if plan[0] != [0, 'exists', 'system', {'uuid': '0000000000000000', 'identity': 'host'}]:
            raise Exception("Wrong value for virt_notify: invalid format of first entry")
        if plan[1] != [0, 'crawl_began', 'system', {}]:
            raise Exception("Wrong value for virt_notify: invalid format of second entry")
        if plan[-1] != [0, 'crawl_ended', 'system', {}]:
            raise Exception("Wrong value for virt_notify: invalid format of last entry")
        for item in plan[2:-1]:
            if item[0] != 0:
                raise Exception("Wrong value for virt_notify: invalid format first item of an entry")
            if item[1] != 'exists':
                raise Exception("Wrong value for virt_notify: invalid format second item of an entry")
            if item[2] != 'domain':
                raise Exception("Wrong value for virt_notify: invalid format third item of an entry")
            if not item[3]['uuid'].startswith("guest"):
                raise Exception("Wrong value for virt_notify: invalid format uuid item")
        return 0


class Options(object):
    def __init__(self, server, username, password):
        self.server = server
        self.username = username
        self.password = password


class TestSatellite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logger = logging.getLogger()
        cls.fake_server = FakeSatellite()
        cls.thread = threading.Thread(target=cls.fake_server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.fake_server.shutdown()

    def test_wrong_server(self):
        options = Options("wrong_server", "abc", "def")
        s = Satellite(self.logger, options)
        #self.assertRaises(SatelliteError, s.connect, "wrong_server", "abc", "def")
        s.hypervisorCheckIn("owner", "env", {}, "test")
        #self.assertRaises(SatelliteError, s.connect, "localhost", "abc", "def")

    def test_new_system(self):
        options = Options("http://localhost:8080", "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)

        # Register with wrong username
        #self.assertRaises(SatelliteError, s.connect, "http://localhost:8080", "wrong", "password", force_register=True)

        # Register with wrong password
        #self.assertRaises(SatelliteError, s.connect, "http://localhost:8080", "username", "wrong", force_register=True)

    def test_hypervisorCheckIn(self):
        options = Options("http://localhost:8080", "username", "password")
        options.force_register = True
        s = Satellite(self.logger, options)

        mapping = {
            'host-1': ['guest1-1', 'guest1-2'],
            'host-2': ['guest2-1', 'guest2-2', 'guest2-3']
        }
        result = s.hypervisorCheckIn("owner", "env", mapping, "type")
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)

    def test_hypervisorCheckIn_preregistered(self):
        temp, filename = tempfile.mkstemp(suffix=TEST_SYSTEM_ID)
        self.addCleanup(os.unlink, filename)
        f = os.fdopen(temp, "wb")
        pickle.dump({'system_id': TEST_SYSTEM_ID}, f)
        f.close()

        options = Options("http://localhost:8080", "username", "password")
        s = Satellite(self.logger, options)

        s.HYPERVISOR_SYSTEMID_FILE = filename.replace(TEST_SYSTEM_ID, '%s')
        mapping = {
            'host-1': ['guest1-1', 'guest1-2'],
            'host-2': ['guest2-1', 'guest2-2', 'guest2-3']
        }
        result = s.hypervisorCheckIn("owner", "env", mapping, "type")
        self.assertTrue("failedUpdate" in result)
        self.assertTrue("created" in result)
        self.assertTrue("updated" in result)


if __name__ == '__main__':
    unittest.main()

"""
Testing module, part of virt-who

Copyright (C) 2011 Radek Novacek <rnovacek@redhat.com>

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

import unittest
import logging
import subprocess
import os

from virt import Virt
from subscriptionmanager import SubscriptionManager

logger = logging.Logger("virt-who")

class VirtTest(unittest.TestCase):
    def setUp(self):
        self.virt = Virt(logger)

    def test_connection(self):
        self.assertTrue(self.virt.virt.getVersion() > 0)

    def test_listDomains(self):
        uuids = []
        for domain in self.virt.listDomains():
            uuids.append(domain.UUIDString())
        virsh_list = subprocess.Popen(["virsh", "-r", "list", "--all"], stdout=subprocess.PIPE).communicate()[0]
        lines = virsh_list.split("\n")[2:]
        for line in lines:
            if len(line) == 0:
                continue
            domId = line.split()[1]
            uuid = subprocess.Popen(["virsh", "-r", "domuuid", domId], stdout=subprocess.PIPE).communicate()[0].strip()
            self.assertTrue(uuid in uuids, "virsh returns more domains then virt-who (%s)" % uuid)
            uuids.remove(uuid)
        self.assertEqual(len(uuids), 0, "virsh returns less domains then virt-who (%s)" % ",".join(uuids))

class SubscriptionManagerTest(unittest.TestCase):
    def setUp(self):
        self.sm = SubscriptionManager(logger)

    def test_connect(self):
        self.sm.connect()
        self.assertNotEqual(self.sm.connection.ping()['result'], "")

    def test_config(self):
        self.sm.readConfig()
        consumerCertDir = None

        f = open("/etc/rhsm/rhsm.conf", "r")
        cfg = f.read()
        for line in cfg.split("\n"):
            line = line.strip()
            if line.startswith("consumerCertDir"):
                consumerCertDir = line.partition("=")[2].strip()
        self.assertTrue(consumerCertDir is not None)
        self.assertEqual(self.sm.cert_file, os.path.join(consumerCertDir, "cert.pem"))
        self.assertEqual(self.sm.key_file, os.path.join(consumerCertDir, "key.pem"))

    def test_uuid(self):
        uuid = None
        for line in subprocess.Popen(["subscription-manager", "identity"], stdout=subprocess.PIPE).communicate()[0].split("\n"):
            if line.startswith("Current identity is:"):
                uuid = line.partition(":")[2].strip()
        self.assertEqual(uuid, self.sm.uuid())

if __name__ == '__main__':
    unittest.main()

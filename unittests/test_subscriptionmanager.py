
import os
import sys
import unittest
import tempfile

sys.path.append("..")
from subscriptionmanager import *

class FakeLogger(object):
    def error(self, *p):
        pass
    def debug(self, *p):
        pass
    def exception(self, *p):
        pass
    def warning(self, *p):
        pass

class SubscriptionManagerX(SubscriptionManager):
    def __init__(self, logger):
        self.cert_uuid = None
        self.logger = logger
        self.config = FakeConfig()

class FakeConfig(object):
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp()

    def createCert(self):
        self.cert_file = os.path.join(self.tmpdir, "cert.pem")
        with open(self.cert_file, "w") as f:
            f.write("CERT")

    def createKey(self):
        with open(os.path.join(self.tmpdir, "key.pem"), "w") as f:
            f.write("KEY")

    def __del__(self):
        try:
            os.rmdir(self.tmpdir)
        except Exception:
            pass

    def get(self, group, name):
        if group == 'rhsm' and name == 'consumerCertDir':
            return self.tmpdir

class FakeConnection(object):
    def __init__(self, cert_file, key_file):
        self.cert_file = cert_file
        self.key_file = key_file

    def ping(self):
        return { 'result': 'OK' }

class Test_SubscriptionManager(unittest.TestCase):
    def setUp(self):
        self.logger = FakeLogger()

    def test_readConfig(self):
        self.sm = SubscriptionManagerX(self.logger)
        self.assertRaises(SubscriptionManagerCertError, self.sm.readConfig)

        self.sm.config.createCert()
        self.sm.readConfig()

    def test_connect(self):
        self.sm = SubscriptionManagerX(self.logger)
        self.sm.config.createCert()
        self.sm.readConfig()
        self.sm.connect(FakeConnection)
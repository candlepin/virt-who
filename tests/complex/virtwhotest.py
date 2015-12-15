
import sys
import os
import signal
import socket
from multiprocessing import Process, Manager, Value
import subprocess

# hack to use unittest2 on python <= 2.6, unittest otherwise
# based on python version
if sys.version_info[0] > 2 or sys.version_info[1] > 6:
    from unittest import TestCase
else:
    from unittest2 import TestCase

import random
import json
from StringIO import StringIO
import time
from tempfile import TemporaryFile

from fake_sam import FakeSam

try:
    import virtwho
    import config
except ImportError:
    sys.path.append("/usr/share/virt-who/")
    import virtwho
    import config

config.VIRTWHO_CONF_DIR = '/this/does/not/exist'
virtwho.VIRTWHO_GENERAL_CONF_PATH = '/this/does/not/exist.conf'


class FakeVirt(Process):
    def __init__(self):
        super(FakeVirt, self).__init__()
        self.daemon = True
        self._port = None
        self._data_version = Value('d', 0)

    @property
    def port(self):
        if self._port is None:
            self._port = random.randint(8000, 9000)
        return self._port

    def clear_port(self):
        print "Clear port: ", self._port
        self._port = None

    @property
    def username(self):
        return 'A!bc\n 3#\'"'

    @property
    def password(self):
        return 'A!bc\n 3#\'"'

    def run(self):
        raise NotImplementedError()

    @property
    def data_version(self):
        return self._data_version.value

    @data_version.setter
    def data_version(self, version):
        self._data_version.value = version


class TestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        TestCase.setUpClass()
        cls.manager = Manager()
        cls.assoc = cls.manager.dict()
        cls.sam = FakeSam(cls.assoc)
        cls.sam.start()

    @classmethod
    def tearDownClass(cls):
        cls.manager.shutdown()
        cls.manager.join()
        cls.sam.terminate()
        cls.sam.join()
        TestCase.tearDownClass()

    def setUp(self):
        self.assoc.clear()
        self.server.data_version = 0

    def run_virtwho(self, args, grab_stdout=False, background=False):
        '''
        Execute virt-who process with given arguments.

        `grab_stdout` argument will take stdout of the virt-who process
        and will return it as second part of the tuple.

        If `background` is set to True, virt-who will be started on background
        and this method will return immediately.

        Returns tuple (status, stdout), where status is return code of the
        virt-who process (or None if `background` is True) and stdout is
        stdout from the process (or None if `grab_stdout` is False).
        '''
        oldMinimumSendInterval = virtwho.MinimumSendInterval
        virtwho.MinimumSendInterval = 2
        virtwho.log.Logger._stream_handler = None
        virtwho.log.Logger._queue_logger = None
        if grab_stdout:
            old_stdout = sys.stdout
            sys.stdout = TemporaryFile()
        sys.argv = ["virt-who"] + args
        code = None
        data = None
        socket.setdefaulttimeout(1)
        self.process = Process(target=virtwho.main)
        self.process.start()

        if not background:
            self.process.join()
            code = self.process.exitcode

        if grab_stdout:
            sys.stdout.seek(0)
            data = sys.stdout.read()
            sys.stdout.close()
            sys.stdout = old_stdout

        virtwho.MinimumSendInterval = oldMinimumSendInterval
        return (code, data)

    def stop_virtwho(self):
        self.process.terminate()
        self.process.join()


class VirtBackendTestMixin(object):
    """
    This is a mixin that provides tests for virt backend. The fake backend
    must provide exactly the expected data.

    Mix this class into the specific virt backend TestCase.
    """

    def __init__(self):
        raise NotImplementedError()

    def check_assoc(self, reported, expected):
        diff = set(reported.keys()) - set(expected.keys())
        self.assertEqual(len(diff), 0, "Hosts %s reported but not expected" % ",".join(diff))
        diff = set(expected.keys()) - set(reported.keys())
        self.assertEqual(len(diff), 0, "Hosts %s expected but not reported" % ",".join(diff))
        for host, excepted_guests in expected.items():
            reported_guests = reported[host]
            expected_guests_uuids = [guest['guestId'] for guest in excepted_guests]
            reported_guests_uuids = [guest['guestId'] for guest in reported_guests]
            diff = set(reported_guests_uuids) - set(expected_guests_uuids)
            self.assertEqual(len(diff), 0, "Guests %s on host %s reported but not expected" % (",".join(diff), host))
            diff = set(expected_guests_uuids) - set(reported_guests_uuids)
            self.assertEqual(len(diff), 0, "Guests %s on host %s expected but not reported" % (",".join(diff), host))
            for excepted_guest in excepted_guests:
                reported_guest = [guest for guest in reported_guests if guest['guestId'] == excepted_guest['guestId']][0]
                self.assertEqual(excepted_guest, reported_guest, "Guest attributes differs")

    def check_assoc_initial(self, assoc):
        self.check_assoc(assoc, {
            'a2c85a15-9b53-493d-9731-8b5cccdd8951': [],
            '4172853d-e72a-493a-883b-8761f5daa5eb': [],
            '5627a268-f036-4f5d-b9a3-0183ec736913': [
                {
                    'guestId': '9844af5d-101b-40ea-a125-8bf1a02f888b',
                    'attributes': {
                        'active': 1,
                        'hypervisorVersion': '',
                        'virtWhoType': self.virt,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }, {
                    'guestId': '640bb2fe-fa3b-48cb-89d0-193c13b15663',
                    'attributes': {
                        'active': 1,
                        'hypervisorVersion': '',
                        'virtWhoType': self.virt,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }, {
                    'guestId': 'c0667b9d-64e1-480c-8b82-c1b1c06614e7',
                    'attributes': {
                        'active': 1,
                        'hypervisorVersion': '',
                        'virtWhoType': self.virt,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }
            ]
        })

    def check_assoc_updated(self, assoc):
        self.check_assoc(assoc, {
            'a2c85a15-9b53-493d-9731-8b5cccdd8951': [
            ],
            '4172853d-e72a-493a-883b-8761f5daa5eb': [
                {
                    'guestId': '9844af5d-101b-40ea-a125-8bf1a02f888b',
                    'attributes': {
                        'active': 1,
                        'hypervisorVersion': '',
                        'virtWhoType': self.virt,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }
            ],
            '5627a268-f036-4f5d-b9a3-0183ec736913': [
                {
                    'guestId': '640bb2fe-fa3b-48cb-89d0-193c13b15663',
                    'attributes': {
                        'active': 1,
                        'hypervisorVersion': '',
                        'virtWhoType': self.virt,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }, {
                    'guestId': 'c0667b9d-64e1-480c-8b82-c1b1c06614e7',
                    'attributes': {
                        'active': 0,
                        'hypervisorVersion': '',
                        'virtWhoType': self.virt,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 5
                }
            ]
        })

    def wait_for_assoc(self, timeout=3):
        for _ in range(timeout):
            if self.assoc:
                break
            time.sleep(1)
        else:
            raise AssertionError("Association was not obtained in %d seconds" % timeout)

    def test_basic(self):
        code, _ = self.run_virtwho(self.arguments + ['-o', '--debug'])
        self.assertEqual(code, 0, "virt-who exited with wrong error code: %s" % code)
        self.check_assoc_initial(dict(self.assoc))

    def test_print(self):
        code, out = self.run_virtwho(self.arguments + ['-p', '--debug'], grab_stdout=True)
        self.assertEqual(code, 0, "virt-who exited with wrong error code: %s" % code)
        returned = json.loads(out)
        # Transform it to the same format as assoc from SAM server
        assoc = dict((host['uuid'], host['guests']) for host in returned['hypervisors'])
        self.check_assoc(assoc, {
            'a2c85a15-9b53-493d-9731-8b5cccdd8951': [],
            '4172853d-e72a-493a-883b-8761f5daa5eb': [],
            '5627a268-f036-4f5d-b9a3-0183ec736913': [
                {
                    'guestId': '9844af5d-101b-40ea-a125-8bf1a02f888b',
                    'attributes': {
                        'virtWhoType': self.virt,
                        'hypervisorVersion': '',
                        'active': 1,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }, {
                    'guestId': '640bb2fe-fa3b-48cb-89d0-193c13b15663',
                    'attributes': {
                        'virtWhoType': self.virt,
                        'hypervisorVersion': '',
                        'active': 1,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }, {
                    'guestId': 'c0667b9d-64e1-480c-8b82-c1b1c06614e7',
                    'attributes': {
                        'virtWhoType': self.virt,
                        'hypervisorVersion': '',
                        'active': 1,
                        'hypervisorType': self.hypervisorType
                    },
                    'state': 1
                }
            ]
        })

    def test_normal(self):
        self.run_virtwho(['-i', '2', '-d'] + self.arguments, background=True)
        self.addCleanup(self.stop_virtwho)

        self.wait_for_assoc()
        self.check_assoc_initial(dict(self.assoc))

        self.server.data_version = 1
        self.assoc.clear()

        self.wait_for_assoc(5)
        self.check_assoc_updated(dict(self.assoc))

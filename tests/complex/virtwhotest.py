from __future__ import print_function

import os
import signal
import sys
import socket
from six.moves.queue import Empty
from shutil import rmtree
from multiprocessing import Process, Queue
from mock import patch

import json
from tempfile import TemporaryFile, mkdtemp

from fake_sam import FakeSam

import virtwho
import virtwho.parser
import virtwho.main
import virtwho.log

# hack to use unittest2 on python <= 2.6, unittest otherwise
# based on python version
if sys.version_info[0] > 2 or sys.version_info[1] > 6:
    from unittest import TestCase
else:
    from unittest2 import TestCase


class TestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        TestCase.setUpClass()
        virtwho.config.VW_CONF_DIR = '/this/does/not/exist'
        virtwho.config.VW_GENERAL_CONF_PATH = '/this/does/not/exist.conf'
        cls.queue = Queue()
        cls.sam = FakeSam(cls.queue)
        cls.sam.start()

    @classmethod
    def tearDownClass(cls):
        cls.sam.terminate()
        cls.sam.join()
        TestCase.tearDownClass()

    def setUp(self):
        # Clear the queue
        while True:
            try:
                self.queue.get(block=False)
            except Empty:
                break
        self.server.data_version = 0

        # Logger patching
        self.tmp_dir = mkdtemp()
        logger_patcher = patch.multiple('virtwho.log.Logger', _log_dir=self.tmp_dir,
                                         _stream_handler=None, _queue_logger=None)
        logger_patcher.start()
        self.addCleanup(logger_patcher.stop)
        self.addCleanup(rmtree, self.tmp_dir)

        log_patcher = patch.multiple('virtwho.log', DEFAULT_LOG_DIR=self.tmp_dir)
        log_patcher.start()
        self.addCleanup(log_patcher.stop)

        rhsm_log_patcher = patch('rhsm.connection.log')
        rhsm_log_patcher.start()
        self.addCleanup(rhsm_log_patcher.stop)

        # Reduce minimum send interval to allow for faster test completion
        minimum_patcher = patch('virtwho.config.MinimumSendInterval', 2)
        minimum_patcher.start()
        self.addCleanup(minimum_patcher.stop)

        # Mock PIDFILE (so we can run tests as an unprivledged user)
        pid_file_name = self.tmp_dir + 'virt-who.pid'
        pid_file_patcher = patch('virtwho.main.PIDFILE', pid_file_name)
        pid_file_patcher.start()
        self.addCleanup(pid_file_patcher.stop)

    def tearDown(self):
        self.process.terminate()
        self.process.join()

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

        old_stdout = None
        if grab_stdout:
            old_stdout = sys.stdout
            sys.stdout = TemporaryFile(mode='w+')
        sys.argv = ["virt-who"] + args
        code = None
        data = None
        socket.setdefaulttimeout(1)
        self.process = Process(target=virtwho.main.main)
        self.process.start()

        if not background:
            self.process.join()
            code = self.process.exitcode

        if grab_stdout:
            sys.stdout.seek(0)
            data = sys.stdout.read()
            sys.stdout.close()
            sys.stdout = old_stdout

        return code, data

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
        for host, excepted_guests in list(expected.items()):
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
                        'virtWhoType': self.virt,
                    },
                    'state': 1
                }, {
                    'guestId': '640bb2fe-fa3b-48cb-89d0-193c13b15663',
                    'attributes': {
                        'active': 1,
                        'virtWhoType': self.virt,
                    },
                    'state': 1
                }, {
                    'guestId': 'c0667b9d-64e1-480c-8b82-c1b1c06614e7',
                    'attributes': {
                        'active': 1,
                        'virtWhoType': self.virt,
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
                        'virtWhoType': self.virt,
                    },
                    'state': 1
                }
            ],
            '5627a268-f036-4f5d-b9a3-0183ec736913': [
                {
                    'guestId': '640bb2fe-fa3b-48cb-89d0-193c13b15663',
                    'attributes': {
                        'active': 1,
                        'virtWhoType': self.virt,
                    },
                    'state': 1
                }, {
                    'guestId': 'c0667b9d-64e1-480c-8b82-c1b1c06614e7',
                    'attributes': {
                        'active': 0,
                        'virtWhoType': self.virt,
                    },
                    'state': 5
                }
            ]
        })

    def wait_for_assoc(self, timeout=4):
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            raise AssertionError("Association was not obtained in %d seconds" % timeout)

    def test_basic(self):
        code, _ = self.run_virtwho(self.arguments + ['-o', '--debug'])
        self.assertEqual(code, 0, "virt-who exited with wrong error code: %s" % code)
        assoc = self.wait_for_assoc()
        self.check_assoc_initial(assoc)

    def test_print(self):
        code, out = self.run_virtwho(self.arguments + ['-p', '--debug'], grab_stdout=True)
        self.assertEqual(code, 0, "virt-who exited with wrong error code: %s" % code)
        returned = json.loads(out)
        # Test facts
        for hypervisor in returned['hypervisors']:
            if hypervisor['facts']['hypervisor.type'] == 'vmware':
                self.assertTrue(hypervisor['facts']['hypervisor.cluster'].startswith('ha-cluster-1'))
            else:
                self.assertTrue(hypervisor['facts']['hypervisor.cluster'].startswith('ha-compute-res'))
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
                        'active': 1,
                    },
                    'state': 1
                }, {
                    'guestId': '640bb2fe-fa3b-48cb-89d0-193c13b15663',
                    'attributes': {
                        'virtWhoType': self.virt,
                        'active': 1,
                    },
                    'state': 1
                }, {
                    'guestId': 'c0667b9d-64e1-480c-8b82-c1b1c06614e7',
                    'attributes': {
                        'virtWhoType': self.virt,
                        'active': 1,
                    },
                    'state': 1
                }
            ]
        })

    def test_normal(self):
        self.run_virtwho(['-i', '2', '-d'] + self.arguments, background=True)
        self.addCleanup(self.stop_virtwho)

        assoc = self.wait_for_assoc()
        self.check_assoc_initial(assoc)

        self.server.data_version = 1

        assoc = self.wait_for_assoc(5)
        self.check_assoc_updated(assoc)

    def test_exit_on_SIGTERM(self):
        """
        This test shows that virt-who exits cleanly in response to the
        SIGTERM signal
        """
        self.run_virtwho(['-i', '2', '-d'] + self.arguments, background=True)
        self.addCleanup(self.stop_virtwho)
        self.assertEqual(self.process.is_alive(), True)
        os.kill(self.process.pid, signal.SIGTERM)
        self.process.join(timeout=3)
        self.assertEqual(self.process.is_alive(), False)

    def test_reload_on_SIGHUP(self):
        """
        This tests that the rhsm.conf is read once again when the process
        receives the reload signal
        """
        rhsm_conf_path = os.path.join(self.sam.tempdir, 'rhsm.conf')
        good_rhsm_conf = ''
        with open(rhsm_conf_path, 'r') as f:
            good_rhsm_conf = ''.join(line for line in f.readlines())
        bad_conf = """
[server]
hostname = BADHOSTNAME
prefix = /nogood
port = {port}1337
insecure = 1
proxy_hostname =
""".format(port=self.sam.port)
        with open(os.path.join(self.sam.tempdir, 'rhsm.conf'), 'w') as \
                rhsm_conf_file:
            rhsm_conf_file.write(bad_conf)
            rhsm_conf_file.flush()
        self.run_virtwho(['-i', '2', '-d'] + self.arguments, background=True)
        self.addCleanup(self.stop_virtwho)
        self.assertEqual(self.process.is_alive(), True)

        # We expect the queue to be empty until we the appropriate
        # configuration file is added
        self.assertRaises(AssertionError, self.wait_for_assoc)

        # Update the configuration file with the good one that came from
        # fake_sam
        with open(os.path.join(self.sam.tempdir, 'rhsm.conf'), 'w') as \
                rhsm_conf_file:
            rhsm_conf_file.write(good_rhsm_conf)
        os.kill(self.process.pid, signal.SIGHUP)
        self.wait_for_assoc(4)
        self.assertEqual(self.process.is_alive(), True)

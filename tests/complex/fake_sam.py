from __future__ import print_function

#
# Module for abstraction of all virtualization backends, part of virt-who
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import os
import six
import sys
import tempfile
import ssl
import json
import shutil
import requests

from fake_server import FakeServer, FakeHandler

from rhsm import config as rhsm_config


class SamHandler(FakeHandler):
    """
    Handler of GET, POST and PUT method for FakeSam (candlepin server)
    """

    def do_GET(self):
        """
        Handler for GET method
        :return:
        """
        print("[FakeSam] GET", self.path)
        if self.path.startswith('/status'):
            content = {
                "result": "ok",
                "managerCapabilities": [""]
            }
            self.write_json(content)
        else:
            content = {"result": "ok"}
            self.write_json(content)

    def do_POST(self):
        """
        Handler for POST method
        """
        print("[FakeSam] POST", self.path, self.server.code)
        if self.server.code:
            self.write_json({}, status_code=self.server.code, headers={"Retry-After": "60"})
        elif self.path.startswith('/hypervisors') or self.path.startswith('//hypervisors'):
            size = int(self.headers["Content-Length"])
            incoming = self.rfile.read(size)
            if isinstance(incoming, six.binary_type):
                incoming = incoming.decode('utf-8')
            data = json.loads(incoming)
            print("[FakeSam] putting in the queue:", data)
            self.server.queue.put(data)
            content = {
                "failedUpdate": [],
                "updated": [],
                "created": [],
            }
            self.write_json(content, status_code=requests.codes.ok)

    def do_PUT(self):
        """
        Handler for PUT method. This method is just ignored
        :return:
        """
        print("[FakeSam] PUT", self.path)


class FakeSam(FakeServer):
    """
    Fake candlepin server used for testing of virt-who
    """
    def __init__(self, queue, port=None, code=None, host='localhost'):
        """
        Initialization of fake candlepin server
        :param queue: inter-process queue used for testing
        :param port: port, where server is listening on
        :param code: (optional) the code that server returns to client
        :param host: the name that is used for host
        """
        super(FakeSam, self).__init__(SamHandler, port=port, host=host)
        self.server.code = code
        base = os.path.dirname(os.path.abspath(__file__))
        certfile = os.path.join(base, 'cert.pem')
        keyfile = os.path.join(base, 'key.pem')
        if not os.access(certfile, os.R_OK):
            raise OSError("No such file %s" % certfile)
        if not os.access(keyfile, os.R_OK):
            raise OSError("No such file %s" % keyfile)
        self.server.socket = ssl.wrap_socket(self.server.socket, certfile=certfile, keyfile=keyfile, server_side=True)

        self.tempdir = tempfile.mkdtemp()
        config_name = os.path.join(self.tempdir, 'rhsm.conf')
        with open(config_name, 'w') as f:
            f.write("""
[server]
hostname = {host}
prefix = /
port = {port}
insecure = 1
proxy_hostname =

[rhsm]
consumerCertDir = {certdir}
""".format(host=self.host, port=self.port, certdir=base))

        rhsm_config.DEFAULT_CONFIG_PATH = config_name

        self.server.sam = self
        self.server.queue = queue

    def terminate(self):
        shutil.rmtree(self.tempdir)
        super(FakeSam, self).terminate()


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        code = int(sys.argv[1])
    else:
        code = None
    from six.moves.queue import Queue
    q = Queue()
    f = FakeSam(q, port=8443, code=code, host='0.0.0.0')
    f.run()

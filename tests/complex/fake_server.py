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
from multiprocessing import Process
from six.moves.SimpleHTTPServer import SimpleHTTPRequestHandler
import random
from six.moves import socketserver
import requests
import json


class FakeTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class FakeHandler(SimpleHTTPRequestHandler):
    """
    Base class of handler for:
    - Fake virt backends like RHEVM or ESX
    - Fake candlepin server (FakeSam)
    """
    def write_file(self, directory, filename):
        """
        Send file with given `filename` to the client. File must be in
        `directory` in the data/ subdirectory of the directory
        where the current __file__ is.
        """
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'data', directory, filename)

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-length", os.stat(path).st_size)
        self.end_headers()
        with open(path, "rb") as f:
            self.wfile.write(f.read())

    def write_json(self, content, status_code=requests.codes.ok, headers=None):
        """
        Send back as json the content parameter (Most useful to input a dict).
        Sets the following headers if not provided (other wise they are added to the input headers)
          "Content-type" : "application/json"
          "Content-length" : len(json.dumps(content).encode('utf-8'))
        :param content: The object to convert to json and send as the body of the message
        :type content: dict

        :param status_code: The HTTP Status code to set on the response
        :type status_code: int

        :param headers: A dict of header_name : header_value.
        :type headers: dict
        :return: Nothing
        :rtype: None
        """

        if headers is None:
            headers = {}
        if "Content-type" not in headers:
            headers["Content-type"] = "application/json"

        content = json.dumps(content).encode('utf-8')
        if "Content-length" not in headers:
            headers["Content-length"] = len(content)

        self.send_response(status_code)
        for header, value in headers.items():
            self.send_header(header, value)
        self.end_headers()
        self.wfile.write(content)


class FakeServer(Process):
    """
    Base class for fake servers like:
    - Fake virt backends like RHEVM or ESX
    - Fake candlepin server
    """

    def __init__(self, handler_class, host='localhost', port=None):
        super(FakeServer, self).__init__()
        self._port = port
        self.host = host
        self.server = FakeTCPServer((self.host, self.port), handler_class)

    @property
    def port(self):
        if self._port is None:
            self._port = random.randint(8000, 9000)
        return self._port

    def clear_port(self):
        print("Clear port: ", self._port)
        self._port = None

    def run(self):
        for i in range(100):
            try:
                print("Starting {cls} on {host}:{port}".format(
                    cls=self.__class__.__name__,
                    host=self.host,
                    port=self.port)
                )
                self.server.serve_forever()
                break
            except AssertionError:
                self.clear_port()
        else:
            raise AssertionError("No free port found, starting aborted")


import os
from multiprocessing import Process, Value
from SimpleHTTPServer import SimpleHTTPRequestHandler
import random
import SocketServer


class FakeServer(SocketServer.TCPServer):
    allow_reuse_address = True


class FakeHandler(SimpleHTTPRequestHandler):
    def write_file(self, directory, filename):
        '''
        Send file with given `filename` to the client. File must be in
        `directory` in the data/ subdirectory of the directory
        where the current __file__ is.
        '''
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'data', directory, filename)

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-length", os.stat(path).st_size)
        self.end_headers()
        with open(path) as f:
            self.wfile.write(f.read())


class FakeVirt(Process):
    def __init__(self, handler_class, host='localhost', port=None):
        super(FakeVirt, self).__init__()
        self._port = port
        self.host = host
        self.handler_class = handler_class
        self.server = FakeServer((self.host, self.port), handler_class)
        self.daemon = True
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

    @property
    def data_version(self):
        return self._data_version.value

    @data_version.setter
    def data_version(self, version):
        self._data_version.value = version

    def run(self):
        for i in range(100):
            try:
                print("Starting {cls} on port {port}".format(cls=self.__class__.__name__, port=self.port))
                self.server.serve_forever()
                break
            except AssertionError:
                self.clear_port()
        else:
            raise AssertionError("No free port found, starting aborted")

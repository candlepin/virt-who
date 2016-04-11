
import os
import time

from xml.etree import ElementTree

from fake_virt import FakeVirt, FakeHandler


class EsxHandler(FakeHandler):
    def do_GET(self):
        print '[GET] >>>>>>>', self.path
        '''
        time.sleep(0.1)
        base = os.path.dirname(os.path.abspath(__file__))
        if self.path == '/api/clusters':
            with open(os.path.join(base, 'data/rhevm/rhevm_clusters.xml'), 'r') as f:
                self.wfile.write(f.read())
        if self.path == '/api/hosts':
            with open(os.path.join(base, 'data/rhevm/rhevm_hosts.xml'), 'r') as f:
                self.wfile.write(f.read())
        elif self.path == '/api/vms':
            vms = 'data/rhevm/rhevm_vms_%d.xml' % self.server._data_version.value
            with open(os.path.join(base, vms), 'r') as f:
                self.wfile.write(f.read())
        '''

    def write_file(self, filename):
        '''
        Send file with given `filename` to the client. File must be in
        data/esx/ subdirectory of the directory where the current __file__ is.
        '''
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, 'data', 'esx', filename)) as f:
            self.wfile.write(f.read())

    def do_POST(self):
        if self.path == '/sdk':
            length = int(self.headers.getheader('content-length'))
            data = self.rfile.read(length)
            xml = ElementTree.fromstring(data)
            body = xml.find('{http://schemas.xmlsoap.org/soap/envelope/}Body')
            root = body[0]
            print ">>>>", self.path, root.tag, self.server._data_version.value

            if 'RetrieveServiceContent' in root.tag:
                self.write_file('esx_retrieveservicecontent.xml')
            elif 'Login' in root.tag:
                if root.find('{urn:vim25}userName').text != 'A!bc\n 3#\'"' or root.find('{urn:vim25}password').text != 'A!bc\n 3#\'"':
                    self.send_error(401, 'Cannot complete login due to an incorrect user name or password.')
                self.write_file('esx_loginresponse.xml')
            elif 'Logout' in root.tag:
                self.write_file('esx_logoutresponse.xml')
            elif 'CreateFilter' in root.tag:
                self.write_file('esx_createfilterresponse.xml')
            elif 'WaitForUpdatesEx' in root.tag:
                time.sleep(1)
                version = self.server._data_version.value
                self.write_file('esx_waitforupdatesexresponse_%d.xml' % version)
            elif 'CancelWaitForUpdatesEx' in root.tag:
                self.write_file('esx_cancelwaitforupdatesexresponse.xml')
            elif 'DestroyPropertyFilter' in root.tag:
                self.write_file('esx_destroypropertyfilterresponse.xml')

class FakeEsx(FakeVirt):
    def __init__(self, port=None):
        super(FakeEsx, self).__init__(EsxHandler, port=port)
        self.server._data_version = self._data_version

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

from fake_server import FakeServer

from multiprocessing import Value


class FakeVirt(FakeServer):

    virt_type = None

    """
    Base class for fake virt backends like RHEVM or ESX
    """
    def __init__(self, handler_class, host='localhost', port=None):
        super(FakeVirt, self).__init__(handler_class, host, port)
        self._data_version = Value('d', 0)

    @property
    def username(self):
        return 'A!bc3#\'"'

    @property
    def password(self):
        return 'A!bc3#\'"'

    @property
    def data_version(self):
        return self._data_version.value

    @data_version.setter
    def data_version(self, version):
        self._data_version.value = version

    def virt_who_config(self):
        """
        This method return configuration file that can be used by virt-who for testing
        :return: string with configuration file
        """
        conf_file_content = """
[test]
type=%s
server=http://localhost:%s
username=%s
password=%s
owner=admin
        """ % (self.virt_type, self.port, self.username, self.password)
        return conf_file_content

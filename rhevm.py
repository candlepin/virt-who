"""
Module for communcating with RHEV-M, part of virt-who

Copyright (C) 2012 Radek Novacek <rnovacek@redhat.com>

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

import sys
import urlparse
import urllib2
import base64

# Import XML parser
try:
    from elementtree import ElementTree
except ImportError:
    from xml.etree import ElementTree

class RHEVM:
    def __init__(self, logger, url, username, password):
        self.logger = logger
        self.url = url
        if "//" not in self.url:
            self.url = "//" + url
        parsed = urlparse.urlsplit(self.url, "https")
        if ":" not in parsed[1]:
            netloc = parsed[1] + ":8443"
        else:
            netloc = parsed[1]
        self.url = urlparse.urlunsplit((parsed[0], netloc, parsed[2], "", ""))

        self.username = username
        self.password = password

        self.hosts_url = urlparse.urljoin(self.url, "/api/hosts")
        self.vms_url = urlparse.urljoin(self.url, "/api/vms")

        self.auth = base64.encodestring('%s:%s' % (username, password))[:-1]

    def get(self, url):
        """
        Call RHEV-M server and retrieve what's on given url.
        """
        request = urllib2.Request(url)
        request.add_header("Authorization", "Basic %s" % self.auth)
        return urllib2.urlopen(request)

    def getHostGuestMapping(self):
        """
        Returns dictionary with host to guest mapping, e.g.:

        { 'host_id_1': ['guest1', 'guest2'],
          'host_id_2': ['guest3', 'guest4'],
        }
        """
        mapping = {}

        hosts_xml = ElementTree.parse(self.get(self.hosts_url))
        vms_xml = ElementTree.parse(self.get(self.vms_url))

        for host in hosts_xml.findall('host'):
            id = host.get('id')
            mapping[id] = []

        for vm in vms_xml.findall('vm'):
            guest_id = vm.get('id')
            host = vm.find('host')
            if host is None:
                # Guest don't have any host
                continue

            host_id = host.get('id')
            if host_id not in mapping.keys():
                self.logger.warning("Guest %s claims that it belongs to host %s which doen't exist" % (guest_id, host_id))
            else:
                mapping[host_id].append(guest_id)

        return mapping

    def ping(self):
        return True

if __name__ == '__main__':
    # TODO: read from config
    if len(sys.argv) < 4:
        print "Usage: %s url username password"
        sys.exit(0)

    import logging
    logger = logging.Logger("")
    rhevm = RHEVM(logger, sys.argv[1], sys.argv[2], sys.argv[3])
    rhevm.getHostGuestMapping()

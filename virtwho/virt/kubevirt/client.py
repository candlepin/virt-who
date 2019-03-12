#
# Copyright 2019 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#
from __future__ import absolute_import

import json
import ssl
import urllib3

from six import PY3

from virtwho.virt.kubevirt import config


class KubeClient:

    def __init__(self, path):
        cfg = config.Configuration()
        cl = config._get_kube_config_loader_for_yaml_file(path)
        cl.load_and_set(cfg)

        cert_reqs = ssl.CERT_REQUIRED
        ca_certs = cfg.ssl_ca_cert
        cert_file = cfg.cert_file
        key_file = cfg.key_file

        self._pool_manager = urllib3.PoolManager(
            num_pools=4,
            maxsize=4,
            cert_reqs=cert_reqs,
            ca_certs=ca_certs,
            cert_file=cert_file,
            key_file=key_file
        )

        self.host = cfg.host
        self.token = cfg.token
        self._version = self._kubevirt_version()

    def get_nodes(self):
        return self._request('/api/v1/nodes')

    def get_vms(self):
        return self._request('/apis/kubevirt.io/' + self._version + '/virtualmachineinstances')

    def _kubevirt_version(self):
        versions = self._request('/apis/kubevirt.io')
        return versions['preferredVersion']['version']

    def _request(self, path):
        header_params = {}

        header_params['Accept'] = 'application/json'
        header_params['Content-Type'] = 'application/json'
        header_params['Authorization'] = self.token

        url = self.host + path

        try:
            r = self._pool_manager.request("GET", url,
                                          fields=None,
                                          preload_content=True,
                                          headers=header_params)
        except urllib3.exceptions.SSLError as e:
            msg = "{0}\n{1}".format(type(e).__name__, str(e))
            raise ApiException(status=0, reason=msg)

        # In the python 3, the response.data is bytes.
        # we need to decode it to string.
        if PY3:
            r.data = r.data.decode('utf8')

        if not 200 <= r.status <= 299:
            raise ApiException(http_resp=r)

        # fetch data from response object
        try:
            data = json.loads(r.data)
        except ValueError:
            data = r.data

        return data


class ApiException(Exception):

    def __init__(self, status=None, reason=None, http_resp=None):
        if http_resp:
            self.status = http_resp.status
            self.reason = http_resp.reason
            self.body = http_resp.data
            self.headers = http_resp.getheaders()
        else:
            self.status = status
            self.reason = reason
            self.body = None
            self.headers = None

    def __str__(self):
        """
        Custom error messages for exception
        """
        error_message = "({0})\n"\
                        "Reason: {1}\n".format(self.status, self.reason)
        if self.headers:
            error_message += "HTTP response headers: {0}\n".format(self.headers)

        if self.body:
            error_message += "HTTP response body: {0}\n".format(self.body)

        return error_message

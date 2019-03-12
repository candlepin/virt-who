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

import atexit
import base64
import os
import tempfile
import urllib3
import yaml


KUBE_CONFIG_DEFAULT_LOCATION = os.environ.get('KUBECONFIG', '~/.kube/config')
_temp_files = {}


def _create_temp_file_with_content(content):
    if len(_temp_files) == 0:
        atexit.register(_cleanup_temp_files)
    # Because we may change context several times, try to remember files we
    # created and reuse them at a small memory cost.
    content_key = str(content)
    if content_key in _temp_files:
        return _temp_files[content_key]
    _, name = tempfile.mkstemp()
    _temp_files[content_key] = name
    with open(name, 'wb') as fd:
        fd.write(content.encode() if isinstance(content, str) else content)
    return name


def _cleanup_temp_files():
    global _temp_files
    for temp_file in _temp_files.values():
        try:
            os.remove(temp_file)
        except OSError:
            pass
    _temp_files = {}


def _get_kube_config_loader_for_yaml_file(filename, **kwargs):
    with open(filename) as f:
        return KubeConfigLoader(
            config_dict=yaml.load(f),
            config_base_path=os.path.abspath(os.path.dirname(filename)),
            **kwargs)


class Configuration(object):
    pass


class ConfigException(Exception):
    pass


class KubeConfigLoader(object):

    def __init__(self, config_dict, active_context=None,
                 config_base_path="",
                 config_persister=None):
        self._config = ConfigNode('kube-config', config_dict)
        self._current_context = None
        self._user = None
        self._cluster = None
        self.set_active_context(active_context)
        self._config_base_path = config_base_path
        self._config_persister = config_persister

    def set_active_context(self, context_name=None):
        if context_name is None:
            context_name = self._config['current-context']
        self._current_context = self._config['contexts'].get_with_name(
            context_name)
        if (self._current_context['context'].safe_get('user') and
                self._config.safe_get('users')):
            user = self._config['users'].get_with_name(
                self._current_context['context']['user'], safe=True)
            if user:
                self._user = user['user']
            else:
                self._user = None
        else:
            self._user = None
        self._cluster = self._config['clusters'].get_with_name(
            self._current_context['context']['cluster'])['cluster']

    def _load_cluster_info(self):
        if 'server' in self._cluster:
            self.host = self._cluster['server']
            if self.host.startswith("https"):
                self.ssl_ca_cert = FileOrData(
                    self._cluster, 'certificate-authority',
                    file_base_path=self._config_base_path).as_file()
                self.cert_file = FileOrData(
                    self._user, 'client-certificate',
                    file_base_path=self._config_base_path).as_file()
                self.key_file = FileOrData(
                    self._user, 'client-key',
                    file_base_path=self._config_base_path).as_file()
        if 'insecure-skip-tls-verify' in self._cluster:
            self.verify_ssl = not self._cluster['insecure-skip-tls-verify']

    def _load_authentication(self):
        if self._load_user_token():
            return
        self._load_user_pass_token()

    def _load_user_token(self):
        token = FileOrData(
            self._user, 'tokenFile', 'token',
            file_base_path=self._config_base_path,
            base64_file_content=False).as_data()
        if token:
            self.token = "Bearer %s" % token
            return True

    def _load_user_pass_token(self):
        if 'username' in self._user and 'password' in self._user:
            self.token = urllib3.util.make_headers(
                basic_auth=(self._user['username'] + ':' +
                            self._user['password'])).get('authorization')
            return True

    def _set_config(self, client_configuration):
        if 'token' in self.__dict__:
            client_configuration.token = self.token
        # copy these keys directly from self to configuration object
        keys = ['host', 'ssl_ca_cert', 'cert_file', 'key_file', 'verify_ssl']
        for key in keys:
            if key in self.__dict__:
                setattr(client_configuration, key, getattr(self, key))

    def load_and_set(self, client_configuration):
        self._load_authentication()
        self._load_cluster_info()
        self._set_config(client_configuration)

    def list_contexts(self):
        return [context.value for context in self._config['contexts']]

    @property
    def current_context(self):
        return self._current_context.value


class ConfigNode(object):
    """Remembers each config key's path and construct a relevant exception
    message in case of missing keys. The assumption is all access keys are
    present in a well-formed kube-config."""

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __contains__(self, key):
        return key in self.value

    def __len__(self):
        return len(self.value)

    def safe_get(self, key):
        if (isinstance(self.value, list) and isinstance(key, int) or
                key in self.value):
            return self.value[key]

    def __getitem__(self, key):
        v = self.safe_get(key)
        if not v:
            raise ConfigException(
                'Invalid kube-config file. Expected key %s in %s'
                % (key, self.name))
        if isinstance(v, dict) or isinstance(v, list):
            return ConfigNode('%s/%s' % (self.name, key), v)
        else:
            return v

    def get_with_name(self, name, safe=False):
        if not isinstance(self.value, list):
            raise ConfigException(
                'Invalid kube-config file. Expected %s to be a list'
                % self.name)
        result = None
        for v in self.value:
            if 'name' not in v:
                raise ConfigException(
                    'Invalid kube-config file. '
                    'Expected all values in %s list to have \'name\' key'
                    % self.name)
            if v['name'] == name:
                if result is None:
                    result = v
                else:
                    raise ConfigException(
                        'Invalid kube-config file. '
                        'Expected only one object with name %s in %s list'
                        % (name, self.name))
        if result is not None:
            return ConfigNode('%s[name=%s]' % (self.name, name), result)
        if safe:
            return None
        raise ConfigException(
            'Invalid kube-config file. '
            'Expected object with name %s in %s list' % (name, self.name))


class FileOrData(object):
    """Utility class to read content of obj[%data_key_name] or file's
     content of obj[%file_key_name] and represent it as file or data.
     Note that the data is preferred. The obj[%file_key_name] will be used iff
     obj['%data_key_name'] is not set or empty. Assumption is file content is
     raw data and data field is base64 string. The assumption can be changed
     with base64_file_content flag. If set to False, the content of the file
     will assumed to be base64 and read as is. The default True value will
     result in base64 encode of the file content after read."""

    def __init__(self, obj, file_key_name, data_key_name=None,
                 file_base_path="", base64_file_content=True):
        if not data_key_name:
            data_key_name = file_key_name + "-data"
        self._file = None
        self._data = None
        self._base64_file_content = base64_file_content
        if data_key_name in obj:
            self._data = obj[data_key_name]
        elif file_key_name in obj:
            self._file = os.path.normpath(
                os.path.join(file_base_path, obj[file_key_name]))

    def as_file(self):
        """If obj[%data_key_name] exists, return name of a file with base64
        decoded obj[%data_key_name] content otherwise obj[%file_key_name]."""
        use_data_if_no_file = not self._file and self._data
        if use_data_if_no_file:
            if self._base64_file_content:
                if isinstance(self._data, str):
                    content = self._data.encode()
                else:
                    content = self._data
                self._file = _create_temp_file_with_content(
                    base64.standard_b64decode(content))
            else:
                self._file = _create_temp_file_with_content(self._data)
        if self._file and not os.path.isfile(self._file):
            raise ConfigException("File does not exists: %s" % self._file)
        return self._file

    def as_data(self):
        """If obj[%data_key_name] exists, Return obj[%data_key_name] otherwise
        base64 encoded string of obj[%file_key_name] file content."""
        use_file_if_no_data = not self._data and self._file
        if use_file_if_no_data:
            with open(self._file) as f:
                if self._base64_file_content:
                    self._data = bytes.decode(
                        base64.standard_b64encode(str.encode(f.read())))
                else:
                    self._data = f.read()
        return self._data

# -*- coding: utf-8 -*-
from __future__ import print_function
"""
Module for reading configuration files

Copyright (C) 2017 Christopher Snyder <csnyder@redhat.com>

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
import copy
from threading import Lock


class Datastore(object):
    """ This class is a threadsafe datastore"""

    def __init__(self, *args, **kwargs):
        self._datastore = dict()
        self._datastore_lock = Lock()

    def put(self, key, value):
        """
        Stores the value, retrievable by key, in a threadsafe manner in the
        underlying datastore.

        @param key: The unique identifier for this value
        @type  key: str

        @param value: The object to store
        """
        to_store = copy.deepcopy(value)
        with self._datastore_lock:
            self._datastore[key] = to_store

    def get(self, key, default=None):
        """
        Retrieves the value for the given key, in a threadsafe manner from the
        underlying datastore.

        @param key: The unique identifier for this value
        @type  key: str

        @param default: An optional default object to return should the
        underlying datastore not have an item for the given key.

        @raises KeyError: A KeyError is raised when the underlying datastore
        has no item for the given key and a default has not been provided.
        """
        with self._datastore_lock:
            try:
                return self._datastore[key]
            except KeyError:
                if default:
                    return default
                raise

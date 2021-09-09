# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify it under
# the terms of the (LGPL) GNU Lesser General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Library Lesser General Public License
# for more details at ( http://www.gnu.org/licenses/lgpl.html ).
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# written by: Jurko Gospodnetić ( jurko.gospodnetic@pke.hr )

"""
Suds Python library DocumentStore unit tests.

Implemented using the 'pytest' testing framework.

"""

if __name__ == "__main__":
    import testutils
    testutils.run_using_pytest(globals())

import virtwho.virt.esx.suds
import virtwho.virt.esx.suds.store

import pytest


def test_accessing_DocumentStore_content():
    content1 = virtwho.virt.esx.suds.byte_str("one")
    content2 = virtwho.virt.esx.suds.byte_str("two")
    content1_1 = virtwho.virt.esx.suds.byte_str("one one")

    store = virtwho.virt.esx.suds.store.DocumentStore({"1": content1})
    assert len(store) == 2
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)

    store = virtwho.virt.esx.suds.store.DocumentStore({"1": content1, "2": content2})
    assert len(store) == 3
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)
    _test_open(store, "2", content2)

    store = virtwho.virt.esx.suds.store.DocumentStore(uno=content1, due=content2)
    assert len(store) == 3
    _test_default_DocumentStore_content(store)
    _test_open(store, "uno", content1)
    _test_open(store, "due", content2)

    store = virtwho.virt.esx.suds.store.DocumentStore({"1 1": content1_1})
    assert len(store) == 2
    _test_default_DocumentStore_content(store)
    _test_open(store, "1 1", content1_1)

    store = virtwho.virt.esx.suds.store.DocumentStore({"1": content1, "1 1": content1_1})
    assert len(store) == 3
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)
    _test_open(store, "1 1", content1_1)


def test_accessing_missing_DocumentStore_content():
    store = virtwho.virt.esx.suds.store.DocumentStore()
    assert store.open("missing-content") is None
    assert store.open("buga-wuga://missing-content") is None
    assert store.open("ftp://missing-content") is None
    assert store.open("http://missing-content") is None
    assert store.open("https://missing-content") is None
    pytest.raises(Exception, store.open, "suds://missing-content")


def test_default_DocumentStore_instance():
    assert len(virtwho.virt.esx.suds.store.defaultDocumentStore) == 1
    _test_default_DocumentStore_content(virtwho.virt.esx.suds.store.defaultDocumentStore)


def test_empty_DocumentStore_instance_is_not_shared():
    assert virtwho.virt.esx.suds.store.DocumentStore() is not virtwho.virt.esx.suds.store.defaultDocumentStore
    assert virtwho.virt.esx.suds.store.DocumentStore() is not virtwho.virt.esx.suds.store.DocumentStore()


def test_updating_DocumentStore_content():
    content1 = virtwho.virt.esx.suds.byte_str("one")
    content2 = virtwho.virt.esx.suds.byte_str("two")
    content1_1 = virtwho.virt.esx.suds.byte_str("one one")

    store = virtwho.virt.esx.suds.store.DocumentStore()
    assert len(store) == 1
    _test_default_DocumentStore_content(store)

    store.update({"1": content1})
    assert len(store) == 2
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)

    store.update({"1": content1, "2": content2, "1 1": content1_1})
    assert len(store) == 4
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)
    _test_open(store, "2", content2)
    _test_open(store, "1 1", content1_1)

    store.update({"2": content2, "1 1": content1_1})
    assert len(store) == 4
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)
    _test_open(store, "2", content2)
    _test_open(store, "1 1", content1_1)

    store.update(uno=content1, due=content2)
    assert len(store) == 6
    _test_default_DocumentStore_content(store)
    _test_open(store, "1", content1)
    _test_open(store, "2", content2)
    _test_open(store, "1 1", content1_1)
    _test_open(store, "uno", content1)
    _test_open(store, "due", content2)


def _test_default_DocumentStore_content(store):
    _test_open(store, "schemas.xmlsoap.org/soap/encoding/",
        virtwho.virt.esx.suds.store.soap5_encoding_schema)


def _test_open(store, location, expected_content):
    assert store.open(location) is expected_content
    assert store.open("buga-wuga://%s" % location) is expected_content
    assert store.open("ftp://%s" % location) is expected_content
    assert store.open("http://%s" % location) is expected_content
    assert store.open("https://%s" % location) is expected_content
    assert store.open("suds://%s" % location) is expected_content

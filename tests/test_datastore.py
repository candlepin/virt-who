from __future__ import print_function
from base import TestBase
from mock import sentinel, patch, MagicMock
from threading import Lock
from virtwho.datastore import Datastore


class TestDatastore(TestBase):

    def setUp(self):
        copy_patcher = patch('virtwho.datastore.copy')
        self.mock_copy = copy_patcher.start()
        self.mock_copy.deepcopy.side_effect = [
            sentinel.deep_copy_value_1,
            sentinel.deep_copy_value_2
        ]
        self.addCleanup(copy_patcher.stop)

        lock_patcher = patch('virtwho.datastore.Lock')
        mock_lock_class = lock_patcher.start()
        mock_lock_instance = MagicMock(spec=Lock())
        mock_lock_class.return_value = mock_lock_instance
        self.mock_lock = mock_lock_instance
        self.addCleanup(lock_patcher.stop)

    def _mock_test_data(self, datastore, **kwargs):
        # Sets the datastore to contain the keys and values of the kwargs
        # in a way that does not use the put method of the datastore
        # Returns the datastore instance as modified, the test internal
        # datastore
        mock_internal_datastore = MagicMock(wraps=dict(kwargs))
        datastore._datastore = mock_internal_datastore
        return datastore, mock_internal_datastore

    def test_get_uses_lock(self):
        # Ensure a lock is acquired before returning a particular entry in the
        # store

        # Ensure that a lock is acquired before updating a particular entry
        # in the store.
        # These assertions assume the lock is used as a context manager
        # and that the lock (when used as a context manager) is acquired by
        # the calling thread on __enter__ and released by the calling thread
        # on __exit__
        datastore, mock_internal_datastore = self._mock_test_data(Datastore(),
                                                                 test_item=sentinel.test_value)

        def assert_internal_store_unchanged(*args, **kwargs):
            # Assert there have been no accesses of the internal datastore
            mock_internal_datastore.__getitem__.assert_not_called()
            mock_internal_datastore.__setitem__.assert_not_called()

        def assert_internal_store_accessed(*args, **kwargs):
            mock_internal_datastore.__getitem__.assert_called_once_with(
                    "test_item")
            mock_internal_datastore.__setitem__.assert_not_called()

        self.mock_lock.__enter__.side_effect = assert_internal_store_unchanged
        self.mock_lock.__exit__.side_effect = assert_internal_store_accessed

        datastore.get("test_item")

        # These assertions assume the lock is used as a context manager
        # and that the lock (when used as a context manager) is acquired by
        # the calling thread on __enter__ and released by the calling thread
        # on __exit__
        self.mock_lock.__enter__.assert_called_once()
        self.mock_lock.__exit__.assert_called_once()

    def test_get_nonexistant_item_raises_keyerror(self):
        datastore = Datastore()
        item = sentinel.no_value
        try:
            item = datastore.get("NONEXISTANT")
        except KeyError:
            return
        self.fail("Item retrieved for nonexistant key: %s" % item)

    def test_get_nonexistant_item_with_default_returns_default(self):
        # Ensures the default is returned if there is one provided and the
        # key does not exist
        datastore = Datastore()
        result = datastore.get("NONEXISTANT", default=sentinel.default_value)
        self.assertTrue(result == sentinel.default_value)

    def test_get_existing_item_with_default_returns_item(self):
        # Ensures the item is returned if there is a default provided,
        # and the item exists
        datastore = Datastore()
        expected_value = sentinel.test_value
        self.mock_copy.deepcopy.side_effect = lambda x: x
        with patch.dict(datastore._datastore, test_item=expected_value):
            result = datastore.get("test_item", default=sentinel.default_value)
            self.assertEqual(result, expected_value)

    def test_get_returns_correct_item(self):
        # Ensure that calling the get method returns the right value for a
        # particular key, and that the value is loaded using pickle

        datastore = Datastore()
        with patch.dict(datastore._datastore,
                        test_item=sentinel.test_item_value):
            result = datastore.get("test_item")
        self.assertEqual(result, sentinel.test_item_value)

    def test_put_locking(self):
        # Ensure that a lock is acquired before (and released after) updating a
        # particular entry in the store.
        # These assertions assume the lock is used as a context manager
        # and that the lock (when used as a context manager) is acquired by
        # the calling thread on __enter__ and released by the calling thread
        # on __exit__
        datastore, mock_internal_datastore = self._mock_test_data(Datastore(),
                                                                 test_item=sentinel.test_value)

        def assert_internal_store_unchanged(*args, **kwargs):
            # Assert there have been no accesses of the internal datastore
            mock_internal_datastore.__getitem__.assert_not_called()
            mock_internal_datastore.__setitem__.assert_not_called()

        def assert_internal_store_accessed(*args, **kwargs):
            mock_internal_datastore.__setitem__.assert_called_once_with(
                    "test_item", sentinel.deep_copy_value_1)

        self.mock_lock.__enter__.side_effect = assert_internal_store_unchanged
        self.mock_lock.__exit__.side_effect = assert_internal_store_accessed

        datastore.put("test_item", "test_item")
        self.mock_lock.__enter__.assert_called_once()
        self.mock_lock.__exit__.assert_called_once()

    def test_put_uses_deepcopy(self):
        # Ensure that put uses the return value of pickle.dumps
        test_item = "test_value"
        test_key = "test_item"
        datastore, mock_internal_ds = self._mock_test_data(Datastore(),
                                                          test_item=test_item)
        datastore.put(test_key, test_item)
        self.mock_copy.deepcopy.assert_called_with(test_item)
        expected_value = sentinel.deep_copy_value_1
        mock_internal_ds.__setitem__.assert_called_with(test_key,
                                                        expected_value)

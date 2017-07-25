
import os
import tempfile
import shutil

from base import TestBase
from stubs import StubEffectiveConfig

from mock import Mock, patch, call
from threading import Event

from virtwho.config import DestinationToSourceMapper, Config, VW_GLOBAL
from virtwho.manager import ManagerThrottleError, ManagerFatalError
from virtwho.virt import HostGuestAssociationReport, Hypervisor, Guest, \
    DestinationThread, ErrorReport, AbstractVirtReport, DomainListReport


xvirt = type("", (), {'CONFIG_TYPE': 'xxx'})()


class TestVirtInclude(TestBase):
    def test_filter_hosts(self):
        self.filter_hosts('filter_hosts=12345')

    def test_exclude_hosts(self):
        self.filter_hosts('exclude_hosts=00000')

    def test_filter_hosts_glob(self):
        self.filter_hosts('filter_hosts=12*')
        self.filter_hosts('filter_hosts=12?45')
        self.filter_hosts('filter_hosts=12[36]45')

    def test_exclude_hosts_glob(self):
        self.filter_hosts('exclude_hosts=00*')
        self.filter_hosts('exclude_hosts=00?00')
        self.filter_hosts('exclude_hosts=00[03]00')

    def test_filter_hosts_regex(self):
        self.filter_hosts('filter_hosts=12.*')
        self.filter_hosts('filter_hosts=12.+45')
        self.filter_hosts('filter_hosts=12[36]45')

    def test_exclude_hosts_regex(self):
        self.filter_hosts('exclude_hosts=00.*')
        self.filter_hosts('exclude_hosts=00.+00')
        self.filter_hosts('exclude_hosts=00[03]00')

    def test_filter_host_uuids(self):
        self.filter_hosts('filter_host_uuids=12345')

    def test_exclude_host_uuids(self):
        self.filter_hosts('exclude_host_uuids=00000')

    def filter_hosts(self, config):
        config_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, config_dir)
        with open(os.path.join(config_dir, "test.conf"), "w") as f:
            f.write("""
[test]
type=esx
server=does.not.exist
username=username
password=password
owner=owner
env=env
{config}
""".format(config=config))
        config_manager = DestinationToSourceMapper(self.logger, config_dir)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0]

        included_hypervisor = Hypervisor('12345', guestIds=[
            Guest('guest-2', xvirt, Guest.STATE_RUNNING),
        ])
        excluded_hypervisor = Hypervisor('00000', guestIds=[
            Guest('guest-1', xvirt, Guest.STATE_RUNNING),
        ])

        assoc = {
            'hypervisors': [
                excluded_hypervisor,
                included_hypervisor,
            ]
        }

        report = HostGuestAssociationReport(config, assoc)
        assert report.association == {
            'hypervisors': [
                included_hypervisor
            ]
        }


class TestDestinationThread(TestBase):

    def setUp(self):
        self.options_values = {
            VW_GLOBAL: {
                'print': False,
            },
        }
        self.options = StubEffectiveConfig(self.options_values)

    def test_get_data(self):
        # Show that get_data accesses the given source and tries to retrieve
        # the right source_keys
        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}
        manager = Mock()
        logger = Mock()
        config = Mock()
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        destination_thread.is_initial_run = False
        result_data = destination_thread._get_data()
        self.assertEquals(result_data, datastore)

    def test_get_data_ignore_same_reports(self):
        # Show that the data returned from _get_data does not include those
        # reports whose hash is identical to that of the last one sent for
        # the given source
        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}
        last_report_for_source = {
            'source1': report1.hash
        }
        expected_data = {
            'source2': report2
        }
        manager = Mock()
        logger = Mock()
        config = Mock()
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True,
                                               options=self.options)
        destination_thread.is_initial_run = False
        destination_thread.last_report_for_source = last_report_for_source
        result_data = destination_thread._get_data()
        self.assertEquals(result_data, expected_data)

    @patch('virtwho.virt.virt.Event')
    def test_send_data_quit_on_error_report(self, mock_event_class):
        mock_event = Mock(spec=Event())
        mock_event_class.return_value = mock_event

        mock_error_report = Mock(spec=ErrorReport)

        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}
        manager = Mock()
        logger = Mock()
        config = Mock()
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True,
                                               options=self.options)
        destination_thread._send_data(mock_error_report)
        mock_event.set.assert_called()

    def test_send_data_batch_hypervisor_checkin(self):
        # This tests that reports of the right type are batched into one
        # and that the hypervisorCheckIn method of the destination is called
        # with the right parameters
        config1 = Config('source1', 'esx')
        config1.exclude_hosts = []
        config1.filter_hosts = []

        config2 = Config('source2', 'esx')
        config2.exclude_hosts = []
        config2.filter_hosts = []

        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2, Guest.STATE_RUNNING)
        assoc1 = {'hypervisors': [Hypervisor('hypervisor_id_1', [guest1])]}
        assoc2 = {'hypervisors': [Hypervisor('hypervisor_id_2', [guest2])]}
        report1 = HostGuestAssociationReport(config1, assoc1)
        report2 = HostGuestAssociationReport(config2, assoc2)

        data_to_send = {'source1': report1,
                        'source2': report2}

        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}
        manager = Mock()

        def check_hypervisorCheckIn(report, options=None):
            self.assertEquals(report.association['hypervisors'],
                              data_to_send.values)

        manager.hypervisorCheckIn = Mock(side_effect=check_hypervisorCheckIn)
        logger = Mock()
        config = Mock()
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        destination_thread._send_data(data_to_send)

    def test_send_data_poll_hypervisor_async_result(self):
        # This test's that when we have an async result from the server,
        # we poll for the result

        # Setup the test data
        config1 = Config('source1', 'esx')
        config2 = Config('source2', 'esx')
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2, Guest.STATE_RUNNING)
        assoc1 = {'hypervisors': [Hypervisor('hypervisor_id_1', [guest1])]}
        assoc2 = {'hypervisors': [Hypervisor('hypervisor_id_2', [guest2])]}
        report1 = HostGuestAssociationReport(config1, assoc1)
        report2 = HostGuestAssociationReport(config2, assoc2)

        data_to_send = {'source1': report1,
                        'source2': report2}
        source_keys = ['source1', 'source2']
        batch_report1 = Mock()  # The "report" to return from hypervisorCheckIn
        batch_report1.state = AbstractVirtReport.STATE_CREATED
        datastore = {'source1': report1, 'source2': report2}
        manager = Mock()
        manager.hypervisorCheckIn.return_value = batch_report1

        # A closure to allow us to have a function that "modifies" the given
        # report in a predictable way.
        # In this case I want to set the state of the report to STATE_FINISHED
        # after the first try
        def check_report_state_closure():
            # The local variables we'd like to use to keep track of state
            # must be in a dict (or some other mutable container) as all
            # references in the enclosing scope in python 2.X are read-only
            local_variables = {'count': 0}

            def mock_check_report_state(report):
                if local_variables['count'] > 0:
                    report.state = AbstractVirtReport.STATE_FINISHED
                else:
                    report.state = AbstractVirtReport.STATE_CREATED
                    local_variables['count'] += 1
                return report
            return mock_check_report_state
        check_report_mock = check_report_state_closure()
        manager.check_report_state = Mock(side_effect=check_report_mock)
        logger = Mock()
        config = Mock()
        config.polling_interval = 10
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        # In this test we want to see that the wait method is called when we
        # expect and with what parameters we expect
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread._send_data(data_to_send)
        # We expect there two be two calls to wait with the value of the
        # polling_interval attr because we'd like to wait one polling
        # interval before making the first check. Because the mock
        # check_report_state function will modify the report to be in the
        # successful state after the first call, we expect to wait exactly
        # twice, both of duration config.polling_interval
        destination_thread.wait.assert_has_calls([
            call(wait_time=config.polling_interval),
        ])

    def test_send_data_poll_async_429(self):
        # This test's that when a 429 is detected during async polling
        # we wait for the amount of time specified
        source_keys = ['source1', 'source2']
        config1 = Config('source1', 'esx')
        config2 = Config('source2', 'esx')
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2, Guest.STATE_RUNNING)
        assoc1 = {'hypervisors': [Hypervisor('hypervisor_id_1', [guest1])]}
        assoc2 = {'hypervisors': [Hypervisor('hypervisor_id_2', [guest2])]}
        report1 = HostGuestAssociationReport(config1, assoc1)
        report2 = HostGuestAssociationReport(config2, assoc2)

        datastore = {'source1': report1, 'source2': report2}
        data_to_send = {'source1': report1,
                        'source2': report2}
        config = Mock()
        config.polling_interval = 10
        error_to_throw = ManagerThrottleError(retry_after=62)

        manager = Mock()
        manager.hypervisorCheckIn.return_value = report1
        # A closure to allow us to have a function that "modifies" the given
        # report in a predictable way.
        # In this case I want to set the state of the report to STATE_FINISHED
        # after the first try

        def check_report_state_closure(items):
            item_iterator = iter(items)

            def mock_check_report_state(report):
                item = next(item_iterator)
                if isinstance(item, Exception):
                    raise item
                report.state = item
                return report
            return mock_check_report_state
        states = [error_to_throw, AbstractVirtReport.STATE_FINISHED]
        expected_wait_calls = [call(wait_time=error_to_throw.retry_after)]

        check_report_mock = check_report_state_closure(states)
        manager.check_report_state = Mock(side_effect=check_report_mock)
        logger = Mock()
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread._send_data(data_to_send)
        destination_thread.wait.assert_has_calls(expected_wait_calls)

    def test_send_data_domain_list_reports(self):
        # Show that DomainListReports are sent using the sendVirtGuests
        # method of the destination

        source_keys = ['source1']
        config1 = Config('source1', 'esx')
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1, Guest.STATE_RUNNING)
        report1 = DomainListReport(config1, [guest1],
                                   hypervisor_id='hypervisor_id_1')

        datastore = {'source1': report1}
        data_to_send = {'source1': report1}

        config = Mock()
        config.polling_interval = 10
        logger = Mock()

        manager = Mock()
        terminate_event = Mock()
        interval = 10
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread._send_data(data_to_send)
        manager.sendVirtGuests.assert_has_calls([call(report1,
                                                      options=destination_thread.options)])

    def test_send_data_429_during_send_virt_guests(self):
        # Show that when a 429 is encountered during the sending of a
        # DomainListReport that we retry after waiting the appropriate
        # amount of time
        source_keys = ['source1']
        config1 = Config('source1', 'esx')
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1, Guest.STATE_RUNNING)
        report1 = DomainListReport(config1, [guest1],
                                   hypervisor_id='hypervisor_id_1')

        datastore = {'source1': report1}
        data_to_send = {'source1': report1}

        config = Mock()
        config.polling_interval = 10
        logger = Mock()

        error_to_throw = ManagerThrottleError(retry_after=62)

        manager = Mock()
        manager.sendVirtGuests = Mock(side_effect=[error_to_throw, report1])
        terminate_event = Mock()
        interval = 10
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread._send_data(data_to_send)
        manager.sendVirtGuests.assert_has_calls([call(report1,
                                                      options=destination_thread.options)])
        destination_thread.wait.assert_has_calls([call(
                wait_time=error_to_throw.retry_after)])

    def test_duplicate_reports_are_ignored(self):
        """
        Test that duplicate reports are filtered out when retrieving items
        from the data store
        """
        source_keys = ['source1', 'source2']
        interval = 1
        terminate_event = Mock()
        config1 = Config('source1', 'esx')
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        config = Mock()
        manager = Mock()

        guest1 = Guest('GUUID1', virt1, Guest.STATE_RUNNING)
        report1 = DomainListReport(config1, [guest1],
                                   hypervisor_id='hypervisor_id_1')
        report2 = DomainListReport(config1, [guest1],
                                   hypervisor_id='hypervisor_id_2')
        report3 = DomainListReport(config1, [guest1],
                                   hypervisor_id='hypervisor_id_3')
        datastore = {
            'source1': report1,  # Not changing, should be excluded later
            'source2': report2,  # Will change the report sent for source2
        }
        data_to_send = {
            'source1': report1,
            'source2': report2,
        }
        logger = Mock()
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        destination_thread.is_initial_run = False
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread._send_data(data_to_send=data_to_send)

        expected_hashes = {}
        for source_key, report in data_to_send.iteritems():
            expected_hashes[source_key] = report.hash

        self.assertEqual(destination_thread.last_report_for_source,
                         expected_hashes)
        # Pretend there were updates to the datastore from elsewhere
        destination_thread.source['source2'] = report3

        next_data_to_send = destination_thread._get_data()
        expected_next_data_to_send = {
            'source2': report3
        }
        self.assertEqual(next_data_to_send, expected_next_data_to_send)


class TestDestinationThreadTiming(TestBase):
    """
    A group of tests meant to show that the destination thread does things
    in the right amount of time given different circumstances.
    """
    pass

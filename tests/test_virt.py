from __future__ import print_function

import os
import tempfile
import shutil

from base import TestBase
from stubs import StubEffectiveConfig

from mock import Mock, patch, call, ANY
from threading import Event

from virtwho import MinimumJobPollInterval
from virtwho.config import (
    DestinationToSourceMapper, VW_GLOBAL, EffectiveConfig,
    parse_file, VirtConfigSection
)
from virtwho.datastore import Datastore
from virtwho.manager import ManagerThrottleError, ManagerError
from virtwho.virt import (
    HostGuestAssociationReport, Hypervisor, Guest,
    DestinationThread, ErrorReport, AbstractVirtReport, DomainListReport,
    Virt, VirtError, StatusReport
)


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

    def test_filter_hosts_glob_filter_type(self):
        self.filter_hosts('filter_hosts=12*', 'filter_type=wildcards')
        self.filter_hosts('filter_hosts=12?45', 'filter_type=wildcards')
        self.filter_hosts('filter_hosts=12[36]45', 'filter_type=wildcards')

    def test_exclude_hosts_glob(self):
        self.filter_hosts('exclude_hosts=00*')
        self.filter_hosts('exclude_hosts=00?00')
        self.filter_hosts('exclude_hosts=00[03]00')

    def test_filter_hosts_regex(self):
        self.filter_hosts('filter_hosts=12.*')
        self.filter_hosts('filter_hosts=12.+45')
        self.filter_hosts('filter_hosts=12[36]45')

    def test_filter_hosts_regex_filter_type(self):
        self.filter_hosts('filter_hosts=12.*', 'filter_type=regex')
        self.filter_hosts('filter_hosts=12.+45', 'filter_type=regex')
        self.filter_hosts('filter_hosts=12[36]45', 'filter_type=regex')

    def test_exclude_hosts_regex(self):
        self.filter_hosts('exclude_hosts=00.*')
        self.filter_hosts('exclude_hosts=00.+00')
        self.filter_hosts('exclude_hosts=00[03]00')

    def test_filter_host_uuids(self):
        self.filter_hosts('filter_host_uuids=12345')

    def test_exclude_host_uuids(self):
        self.filter_hosts('exclude_host_uuids=00000')

    def filter_hosts(self, filter_something, filter_type=''):
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
{filter_something}
{filter_type}
""".format(filter_something=filter_something, filter_type=filter_type))
        conf = parse_file(os.path.join(config_dir, "test.conf"))
        test_conf_values = conf.pop('test')
        effective_config = EffectiveConfig()
        effective_config['test'] = VirtConfigSection.from_dict(
            test_conf_values,
            'test',
            effective_config
        )
        effective_config.validate()
        config_manager = DestinationToSourceMapper(effective_config)
        self.assertEqual(len(config_manager.configs), 1)
        config = config_manager.configs[0][1]

        included_hypervisor = Hypervisor('12345', guestIds=[
            Guest('guest-2', xvirt.CONFIG_TYPE, Guest.STATE_RUNNING),
        ])
        excluded_hypervisor = Hypervisor('00000', guestIds=[
            Guest('guest-1', xvirt.CONFIG_TYPE, Guest.STATE_RUNNING),
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


class TestVirtStatus(TestBase):

    def test_status_error(self):
        config_values = {
            'type': 'virt',
            'server': 'localhost',
            'username': 'username',
            'password': 'password',
            'owner': 'owner',
        }
        config = VirtConfigSection('test', None)
        config.update(**config_values)
        self.virt = Virt(self.logger, config, None, interval=60)  # No dest given here
        self.virt.status = True
        self.virt._send_data = Mock()
        self.virt._run = Mock(side_effect=VirtError('unable to connect to source'))
        self.run_once()

        self.virt._send_data.assert_called_once_with(data_to_send=ANY)
        self.assertTrue(isinstance(self.virt._send_data.mock_calls[0].kwargs['data_to_send'], StatusReport))
        self.assertEqual(
            self.virt._send_data.mock_calls[0].kwargs['data_to_send'].data['source']['message'],
            'unable to connect to source.'
        )

    def run_once(self, datastore=None):
        ''' Run generic virt in oneshot mode '''
        self.virt._oneshot = True
        if datastore is None:
            datastore = Mock(spec=Datastore())

        self.virt.dest = datastore
        self.virt._terminate_event = Event()
        self.virt._oneshot = True
        self.virt._interval = 0
        self.virt.run()


class TestDestinationThread(TestBase):

    default_config_args = {
        'type': 'esx',
        'hypervisor_id': 'uuid',
        'simplified_vim': True,
        'owner': 'owner'
    }

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
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        destination_thread.is_initial_run = False
        result_data = destination_thread._get_data()
        self.assertEqual(result_data, datastore)

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
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
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
        self.assertEqual(result_data, expected_data)

    def test_send_data_clear_no_hypervisors(self):
        # BZ 1943486
        # Show that a run of _send_data with zero hypervisors
        # for a config will clear the previous report hash
        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}
        last_report_for_source = {
            'source1': report1.hash,
            'source2': report2.hash
        }
        manager = Mock()
        logger = Mock()
        config, d = self.create_fake_config('source1', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
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
        destination_thread.record_status = Mock()

        report = HostGuestAssociationReport(config, {'hypervisors': []})
        destination_thread._send_data({'source1': report})
        self.assertEqual(destination_thread.last_report_for_source, {'source2': report2.hash})

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
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
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
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        d1['exclude_hosts'] = []
        d1['filter_hosts'] = []

        config2, d2 = self.create_fake_config('source2', **self.default_config_args)
        d2['exclude_hosts'] = []
        d2['filter_hosts'] = []

        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2.CONFIG_TYPE, Guest.STATE_RUNNING)
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
        options = Mock()
        options.print_ = False

        def check_hypervisorCheckIn(report, options=None):
            self.assertEqual(
                report.association['hypervisors'],
                data_to_send.values
            )

        manager.hypervisorCheckIn = Mock(side_effect=check_hypervisorCheckIn)
        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        destination_thread.record_status = Mock()
        destination_thread._send_data(data_to_send)

    def test_send_check_status_heartbeat_call(self):
        # This tests that reports of the right type are batched into one
        # and that the hypervisorCheckIn method of the destination is called
        # with the right parameters
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'
        report1 = StatusReport(config1)
        report2 = StatusReport(config2)

        data_to_send = {'source1': report1,
                        'source2': report2}

        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}

        manager = Mock()
        options = Mock()
        options.print_ = False

        def check_status(report, options=None):
            self.assertTrue(isinstance(report, StatusReport))
            self.assertEqual(options['reporter_id'], 'status_test')

        manager.hypervisorHeartbeat = Mock(side_effect=check_status)
        manager.hypervisorCheckIn = Mock()
        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, status=True,
                                               options=self.options)
        destination_thread._send_data(data_to_send)

    def test_send_check_status_heartbeat_call_failure(self):
        # This tests that reports of the right type are batched into one
        # and that the hypervisorCheckIn method of the destination is called
        # with the right parameters
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'
        report1 = StatusReport(config1)
        report2 = StatusReport(config2)

        data_to_send = {'source1': report1,
                        'source2': report2}

        source_keys = ['source1', 'source2']
        report1 = Mock()
        report2 = Mock()
        report1.hash = "report1_hash"
        report2.hash = "report2_hash"
        datastore = {'source1': report1, 'source2': report2}

        manager = Mock()
        options = Mock()
        options.print_ = False

        manager.hypervisorHeartbeat = Mock(side_effect=ManagerError("cannot connect to destination"))
        manager.hypervisorCheckIn = Mock()
        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        config.owner = 'test_owner'
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, status=True,
                                               options=self.options)
        destination_thread._send_data(data_to_send)
        for source_key, report in data_to_send.items():
            self.assertEqual(report.data['destination']['message'], "Error during status connection: cannot connect to destination.")

    def test_send_data_poll_hypervisor_async_result(self):
        # This test's that when we have an async result from the server,
        # we poll for the result

        # Setup the test data
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2.CONFIG_TYPE, Guest.STATE_RUNNING)
        assoc1 = {'hypervisors': [Hypervisor('hypervisor_id_1', [guest1])]}
        assoc2 = {'hypervisors': [Hypervisor('hypervisor_id_2', [guest2])]}
        report1 = HostGuestAssociationReport(config1, assoc1)
        report2 = HostGuestAssociationReport(config2, assoc2)

        source_keys = ['source1', 'source2']
        batch_report1 = Mock()  # The "report" to check status
        batch_report1.state = AbstractVirtReport.STATE_CREATED
        datastore = {'source1': report1, 'source2': report2}
        manager = Mock()
        items = [ManagerThrottleError(), ManagerThrottleError(), ManagerThrottleError(), AbstractVirtReport.STATE_FINISHED]
        manager.check_report_state = Mock(side_effect=self.check_report_state_closure(items))

        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        # In this test we want to see that the wait method is called when we
        # expect and with what parameters we expect
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread.check_report_status(batch_report1)
        # There should be three waits, one after the job is submitted with duration of
        # MinimumJobPollingInterval. The second and third with duration MinimumJobPollInterval * 2
        # (and all subsequent calls as demonstrated by the third wait)
        destination_thread.wait.assert_has_calls([
            call(wait_time=MinimumJobPollInterval),
            call(wait_time=MinimumJobPollInterval * 2),
            call(wait_time=MinimumJobPollInterval * 2)])

    def test_status_pending_hypervisor_async_result(self):
        # This test's that when we have an async result from the server,
        # we poll for the status on the interval until we get completed result

        # Setup the test data
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2.CONFIG_TYPE, Guest.STATE_RUNNING)
        assoc1 = {'hypervisors': [Hypervisor('hypervisor_id_1', [guest1])]}
        assoc2 = {'hypervisors': [Hypervisor('hypervisor_id_2', [guest2])]}
        report1 = HostGuestAssociationReport(config1, assoc1)
        report2 = HostGuestAssociationReport(config2, assoc2)
        report1.job_id = 'job1'
        report2.job_id = 'job2'

        source_keys = ['source1', 'source2']
        batch_report1 = Mock()  # The "report" to check status
        batch_report1.state = AbstractVirtReport.STATE_CREATED
        datastore = {'source1': report1, 'source2': report2}
        manager = Mock()
        items = [AbstractVirtReport.STATE_PROCESSING, AbstractVirtReport.STATE_PROCESSING,
                 AbstractVirtReport.STATE_PROCESSING, AbstractVirtReport.STATE_FINISHED,
                 AbstractVirtReport.STATE_FINISHED]
        manager.check_report_state = Mock(side_effect=self.check_report_state_closure(items))

        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        # In this test we want to see that the wait method is called when we
        # expect and with what parameters we expect
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread.submitted_report_and_hash_for_source = {
            'source1': (report1, 'hash1'),
            'source2': (report2, 'hash2')
        }
        reports = destination_thread._get_data_common(source_keys)
        self.assertEqual(0, len(reports))
        reports = destination_thread._get_data_common(source_keys)
        self.assertEqual(1, len(reports))
        reports = destination_thread._get_data_common(source_keys)
        self.assertEqual(2, len(reports))

    # A closure to allow us to have a function that "modifies" the given
    # report in a predictable way.
    # In this case I want to set the state of the report to STATE_FINISHED
    # after the first try

    def check_report_state_closure(self, items):
        item_iterator = iter(items)

        def mock_check_report_state(report, status=False):
            item = next(item_iterator)
            if isinstance(item, Exception):
                raise item
            report.state = item
            return report

        return mock_check_report_state

    def test_send_data_poll_async_429(self):
        # This test's that when a 429 is detected during async polling
        # we wait for the amount of time specified
        source_keys = ['source1', 'source2']
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2.CONFIG_TYPE, Guest.STATE_RUNNING)
        assoc1 = {'hypervisors': [Hypervisor('hypervisor_id_1', [guest1])]}
        assoc2 = {'hypervisors': [Hypervisor('hypervisor_id_2', [guest2])]}
        report1 = HostGuestAssociationReport(config1, assoc1)
        report2 = HostGuestAssociationReport(config2, assoc2)

        datastore = {'source1': report1, 'source2': report2}
        data_to_send = {'source1': report1,
                        'source2': report2}
        config, d = self.create_fake_config('test', **self.default_config_args)
        error_to_throw = ManagerThrottleError(retry_after=62)

        manager = Mock()
        manager.hypervisorCheckIn = Mock(side_effect=[error_to_throw, report1])
        expected_wait_calls = [call(wait_time=error_to_throw.retry_after)]

        logger = Mock()
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        options = Mock()
        options.print_ = False
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread.record_status = Mock()
        destination_thread._send_data(data_to_send)
        destination_thread.wait.assert_has_calls(expected_wait_calls)

    def test_send_data_domain_list_reports(self):
        # Show that DomainListReports are sent using the sendVirtGuests
        # method of the destination

        source_keys = ['source1']
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        report1 = DomainListReport(config1, [guest1],
                                   hypervisor_id='hypervisor_id_1')

        datastore = {'source1': report1}
        data_to_send = {'source1': report1}

        config, d = self.create_fake_config('test', **self.default_config_args)
        logger = Mock()

        manager = Mock()
        terminate_event = Mock()
        interval = 10
        options = Mock()
        options.print_ = False
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)
        destination_thread.wait = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread.record_status = Mock()
        destination_thread._send_data(data_to_send)
        manager.sendVirtGuests.assert_has_calls([call(report1,
                                                      options=destination_thread.options)])

    def test_send_data_429_during_send_virt_guests(self):
        # Show that when a 429 is encountered during the sending of a
        # DomainListReport that we retry after waiting the appropriate
        # amount of time
        config, d = self.create_fake_config('test', **self.default_config_args)
        source_keys = ['source1']
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        report1 = DomainListReport(config, [guest1],
                                   hypervisor_id='hypervisor_id_1')

        datastore = {'source1': report1}
        data_to_send = {'source1': report1}

        logger = Mock()

        error_to_throw = ManagerThrottleError(retry_after=62)

        manager = Mock()
        manager.sendVirtGuests = Mock(side_effect=[error_to_throw, report1])
        terminate_event = Mock()
        interval = 10
        options = Mock()
        options.print_ = False
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=False, options=self.options)
        destination_thread.wait = Mock()
        destination_thread.record_status = Mock()
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
        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        config, d = self.create_fake_config('test', **self.default_config_args)
        manager = Mock()

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        report1 = DomainListReport(config, [guest1],
                                   hypervisor_id='hypervisor_id_1')
        report2 = DomainListReport(config, [guest1],
                                   hypervisor_id='hypervisor_id_2')
        report3 = DomainListReport(config, [guest1],
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
        destination_thread.record_status = Mock()
        destination_thread._send_data(data_to_send=data_to_send)

        expected_hashes = {}
        for source_key, report in data_to_send.items():
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

    def test_record_status(self):
        # This tests that reports of the right type are batched into one
        # and that the hypervisorCheckIn method of the destination is called
        # with the right parameters
        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)

        virt1 = Mock()
        virt1.CONFIG_TYPE = 'esx'
        virt2 = Mock()
        virt2.CONFIG_TYPE = 'esx'

        guest1 = Guest('GUUID1', virt1.CONFIG_TYPE, Guest.STATE_RUNNING)
        guest2 = Guest('GUUID2', virt2.CONFIG_TYPE, Guest.STATE_RUNNING)
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
        options = Mock()
        options.print_ = False

        def check_hypervisorCheckIn(report, options=None):
            report.job_id = '123456789'
            return Mock()

        manager.hypervisorCheckIn = Mock(side_effect=check_hypervisorCheckIn)
        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options)

        def check_record_status(source_key, type, json_info):
            if type == 'sources':
                self.assertEqual(json_info['hypervisors'], 1)
            elif type == 'destinations':
                self.assertEqual(json_info['last_job_id'], '123456789')

        destination_thread.record_status = Mock(side_effect=check_record_status)
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread._send_data(data_to_send)

    def test_merge_status(self):
        self.tmp_dir = tempfile.mkdtemp()
        status_pid_file_name = self.tmp_dir + os.path.sep + 'virt-who-status.pid'
        status_pid_file_patcher = patch('virtwho.virt.virt.STATUS_LOCK', status_pid_file_name)
        status_pid_file_patcher.start()
        self.addCleanup(status_pid_file_patcher.stop)

        status_file_name = self.tmp_dir + os.path.sep + 'run_data.json'
        status_data_file_patcher = patch('virtwho.virt.virt.STATUS_DATA', status_file_name)
        status_data_file_patcher.start()
        self.addCleanup(status_data_file_patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir)

        with open(status_file_name, "w+") as f:
            f.write("""
{
    "sources": {
        "source1": {
            "last_successful_retrieve": "2020-02-28 07:25:25 UTC",
            "hypervisors": 20,
            "guests": 37
        },
        "source2": {
            "last_successful_retrieve": null
        }
    },
    "destinations": {
        "source1": {
            "last_successful_send": "2020-02-28 07:25:27 UTC",
            "last_job_id": "hypervisor12345"
        },
        "source2": {
            "last_successful_send": null,
            "last_job_id": null
        }
    }
}

        """)
        os.chmod(status_file_name, 444)

        config1, d1 = self.create_fake_config('source1', **self.default_config_args)
        config2, d2 = self.create_fake_config('source2', **self.default_config_args)

        report1 = StatusReport(config1)
        report2 = StatusReport(config2)

        data_to_send = {'source1': report1,
                        'source2': report2}

        source_keys = ['source1', 'source2']
        datastore = {'source1': Mock(), 'source2': Mock()}
        manager = Mock()
        options = Mock()
        options.print_ = False

        manager.hypervisorCheckIn = Mock()
        logger = Mock()
        config, d = self.create_fake_config('test', **self.default_config_args)
        config.owner = 'test_owner'
        terminate_event = Mock()
        interval = 10  # Arbitrary for this test
        destination_thread = DestinationThread(logger, config,
                                               source_keys=source_keys,
                                               source=datastore,
                                               dest=manager,
                                               interval=interval,
                                               terminate_event=terminate_event,
                                               oneshot=True, options=self.options,
                                               status=True)

        def check_report_status(report, status_call):
            self.assertTrue(status_call)
            report.last_job_status = "FINISHED"

        destination_thread.record_status = Mock()
        destination_thread.is_terminated = Mock(return_value=False)
        destination_thread.check_report_status = Mock(side_effect=check_report_status)
        destination_thread._send_data(data_to_send)
        self.assertEqual(report1.data['source']['last_successful_retrieve'], "2020-02-28 07:25:25 UTC")
        self.assertEqual(report1.data['source']['hypervisors'], 20)
        self.assertEqual(report1.data['source']['guests'], 37)
        self.assertEqual(report1.data['destination']["last_successful_send"], "2020-02-28 07:25:27 UTC")
        self.assertEqual(report1.data['destination']["last_successful_send_job_status"], "FINISHED")
        self.assertEqual(report2.data['source']['last_successful_retrieve'], None)
        self.assertEqual(report2.data['source']['hypervisors'], None)
        self.assertEqual(report2.data['source']['guests'], None)
        self.assertEqual(report2.data['destination']["last_successful_send"], None)
        self.assertEqual(report2.data['destination']["last_successful_send_job_status"], None)


class TestDestinationThreadTiming(TestBase):
    """
    A group of tests meant to show that the destination thread does things
    in the right amount of time given different circumstances.
    """
    pass

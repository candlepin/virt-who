Name:           virt-who
Version:        0.15
Release:        1%{?dist}
Summary:        Agent for reporting virtual guest IDs to subscription-manager

Group:          System Environment/Base
License:        GPLv2+
URL:            https://fedorahosted.org/virt-who/
Source0:        https://fedorahosted.org/releases/v/i/virt-who/%{name}-%{version}.tar.gz
BuildRoot:      %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)

BuildArch:      noarch
BuildRequires:  python2-devel
Requires:       libvirt-python
# python-rhsm 1.10.10 has required call for guestId support
Requires:       python-rhsm >= 1.10.10
# python-suds is required for vSphere support
Requires:       python-suds
# m2crypto is required for Hyper-V support
Requires:       m2crypto
Requires(post): chkconfig
Requires(preun): chkconfig
# This is for /sbin/service
Requires(preun): initscripts

%description
Agent that collects information about virtual guests present in the system and
report them to the subscription manager.

%prep
%setup -q


%build


%install
rm -rf $RPM_BUILD_ROOT

make DESTDIR=$RPM_BUILD_ROOT install
mkdir -p %{buildroot}/%{_sharedstatedir}/%{name}
mkdir -p %{buildroot}/%{_sysconfdir}/virt-who.d
touch %{buildroot}/%{_sharedstatedir}/%{name}/key

# Don't run test suite in check section, because it need the system to be
# registered to subscription-manager server

%clean
rm -rf $RPM_BUILD_ROOT

%post
# This adds the proper /etc/rc*.d links for the script
/sbin/chkconfig --add virt-who

%preun
if [ $1 -eq 0 ] ; then
    /sbin/service virt-who stop >/dev/null 2>&1
    /sbin/chkconfig --del virt-who
fi

%postun
if [ "$1" -ge "1" ] ; then
    /sbin/service virt-who condrestart >/dev/null 2>&1 || :
fi


%files
%doc README.md LICENSE
%{_bindir}/virt-who
%{_bindir}/virt-who-password
%{_datadir}/virt-who/
%{_sysconfdir}/rc.d/init.d/virt-who
%attr(600, root, root) %dir %{_sysconfdir}/virt-who.d
%attr(600, root, root) %config(noreplace) %{_sysconfdir}/sysconfig/virt-who
%{_mandir}/man8/virt-who.8.gz
%{_mandir}/man8/virt-who-password.8.gz
%{_mandir}/man5/virt-who-config.5.gz
%attr(600, root, root) %{_sharedstatedir}/%{name}
%ghost %{_sharedstatedir}/%{name}/key
%{_sysconfdir}/virt-who.d/template.conf


%changelog
* Tue Aug 04 2015 Devan Goodwin <dgoodwin@rm-rf.ca> 0.15-1
- Update spec for renamed README.md. (dgoodwin@redhat.com)
- Moves fakevirt._decode() to util.decode() (csnyder@redhat.com)
- Adds the report.config.name to log message when refusing to send a report due
  to lack of change (csnyder@redhat.com)
- VirtWho: Clears list of reports on reload (csnyder@redhat.com)
- Revises change detection tests to account for changes in master
  (csnyder@redhat.com)
- Libvirtd: Sends a report on start up, and on events (csnyder@redhat.com)
- Removes trailing line at the end of the file (csnyder@redhat.com)
- Test_Esx: Test Oneshot to ensure it queues a report (csnyder@redhat.com)
- Esx: only queue data if the version has changed (csnyder@redhat.com)
- Test_VirtWho:Patches manager.Manager.fromOptions, removes unnecessary mocks
  (csnyder@redhat.com)
- Removes unhelpful debug log message (csnyder@redhat.com)
- Fix spacing, remove unused imports (csnyder@redhat.com)
- Test_VirtWho: Adds test to show same report will not be sent twice
  (csnyder@redhat.com)
- VirtWho: Adds basic change detection using report hashs (csnyder@redhat.com)
- Adds hash property to config (csnyder@redhat.com)
- Adds hash property to DomainListReport and HypervisorGuestAssociationReport
  (csnyder@redhat.com)
- Hypervisor: Adds getHash class method (csnyder@redhat.com)
- Limits interval settings (wpoteat@redhat.com)
- Retry sending data to subscription manager multiple times before dropping
  (rnovacek@redhat.com)
- SubscriptionManager: nicely order keys in debug report (rnovacek@redhat.com)
- Fix serialization of guest list in print mode (rnovacek@redhat.com)
- Do not exit oneshot mode if any job exists (rnovacek@redhat.com)
- SubscriptionManager: check if report result has failedUpdate item
  (rnovacek@redhat.com)
- SubscriptionManager: minor logging fixes (rnovacek@redhat.com)
- SubscriptionManager: add env var to disable asynchronous reporting
  (rnovacek@redhat.com)
- Check jobs status in increasing interval (rnovacek@redhat.com)
- Esx: report host even if it doesn't have any guests (rnovacek@redhat.com)
- Hypervisors reported by hyperv now include hostname. (csnyder@redhat.com)
- Removes completed jobs. (csnyder@redhat.com)
- Fix output format in print mode (rnovacek@redhat.com)
- Fix using empty list as default parameter value (rnovacek@redhat.com)
- satellite: support new hypervisor format (rnovacek@redhat.com)
- Fix tests failures (rnovacek@redhat.com)
- Removes timeouts for jobs. All jobs in the list are now executed just before
  a new report is sent. (csnyder@redhat.com)
- The virtwho loop now blocks on the report queue with a one second timeout
  (csnyder@redhat.com)
- Removes unnecessary imports and queue (csnyder@redhat.com)
- Rewrite readme to markdown syntax (rnovacek@redhat.com)
- CI: install unittest2 from pypi (rnovacek@redhat.com)
- CI: add -y option to add-apt-repository (rnovacek@redhat.com)
- CI: another attempt on cloud archive for libvirt (rnovacek@redhat.com)
- CI: try to install newer version of libvirt from cloud archive
  (rnovacek@redhat.com)
- CI: add libvirt-dev dependency (rnovacek@redhat.com)
- CI: install libvirt-python via pip (rnovacek@redhat.com)
- CI: another attempt without site-packages (rnovacek@redhat.com)
- CI: install python-rhsm dependencies (rnovacek@redhat.com)
- Adds support for facts in Hypervisor profile. (csnyder@redhat.com)
- Adds count of unchanged mappings to the info logged for the result of an
  async job (csnyder@redhat.com)
- Adds tests for jobs in virtwho, removes unnecessary tests for managerprocess.
  (csnyder@redhat.com)
- Changes to ensure backwards compatibility with python-rhsm
  (csnyder@redhat.com)
- Fixes RhevM.getHostGuestMapping() as suggested by rnovacek
  (csnyder@redhat.com)
- Adds layer to hypervisorId. Removes completed TODO (csnyder@redhat.com)
- Moves all functionality of managerprocess into virtwho. (csnyder@redhat.com)
- CI: use python with system side packages enabled (rnovacek@redhat.com)
- CI: install m2crypto using apt instead of pip (rnovacek@redhat.com)
- CI: install python-libvirt using apt instead of pip (rnovacek@redhat.com)
- Add requirements.txt and .travis.yml for the CI (rnovacek@redhat.com)
- Adds tests to verify the hostGuestAssociation is generated correctly.
  (csnyder@redhat.com)
- Updates libvirtd and tests to add host name to hypervisor profile
  (csnyder@redhat.com)
- Updates managerprocess with better logging and changes for the new tests.~~
  (csnyder@redhat.com)
- Updates to use the new hypervisor class (csnyder@redhat.com)
- print mode: format debug message about found hypervisors
  (rnovacek@redhat.com)
- Removing uncesasary comments (csnyder@redhat.com)
- Removes unused dictionary of jobs and associated methods.
  (csnyder@redhat.com)
- Fixes tests data to include "status" key. (csnyder@redhat.com)
- Updates tests to make use of new Hypervisor class. (csnyder@redhat.com)
- Host name is now included in the hypervisor profile using the new Hypervisor
  class (csnyder@redhat.com)
- Adds new Hypervisor class. (csnyder@redhat.com)
- Adds new test for the updates to subscriptionmanager.py (csnyder@redhat.com)
- Updates fakevirt to make use of virt.Guest classes (csnyder@redhat.com)
- Changes to ensure proper execution post-merge (csnyder@redhat.com)
- Removing more unnecessary prints (csnyder@redhat.com)
- Fixes oneshot mode for work with new managerprocess (csnyder@redhat.com)
- Cleaning up unneeded prints and adding more useful debug log messages
  (csnyder@redhat.com)
- Adds async job status polling for use with the new report API
  (csnyder@redhat.com)
- This (along with python-rhsm/csnyder/new_report_api ee38f15, allows
  communication with new report api (csnyder@redhat.com)

* Tue Jun 23 2015 Radek Novacek <rnovacek@redhat.com> 0.14-1
- Version 0.14

* Tue Mar 17 2015 Radek Novacek <rnovacek@redhat.com> 0.13-1
- new package built with tito

* Fri Feb 27 2015 Radek Novacek <rnovacek@redhat.com> 0.12-1
- Version 0.12

* Mon Sep 08 2014 Radek Novacek <rnovacek@redhat.com> 0.11-1
- Version 0.11

* Tue May 20 2014 Radek Novacek <rnovacek@redhat.com> 0.10-1
- Add directory with configuration files
- Version 0.10

* Thu Mar 13 2014 Radek Novacek <rnovacek@redhat.com> 0.9-1
- Remove libvirt dependency
- Add dependency on m2crypto
- Version 0.9

* Fri Sep 14 2012 Radek Novacek <rnovacek@redhat.com> 0.8-1
- Version 0.8

* Mon Jul 09 2012 Radek Novacek <rnovacek@redhat.com> 0.7-1
- Version 0.7

* Mon Feb 13 2012 Radek Novacek <rnovacek@redhat.com> 0.6-1
- Version 0.6

* Fri Dec 09 2011 Radek Novacek <rnovacek@redhat.com> 0.5-1
- VSphere support
- Req: python-suds

* Wed Nov 30 2011 Radek Novacek <rnovacek@redhat.com> 0.4-1
- Version 0.4

* Thu Oct 06 2011 Radek Novacek <rnovacek@redhat.com> - 0.3-2
- Requires python-rhsm >= 0.96.13 (contains fix for char limit in uuid list)

* Thu Sep 01 2011 Radek Novacek <rnovacek@redhat.com> - 0.3-1
- Add initscript and configuration file

* Mon Aug 22 2011 Radek Novacek <rnovacek@redhat.com> - 0.2-1
- Update to upstream version 0.2
- Add Requires: libvirt

* Fri Aug 19 2011 Radek Novacek <rnovacek@redhat.com> - 0.1-2
- Add BuildRoot tag (the package will be in RHEL5)

* Wed Aug 10 2011 Radek Novacek <rnovacek@redhat.com> - 0.1-1
- initial import

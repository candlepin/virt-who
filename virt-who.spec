Name:           virt-who
Version:        0.1
Release:        1%{?dist}
Summary:        Agent for reporting virtual guest IDs to subscription-manager
Group:          System Environment/Base

License:        GPLv2+
URL:            https://fedorahosted.org/virt-who/
Source0:        https://fedorahosted.org/releases/v/i/virt-who/%{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python2-devel
Requires:       libvirt-python
Requires:       python-rhsm

%description
Agent that collects information about virtual guests present in the system and
report them to the subscription manager.

%prep
%setup -q


%build


%install
rm -rf $RPM_BUILD_ROOT

make DESTDIR=$RPM_BUILD_ROOT install

# Don't run test suite in check section, because it need the system to be
# registered to subscription-manager server

%clean
rm -rf $RPM_BUILD_ROOT


%files
%doc README LICENSE
%{_bindir}/virt-who
%{_datadir}/virt-who/


%changelog
* Wed Aug 10 2011 Radek Novacek <rnovacek@redhat.com> - 0.1-1
- initial import

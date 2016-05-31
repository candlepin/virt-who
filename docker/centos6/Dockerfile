FROM centos:6
MAINTAINER Radek Novacek <rnovacek@redhat.com>
RUN yum install -y libvirt-python python-suds m2crypto python-requests epel-release && \
    curl -L https://copr.fedoraproject.org/coprs/dgoodwin/subscription-manager/repo/epel-6/dgoodwin-subscription-manager-epel-6.repo > /etc/yum.repos.d/dgoodwin-subscription-manager-epel-6.repo && \
    yum install -y python-pip python-rhsm && \
    pip install -U pytest-timeout mock unittest2 setuptools && \
    yum clean all
COPY . /virt-who
WORKDIR /virt-who
CMD PYTHONPATH=. py.test --timeout=30

FROM centos:centos6.7
MAINTAINER Radek Novacek <rnovacek@redhat.com>
RUN yum update -y
RUN yum install -y libvirt-python python-suds m2crypto python-requests epel-release wget git
RUN wget https://copr.fedoraproject.org/coprs/dgoodwin/subscription-manager/repo/epel-6/dgoodwin-subscription-manager-epel-6.repo -O /etc/yum.repos.d/dgoodwin-subscription-manager-epel-6.repo
RUN yum install -y python-pip python-rhsm
RUN pip install -U pytest-timeout mock unittest2 setuptools
COPY . /virt-who
WORKDIR /virt-who
CMD PYTHONPATH=. py.test --timeout=30

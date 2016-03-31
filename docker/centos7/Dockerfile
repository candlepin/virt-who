FROM centos:centos7.2.1511
MAINTAINER Radek Novacek <rnovacek@redhat.com>
RUN yum update -y
RUN yum install -y libvirt-python python-suds m2crypto python-requests epel-release wget git python-rhsm
RUN yum install -y python-pip
RUN pip install -U pytest-timeout mock
COPY . /virt-who
WORKDIR /virt-who
CMD PYTHONPATH=. py.test --timeout=30

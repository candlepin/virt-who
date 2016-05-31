FROM centos:7
MAINTAINER Radek Novacek <rnovacek@redhat.com>
RUN yum install -y epel-release && \
    yum install -y libvirt-python python-suds m2crypto python-requests epel-release python-rhsm python-pip && \
    pip install -U pytest-timeout mock && \
    yum clean all
COPY . /virt-who
WORKDIR /virt-who
CMD PYTHONPATH=. py.test --timeout=30

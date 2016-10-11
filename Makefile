
name = virt-who
version = 0.18

.PHONY: pack check install srpm rpm rpmlint upload

release:
	tito tag

pack:
	tito build --tgz -o .

check:
	pyflakes *.py

install:
	python setup.py install

srpm:
	tito build --srpm --test

rpm:
	tito build --rpm --test

rpmlint:
	$(eval tmpdir := $(shell mktemp -d))
	tito build --srpm --test -o $(tmpdir)
	tito build --rpm --test -o $(tmpdir)
	rpmlint $(name).spec $(tmpdir)/*
	rm -rf $(tmpdir)

upload: pack
	scp $(name)-$(version).tar.gz fedorahosted.org:$(name)

test:
	PYTHONPATH=. py.test

testmon:
	PYTHONPATH=. ptw -- --testmon --timeout 5

coverage:
	PYTHONPATH=. py.test -k 'not complex' --cov=. --cov-report=html --cov-report=term --cov-config .coveragerc

test-ci-build:
	docker build -f docker/ci/Dockerfile -t virt-who/test-ci .

test-ci-shell: test-ci-build
	docker run -ti --rm virt-who/test-ci /bin/bash

test-ci: test-ci-build
	# Run the test suite on something similar to Travis-CI
	docker run --rm virt-who/test-ci

test-centos6-build:
	docker build -f docker/centos6/Dockerfile -t virt-who/test-centos6 .

test-centos6-shell: test-centos6-build
	docker run -ti --rm virt-who/test-centos6 /bin/bash

test-centos6: test-centos6-build
	# Run the test suite on centos-6
	docker run --rm virt-who/test-centos6

test-centos7-build:
	docker build -f docker/centos7/Dockerfile -t virt-who/test-centos7 .

test-centos7-shell: test-centos7-build
	docker run -ti --rm virt-who/test-centos7 /bin/bash

test-centos7: test-centos7-build
	# Run the test suite on centos-7
	docker run --rm virt-who/test-centos7

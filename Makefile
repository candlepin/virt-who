
name = virt-who
version = 0.14

.PHONY: pack check install srpm rpm rpmlint upload

release:
	tito tag

pack:
	tito build --tgz -o .

check:
	pyflakes *.py

install:
	for dir in {daemon,password,manager,virt} manager/{satellite,subscriptionmanager} virt/{esx,hyperv,libvirtd,rhevm,vdsm,fakevirt}; do \
	    echo $$dir ; \
	    install -d $(DESTDIR)/usr/share/$(name)/$$dir/ ; \
	    install -pm 0644 $$dir/*.py $(DESTDIR)/usr/share/$(name)/$$dir/ ; \
	done
	install -pm 0644 virt/esx/vimServiceMinimal.wsdl $(DESTDIR)/usr/share/$(name)/virt/esx/
	install -pm 0644 *.py $(DESTDIR)/usr/share/$(name)/
	install -d $(DESTDIR)/usr/bin $(DESTDIR)/etc/rc.d/init.d $(DESTDIR)/etc/sysconfig $(DESTDIR)/usr/share/man/man8/ $(DESTDIR)/usr/share/man/man5/ $(DESTDIR)/var/lib/virt-who/ $(DESTDIR)/etc/virt-who.d/
	install virt-who $(DESTDIR)/usr/bin/
	install virt-who-password $(DESTDIR)/usr/bin/
	install virt-who-initscript $(DESTDIR)/etc/rc.d/init.d/virt-who
	install -pm 0644 virt-who.conf $(DESTDIR)/etc/sysconfig/virt-who
	gzip -c virt-who.8 > virt-who.8.gz
	install -pm 0644 virt-who.8.gz $(DESTDIR)/usr/share/man/man8/
	gzip -c virt-who-password.8 > virt-who-password.8.gz
	install -pm 0644 virt-who-password.8.gz $(DESTDIR)/usr/share/man/man8/
	gzip -c virt-who-config.5 > virt-who-config.5.gz
	install -pm 0644 virt-who-config.5.gz $(DESTDIR)/usr/share/man/man5/
	install -pm 0644 template.conf $(DESTDIR)/etc/virt-who.d/
	install -pm 0644 template-general.conf $(DESTDIR)/etc/virt-who.conf

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

coverage:
	PYTHONPATH=. py.test --cov=. --cov-report=html --cov-report=term --cov-config .coveragerc

test-ci-build:
	docker build -f docker/ci/Dockerfile -t virt-who/test-ci .

test-ci-shell: test-ci-build
	docker run -ti virt-who/test-ci /bin/bash

test-ci: test-ci-build
	# Run the test suite on something similar to Travis-CI
	docker run virt-who/test-ci

test-centos6-build:
	docker build -f docker/centos6/Dockerfile -t virt-who/test-centos6 .

test-centos6-shell: test-centos6-build
	docker run -ti virt-who/test-centos6 /bin/bash

test-centos6: test-centos6-build
	# Run the test suite on centos-6
	docker run virt-who/test-centos6

test-centos7-build:
	docker build -f docker/centos7/Dockerfile -t virt-who/test-centos7 .

test-centos7-shell: test-centos7-build
	docker run -ti virt-who/test-centos7 /bin/bash

test-centos7: test-centos7-build
	# Run the test suite on centos-7
	docker run virt-who/test-centos7

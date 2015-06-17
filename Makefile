
name = virt-who
version = 0.12

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
	install -d $(DESTDIR)/usr/bin $(DESTDIR)/etc/rc.d/init.d $(DESTDIR)/etc/sysconfig $(DESTDIR)/usr/share/man/man8/ $(DESTDIR)/usr/share/man/man5/ $(DESTDIR)/var/lib/virt-who/
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

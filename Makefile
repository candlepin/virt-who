
name = virt-who
version = 0.8

.PHONY: pack check install srpm rpm rpmlint upload

$(name)-$(version).tar.gz:
	git archive --format=tar --prefix=$(name)-$(version)/ master | gzip > $(name)-$(version).tar.gz

pack: $(name)-$(version).tar.gz

check:
	pyflakes *.py

install:
	install -d $(DESTDIR)/usr/share/$(name)/ $(DESTDIR)/usr/bin $(DESTDIR)/etc/rc.d/init.d $(DESTDIR)/etc/sysconfig $(DESTDIR)/usr/share/man/man8/
	install -pm 0644 *.py $(DESTDIR)/usr/share/$(name)/
	install virt-who $(DESTDIR)/usr/bin/
	install virt-who-register-satellite $(DESTDIR)/usr/bin/
	install virt-who-initscript $(DESTDIR)/etc/rc.d/init.d/virt-who
	install -pm 0644 virt-who.conf $(DESTDIR)/etc/sysconfig/virt-who
	gzip -c virt-who.8 > virt-who.8.gz
	install -pm 0644 virt-who.8.gz $(DESTDIR)/usr/share/man/man8/

srpm: pack
	rpmbuild --define "_sourcedir $(PWD)" --define "_specdir $(PWD)" --define "_srcrpmdir $(PWD)" -bs $(name).spec

rpm: pack
	rpmbuild --define "_sourcedir $(PWD)" --define "_specdir $(PWD)" --define "_srcrpmdir $(PWD)" --define "_rpmdir $(PWD)" -bb $(name).spec

rpmlint: srpm rpm
	rpmlint $(name).spec $(shell rpmspec -q $(name).spec | sed 's/.noarch//').src.rpm noarch/$(shell rpmspec -q $(name).spec).rpm

upload: pack
	scp $(name)-$(version).tar.gz fedorahosted.org:$(name)

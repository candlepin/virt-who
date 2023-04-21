
name = virt-who
version = 0.18

.PHONY: pack install srpm rpm rpmlint

release:
	tito tag

pack:
	tito build --tgz -o .

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

test:
	PYTHONPATH=. py.test

coverage:
	PYTHONPATH=. py.test -k 'not complex' --cov=. --cov-report=html --cov-report=term --cov-config .coveragerc

stylish:
	PYTHONPATH=. flake8

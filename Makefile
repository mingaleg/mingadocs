.PHONY: install run migrate makemigrations shell test superuser lint ruff mypy pylint bandit

PYSRC := src/mingadocs/arnlabels src/mingadocs/scans src/mingadocs/siteconfig \
         src/mingadocs/config tools

install:
	poetry install

run:
	poetry run python manage.py runserver

migrate:
	poetry run python manage.py migrate

makemigrations:
	poetry run python manage.py makemigrations

shell:
	poetry run python manage.py shell

superuser:
	poetry run python manage.py createsuperuser

test:
	poetry run python manage.py test

# Static analysis. `make lint` runs all of them; config is in pyproject.toml.
lint: ruff mypy pylint bandit

ruff:
	poetry run ruff check src/mingadocs tools stubs

mypy:
	poetry run mypy src/mingadocs tools

pylint:
	poetry run pylint $(PYSRC)

bandit:
	poetry run bandit -c pyproject.toml -q -r src/mingadocs

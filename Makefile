.PHONY: install run migrate makemigrations shell test superuser

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

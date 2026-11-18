.PHONY: install run migrate makemigrations shell test test-with-actual-docs test-with-actual-docs-failed superuser lint ruff mypy pylint bandit

PYSRC := src/mingadocs/arnlabels src/mingadocs/scans src/mingadocs/siteconfig \
         src/mingadocs/config tools

install:
	uv sync

run:
	uv run python manage.py runserver

migrate:
	uv run python manage.py migrate

makemigrations:
	uv run python manage.py makemigrations

shell:
	uv run python manage.py shell

superuser:
	uv run python manage.py createsuperuser

test:
	uv run python manage.py test

# OCR regression tests against real scans in media/documents/ (not checked
# into git, so this only makes sense to run locally, never in CI). Excluded
# from `make test` and run on their own here.
test-with-actual-docs:
	MINGADOCS_TEST_ACTUAL_DOCS=1 uv run python manage.py test scans.test_actual_docs -v 2

# Fast inner loop while chasing a detection fix: only re-tries the (doc, page)
# pairs that failed on the last run (see .test_actual_docs_failures.json under
# MEDIA_ROOT) instead of the whole corpus. Run `test-with-actual-docs` once
# it's clean to confirm nothing else regressed.
test-with-actual-docs-failed:
	MINGADOCS_TEST_ACTUAL_DOCS=1 MINGADOCS_TEST_ACTUAL_DOCS_FAILED_ONLY=1 \
		uv run python manage.py test scans.test_actual_docs -v 2

# Static analysis. `make lint` runs all of them; config is in pyproject.toml.
lint: ruff mypy pylint bandit

ruff:
	uv run ruff check src/mingadocs tools stubs

mypy:
	uv run mypy src/mingadocs tools

pylint:
	uv run pylint $(PYSRC)

bandit:
	uv run bandit -c pyproject.toml -q -r src/mingadocs

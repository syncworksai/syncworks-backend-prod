import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "syncworksv7.settings")

import django  # noqa: E402
from django.conf import settings  # noqa: E402
from django.test.utils import setup_databases, setup_test_environment, teardown_databases, teardown_test_environment  # noqa: E402

django.setup()

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("testserver")

_DB_CFG = None


def pytest_configure(config):
    global _DB_CFG
    setup_test_environment()
    _DB_CFG = setup_databases(
        verbosity=0,
        interactive=False,
        keepdb=False,
        serialized_aliases=[],
    )


def pytest_unconfigure(config):
    if _DB_CFG is not None:
        teardown_databases(_DB_CFG, verbosity=0)
    teardown_test_environment()

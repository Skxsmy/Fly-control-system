"""Keep import-time database initialization away from personal records."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

_bootstrap = TemporaryDirectory(prefix='flykeeper-pytest-')
os.environ['FLYKEEPER_DB'] = str(Path(_bootstrap.name) / 'bootstrap.db')


def pytest_unconfigure(config):
    _bootstrap.cleanup()

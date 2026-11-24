"""SQLite bağlantısı ve şema kurulumu."""

import argparse
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / 'data/runtime/experiments.sqlite3'
SCHEMA = Path(__file__).with_name('schema.sql')


@contextmanager
def connect(path=DEFAULT_DATABASE):
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path=DEFAULT_DATABASE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        initialize_schema(connection)


def initialize_schema(connection):
    connection.executescript('BEGIN;\n' + SCHEMA.read_text(encoding='utf-8') + '\nCOMMIT;')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    initialize(args.path)


if __name__ == '__main__':
    main()

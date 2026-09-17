import os
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required.")
    return value


@contextmanager
def connection():
    with psycopg.connect(database_url()) as conn:
        register_vector(conn)
        yield conn
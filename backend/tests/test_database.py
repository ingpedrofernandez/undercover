from contextlib import asynccontextmanager

import anyio

from backend import database as db


def test_without_database_url_the_engine_is_sqlite(database):
    built = db.engine()
    assert built.url.drivername == "sqlite"
    assert built.url.database == str(database)


def test_with_database_url_the_engine_is_supabase(monkeypatch):
    options = {}
    real = db.create_engine

    def create_engine(url, **given):
        options.update(given)
        return real(url, **given)

    monkeypatch.setattr(db, "create_engine", create_engine)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.ref:secret@db.example.invalid:5432/postgres",
    )
    built = db.engine()
    assert built.url.drivername == "postgresql+psycopg"
    assert built.url.host == "db.example.invalid"
    assert options["pool_size"] == 4
    assert options["max_overflow"] == 0
    assert options["connect_args"] == {"options": "-c search_path=undercover"}


def test_at_most_four_requests_use_a_connection_at_once():
    using, most = 0, 0

    async def request():
        nonlocal using, most
        async with asynccontextmanager(db.connection_slot)():
            using += 1
            most = max(most, using)
            await anyio.sleep(0.01)
            using -= 1

    async def burst():
        async with anyio.create_task_group() as requests:
            for _ in range(10):
                requests.start_soon(request)

    anyio.run(burst)
    assert most == 4

"""Fixtures compartidos por los tests.

La idea: cada test corre contra una base de datos SQLite EN MEMORIA, nueva y
vacia, totalmente aislada de la BD real de desarrollo (`ommadawn.db`). Asi los
tests son reproducibles y no dejan basura.

Piezas:
  - `db_engine`: el engine de esa BD en memoria, compartido por un mismo test
    entre `client` y `db_session` (misma base fisica, StaticPool obliga).
  - `client`: un cliente HTTP asincrono (httpx) que habla con la app por ASGI,
    sin levantar ningun servidor real. Se le inyecta la sesion de BD de test
    sobreescribiendo la dependencia `get_session`.
  - `db_session`: una sesion suelta contra la MISMA base en memoria, para que un
    test pueda preparar estado que la API no expone (p. ej. promover un usuario
    a administrador: no hay, a proposito, un endpoint publico para eso).
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Engine de una BD SQLite en memoria, fresca por test.

    `StaticPool` + SQLite `:memory:` hace que todas las conexiones compartan la
    MISMA base en memoria (si no, cada conexion veria una BD distinta y vacia).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",  # sin ruta -> base de datos en memoria
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP contra la app, usando la BD en memoria del test."""
    session_maker = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():
        async with session_maker() as session:
            yield session

    # Redirigimos la dependencia real a la sesion de test.
    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Limpieza: quitamos el override (el engine lo cierra `db_engine`).
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Sesion suelta contra la misma BD en memoria que usa `client`.

    Para manipular datos que la API no expone (p. ej. marcar `is_admin=True`).
    """
    session_maker = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_maker() as session:
        yield session

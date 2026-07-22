"""Fixtures compartidos por los tests.

La idea: cada test corre contra una base de datos SQLite EN MEMORIA, nueva y
vacia, totalmente aislada de la BD real de desarrollo (`ommadawn.db`). Asi los
tests son reproducibles y no dejan basura.

Piezas:
  - `client`: un cliente HTTP asincrono (httpx) que habla con la app por ASGI,
    sin levantar ningun servidor real. Se le inyecta la sesion de BD de test
    sobreescribiendo la dependencia `get_session`.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP contra la app, con una BD en memoria fresca por test.

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

    session_maker = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():
        async with session_maker() as session:
            yield session

    # Redirigimos la dependencia real a la sesion de test.
    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Limpieza: quitamos el override y cerramos el engine.
    app.dependency_overrides.clear()
    await engine.dispose()

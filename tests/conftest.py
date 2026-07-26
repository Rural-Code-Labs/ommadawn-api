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

`client` tambien redirige el backend de almacenamiento (imagenes) a una carpeta
TEMPORAL de pytest, para que subir imagenes en los tests no escriba en la
carpeta real de desarrollo (`./media`).
"""

from collections.abc import AsyncGenerator
from pathlib import Path

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
from app.core.storage import LocalStorageBackend, get_storage_backend
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
async def client(
    db_engine: AsyncEngine, tmp_path: Path
) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP contra la app, usando la BD en memoria y un almacenamiento
    de imagenes temporal (ambos aislados de los datos reales de desarrollo)."""
    session_maker = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():
        async with session_maker() as session:
            yield session

    # Redirigimos las dependencias reales a las de test.
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
        media_root=str(tmp_path), media_base_url="http://testserver/media"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Limpieza: quitamos los overrides (el engine lo cierra `db_engine`; la
    # carpeta temporal la limpia pytest solo).
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

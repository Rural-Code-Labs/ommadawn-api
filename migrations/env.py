"""Configuracion del entorno de Alembic (variante async).

Este fichero es el "puente" entre Alembic y nuestra aplicacion. Hace dos cosas
importantes que lo separan del env.py que genera Alembic por defecto:

  1. La URL de la base de datos la lee de `Settings` (.env), NO del alembic.ini.
     Asi la app y las migraciones apuntan SIEMPRE a la misma BD sin duplicar la
     URL en dos sitios.
  2. Le da a Alembic el `metadata` con todas las tablas de la app, para que
     `alembic revision --autogenerate` compare los modelos contra la BD real.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

from app.core.config import get_settings
from app.core.database import Base

# Importar los modelos de cada modulo REGISTRA sus tablas en `Base.metadata`.
# Sin estos imports, autogenerate no "veria" las tablas y generaria migraciones
# vacias. Al anadir un modulo nuevo (discografia, conciertos...), importalo aqui.
from app.modules.auth import models as _auth_models  # noqa: F401

# Objeto de configuracion de Alembic (acceso a los valores de alembic.ini).
config = context.config

# Configura el logging de Python a partir del .ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Unica fuente de la URL: el .env, via Settings. (En alembic.ini la dejamos
# comentada a proposito para que no haya dos verdades.)
DATABASE_URL = get_settings().database_url

# Metadata con TODAS las tablas de la app: es lo que compara autogenerate.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Modo 'offline': genera el SQL sin conectarse a la base de datos.

    Util para producir un script .sql y aplicarlo a mano. Aqui solo hace falta
    la URL, no una conexion real.
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configura el contexto con una conexion ya abierta y corre las migraciones."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Modo 'online' async: abre una conexion real y aplica las migraciones.

    Creamos el engine directamente desde la URL de Settings (en vez de leerlo del
    .ini). `NullPool`: no mantenemos pool; la migracion abre, trabaja y cierra.
    """
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Punto de entrada del modo online: arranca el bucle async."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

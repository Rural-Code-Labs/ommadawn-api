"""Punto de entrada de la aplicacion FastAPI.

Responsabilidades de este fichero (y solo estas):
  - Crear la instancia de FastAPI.
  - Gestionar el ciclo de vida (arranque / apagado) con `lifespan`.
  - Montar los routers de cada modulo bajo el prefijo de version /api/v1.

La logica de negocio NO vive aqui: vive en cada modulo (app/modules/*).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import Base, engine

# Importamos los modelos para que se registren en Base.metadata. Sin este
# import, `create_all` (y Alembic) no "verian" las tablas `users`/`refresh_tokens`.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.auth.router import router as auth_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Codigo que corre al arrancar y al apagar el servidor.

    En DESARROLLO creamos las tablas automaticamente a partir de los modelos.
    En PRODUCCION esto se sustituye por migraciones Alembic (el esquema no se
    crea "magicamente", se versiona).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # (aqui iria codigo de limpieza al apagar, si hiciera falta)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Endpoint simple para comprobar que la API esta viva."""
    return {"status": "ok"}


# --- Routers de los modulos ---
# Cada modulo cuelga de /api/v1. El router de auth anade su propio /auth, asi que
# sus rutas finales son /api/v1/auth/...
app.include_router(auth_router, prefix="/api/v1")

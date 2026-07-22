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

# Descripcion que se muestra en la cabecera de /docs y /redoc. Admite Markdown.
API_DESCRIPTION = """
API REST que cataloga la obra de **Mike Oldfield**: discografia, conciertos,
libros y mas. Pensada para consumirse desde una app movil (iOS y, en el futuro,
Android).

## Autenticacion

Se usa **JWT** con dos tokens:

* **access token** — corto (~15 min), se envia en cada peticion como
  `Authorization: Bearer <token>`.
* **refresh token** — largo (~30 dias), rotativo y revocable. Sirve para obtener
  un access token nuevo cuando el anterior caduca.

Los endpoints marcados con un candado requieren un access token valido.
"""

# Descripcion de cada grupo de endpoints (los "tags") en la documentacion.
TAGS_METADATA = [
    {
        "name": "auth",
        "description": "Registro, inicio de sesion y gestion de la sesion (tokens).",
    },
    {
        "name": "health",
        "description": "Comprobacion de que el servicio esta vivo.",
    },
]


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
    summary="Catalogo de la obra de Mike Oldfield.",
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
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

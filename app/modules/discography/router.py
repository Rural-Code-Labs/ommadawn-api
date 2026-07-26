"""Router del modulo de discografia: define los endpoints HTTP.

Prefijo: se monta bajo `/api/v1` en `main.py`, y este router anade `/discography`,
asi que las rutas finales son `/api/v1/discography/releases...`.

Tres niveles, igual que el modelo: `Release` (la obra) -> `Edition` (una
publicacion concreta, anidada bajo su obra) -> `Track` (dentro del body de
cada edicion, no tiene endpoints propios).

Leer el catalogo (listar, ver detalle) es PUBLICO: es el proposito de la app.
Escribir (crear/editar/borrar obras y ediciones) exige ser ADMINISTRADOR.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ErrorMessage
from app.modules.auth.dependencies import require_admin
from app.modules.auth.models import User
from app.modules.discography import service
from app.modules.discography.models import Edition, Release, ReleaseType
from app.modules.discography.schemas import (
    EditionCreate,
    EditionRead,
    EditionUpdate,
    ReleaseCreate,
    ReleaseRead,
    ReleaseUpdate,
)

router = APIRouter(prefix="/discography", tags=["discography"])

_NOT_FOUND = {"model": ErrorMessage, "description": "La publicacion no existe"}
_EDITION_NOT_FOUND = {
    "model": ErrorMessage,
    "description": "La edicion no existe (o no pertenece a esa publicacion)",
}
_NO_AUTH = {
    "model": ErrorMessage,
    "description": "Falta el access token o no es valido",
}
_FORBIDDEN = {
    "model": ErrorMessage,
    "description": "El usuario esta autenticado pero no es administrador",
}
_INVALID_TRACKS = {
    "model": ErrorMessage,
    "description": "Datos invalidos (p. ej. dos temas con la misma posicion)",
}


# --- Release (la obra) ------------------------------------------------------------


@router.get(
    "/releases",
    response_model=list[ReleaseRead],
    summary="Listar obras del catalogo",
)
async def list_releases(
    release_type: ReleaseType | None = Query(
        default=None,
        alias="type",
        description="Filtra por tipo: studio, compilation, single o bootleg",
    ),
    session: AsyncSession = Depends(get_session),
) -> list[Release]:
    """Lista obras (discos, recopilatorios, singles, bootlegs...) con sus ediciones."""
    return await service.list_releases(session, release_type=release_type)


@router.get(
    "/releases/{release_id}",
    response_model=ReleaseRead,
    summary="Detalle de una obra (con todas sus ediciones y temas)",
    responses={status.HTTP_404_NOT_FOUND: _NOT_FOUND},
)
async def get_release(
    release_id: int, session: AsyncSession = Depends(get_session)
) -> Release:
    """Devuelve una obra con sus ediciones, o 404 si no existe."""
    return await service.get_release(session, release_id)


@router.post(
    "/releases",
    response_model=ReleaseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Anadir una obra al catalogo (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
    },
)
async def create_release(
    data: ReleaseCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Release:
    """Crea una obra (titulo + tipo). Sus ediciones se anaden por separado."""
    return await service.create_release(session, data)


@router.patch(
    "/releases/{release_id}",
    response_model=ReleaseRead,
    summary="Editar una obra (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
    },
)
async def update_release(
    release_id: int,
    data: ReleaseUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Release:
    """Edita los campos presentes en el body (titulo y/o tipo)."""
    return await service.update_release(session, release_id, data)


@router.delete(
    "/releases/{release_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una obra (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
    },
)
async def delete_release(
    release_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Borra una obra, sus ediciones y sus temas."""
    await service.delete_release(session, release_id)


# --- Edition (una publicacion concreta de la obra) --------------------------------


@router.post(
    "/releases/{release_id}/editions",
    response_model=EditionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Anadir una edicion a una obra (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_TRACKS,
    },
)
async def create_edition(
    release_id: int,
    data: EditionCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Edition:
    """Crea una edicion (con su tracklist) para una obra existente."""
    return await service.create_edition(session, release_id, data)


@router.patch(
    "/releases/{release_id}/editions/{edition_id}",
    response_model=EditionRead,
    summary="Editar una edicion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _EDITION_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_TRACKS,
    },
)
async def update_edition(
    release_id: int,
    edition_id: int,
    data: EditionUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Edition:
    """Edita los campos presentes en el body. Si incluye `tracks`, los reemplaza."""
    return await service.update_edition(session, release_id, edition_id, data)


@router.delete(
    "/releases/{release_id}/editions/{edition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una edicion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _EDITION_NOT_FOUND,
    },
)
async def delete_edition(
    release_id: int,
    edition_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Borra una edicion y sus temas."""
    await service.delete_edition(session, release_id, edition_id)

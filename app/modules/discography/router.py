"""Router del modulo de discografia: define los endpoints HTTP.

Prefijo: se monta bajo `/api/v1` en `main.py`, y este router anade `/discography`,
asi que las rutas finales son `/api/v1/discography/releases...`.

Leer el catalogo (listar, ver detalle) es PUBLICO: es el proposito de la app.
Escribir (anadir una publicacion) exige ser ADMINISTRADOR: solo el equipo cura
el contenido, no cualquier usuario registrado.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ErrorMessage
from app.modules.auth.dependencies import require_admin
from app.modules.auth.models import User
from app.modules.discography import service
from app.modules.discography.models import Release, ReleaseType
from app.modules.discography.schemas import ReleaseCreate, ReleaseRead, ReleaseUpdate

router = APIRouter(prefix="/discography", tags=["discography"])

_NOT_FOUND = {"model": ErrorMessage, "description": "La publicacion no existe"}
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


@router.get(
    "/releases",
    response_model=list[ReleaseRead],
    summary="Listar publicaciones del catalogo",
)
async def list_releases(
    release_type: ReleaseType | None = Query(
        default=None,
        alias="type",
        description="Filtra por tipo: studio, compilation, single o bootleg",
    ),
    session: AsyncSession = Depends(get_session),
) -> list[Release]:
    """Lista publicaciones (discos, recopilatorios, singles, bootlegs...).

    Sin filtro devuelve todo el catalogo, ordenado cronologicamente.
    """
    return await service.list_releases(session, release_type=release_type)


@router.get(
    "/releases/{release_id}",
    response_model=ReleaseRead,
    summary="Detalle de una publicacion (con su lista de temas)",
    responses={status.HTTP_404_NOT_FOUND: _NOT_FOUND},
)
async def get_release(
    release_id: int, session: AsyncSession = Depends(get_session)
) -> Release:
    """Devuelve una publicacion con sus temas, o 404 si no existe."""
    return await service.get_release(session, release_id)


@router.post(
    "/releases",
    response_model=ReleaseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Anadir una publicacion al catalogo (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_TRACKS,
    },
)
async def create_release(
    data: ReleaseCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Release:
    """Crea una publicacion (con su tracklist) y la devuelve.

    `_admin`: solo se usa para exigir el permiso; no se necesita su valor.
    """
    return await service.create_release(session, data)


@router.patch(
    "/releases/{release_id}",
    response_model=ReleaseRead,
    summary="Editar una publicacion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_TRACKS,
    },
)
async def update_release(
    release_id: int,
    data: ReleaseUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Release:
    """Edita los campos presentes en el body.

    Si el body incluye `tracks`, reemplaza toda la tracklist existente.
    """
    return await service.update_release(session, release_id, data)


@router.delete(
    "/releases/{release_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una publicacion (requiere administrador)",
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
    """Borra una publicacion y sus temas."""
    await service.delete_release(session, release_id)

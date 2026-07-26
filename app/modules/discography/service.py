"""Logica de negocio del modulo de discografia.

Igual que en auth: el `service` es quien toca la base de datos y quien lanza los
errores de negocio (p. ej. "no existe"). No sabe nada de HTTP mas alla de
reutilizar `HTTPException`, igual que hace `core/exceptions.py`.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.discography.models import Release, ReleaseType, Track
from app.modules.discography.schemas import ReleaseCreate

# 404 -> la publicacion pedida no existe. Es especifico de este modulo (no vive
# en core/exceptions.py, que es para lo verdaderamente transversal).
release_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Publicacion no encontrada",
)


async def list_releases(
    session: AsyncSession, release_type: ReleaseType | None = None
) -> list[Release]:
    """Lista publicaciones del catalogo, opcionalmente filtradas por tipo.

    `selectinload(Release.tracks)` precarga los temas en una segunda consulta
    (batch), evitando una consulta N+1 (una por publicacion) al serializar
    `tracks` en la respuesta.
    """
    query = select(Release).options(selectinload(Release.tracks))
    if release_type is not None:
        query = query.where(Release.release_type == release_type)
    # Orden cronologico: lo natural para explorar una discografia. Las fechas
    # nulas (bootlegs sin fecha conocida) quedan al final en Postgres (su
    # comportamiento por defecto); no se fuerza mas que eso por ahora.
    query = query.order_by(Release.release_date, Release.title)

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_release(session: AsyncSession, release_id: int) -> Release:
    """Busca una publicacion por id (con sus temas). Lanza 404 si no existe."""
    result = await session.execute(
        select(Release)
        .options(selectinload(Release.tracks))
        .where(Release.id == release_id)
    )
    release = result.scalar_one_or_none()
    if release is None:
        raise release_not_found_exception
    return release


async def create_release(session: AsyncSession, data: ReleaseCreate) -> Release:
    """Crea una publicacion junto con sus temas, en una unica transaccion.

    Construir los `Track` como parte del objeto `Release` (en vez de anadirlos a
    la sesion por separado) hace que un solo `commit` persista todo junto: si
    algo fallara, no queda una publicacion a medias sin sus temas.
    """
    release = Release(
        title=data.title,
        release_type=data.release_type,
        release_date=data.release_date,
        tracks=[
            Track(
                position=track.position,
                title=track.title,
                duration_seconds=track.duration_seconds,
            )
            for track in data.tracks
        ],
    )
    session.add(release)
    await session.commit()
    await session.refresh(release, attribute_names=["tracks"])
    return release

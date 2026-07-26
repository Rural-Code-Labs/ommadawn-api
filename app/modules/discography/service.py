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
from app.modules.discography.schemas import ReleaseCreate, ReleaseUpdate

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


async def update_release(
    session: AsyncSession, release_id: int, data: ReleaseUpdate
) -> Release:
    """Edita una publicacion. Solo toca los campos presentes en el body.

    `model_dump(exclude_unset=True)` es la clave: distingue un campo OMITIDO (no
    se toca) de uno enviado como `null` (se aplica de verdad, p. ej. borrar una
    `release_date` incierta). Si el body incluye `tracks`, se reemplaza la
    coleccion entera; gracias a `cascade="all, delete-orphan"` en el modelo,
    reasignarla borra los temas viejos y crea los nuevos en el mismo commit.
    """
    release = await get_release(session, release_id)
    updates = data.model_dump(exclude_unset=True)

    if "tracks" in updates:
        tracks_data = updates.pop("tracks")
        # Vaciar y hacer FLUSH antes de anadir los nuevos: si no, SQLAlchemy
        # puede emitir los INSERT antes que los DELETE de los temas viejos y
        # chocar con el UNIQUE(release_id, position) cuando se repite un numero
        # de pista entre la tracklist vieja y la nueva.
        release.tracks = []
        await session.flush()
        release.tracks = [Track(**track) for track in tracks_data]

    for field, value in updates.items():
        setattr(release, field, value)

    await session.commit()
    await session.refresh(release, attribute_names=["tracks"])
    return release


async def delete_release(session: AsyncSession, release_id: int) -> None:
    """Borra una publicacion y sus temas (CASCADE, tanto en el ORM como en la FK)."""
    release = await get_release(session, release_id)
    await session.delete(release)
    await session.commit()

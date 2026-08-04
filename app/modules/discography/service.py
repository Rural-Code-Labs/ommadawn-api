"""Logica de negocio del modulo de discografia.

Igual que en auth: el `service` es quien toca la base de datos y quien lanza los
errores de negocio (p. ej. "no existe"). No sabe nada de HTTP mas alla de
reutilizar `HTTPException`, igual que hace `core/exceptions.py`.
"""

from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.storage import StorageBackend, validate_image_upload
from app.modules.discography.models import Edition, Image, ImageType, Release, ReleaseType, Track
from app.modules.discography.schemas import (
    EditionCreate,
    EditionUpdate,
    ReleaseCreate,
    ReleaseUpdate,
)

# 404 -> la obra, la edicion o la imagen pedida no existe. Especificos de este
# modulo (no viven en core/exceptions.py, que es para lo verdaderamente
# transversal).
release_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Publicacion no encontrada",
)
edition_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Edicion no encontrada",
)
image_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Imagen no encontrada",
)

# Carga en cadena: las ediciones de un Release, y los temas/imagenes de cada
# edicion, en consultas batch (evita una consulta N+1 por nivel al serializar).
_RELEASE_WITH_EDITIONS = (
    selectinload(Release.editions).selectinload(Edition.tracks),
    selectinload(Release.editions).selectinload(Edition.images),
)
_EDITION_WITH_CHILDREN = (
    selectinload(Edition.tracks),
    selectinload(Edition.images),
)


# --- Release (la obra) -----------------------------------------------------------


async def list_releases(
    session: AsyncSession, release_type: ReleaseType | None = None
) -> list[Release]:
    """Lista obras del catalogo, opcionalmente filtradas por tipo."""
    query = select(Release).options(*_RELEASE_WITH_EDITIONS)
    if release_type is not None:
        query = query.where(Release.release_type == release_type)
    query = query.order_by(Release.title)

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_release(session: AsyncSession, release_id: int) -> Release:
    """Busca una obra por id (con sus ediciones, temas e imagenes). Lanza 404 si no existe."""
    result = await session.execute(
        select(Release)
        .options(*_RELEASE_WITH_EDITIONS)
        .where(Release.id == release_id)
    )
    release = result.scalar_one_or_none()
    if release is None:
        raise release_not_found_exception
    return release


async def create_release(session: AsyncSession, data: ReleaseCreate) -> Release:
    """Crea una obra (sin ediciones todavia; se anaden con create_edition)."""
    release = Release(title=data.title, release_type=data.release_type, description=data.description)
    session.add(release)
    await session.commit()
    await session.refresh(release, attribute_names=["editions"])
    return release


async def update_release(
    session: AsyncSession, release_id: int, data: ReleaseUpdate
) -> Release:
    """Edita una obra. Solo toca los campos presentes en el body (PATCH real)."""
    release = await get_release(session, release_id)
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(release, field, value)

    await session.commit()
    await session.refresh(release, attribute_names=["editions"])
    return release


async def delete_release(session: AsyncSession, release_id: int) -> None:
    """Borra una obra, sus ediciones y sus temas (CASCADE)."""
    release = await get_release(session, release_id)
    await session.delete(release)
    await session.commit()


# --- Edition (una publicacion concreta de la obra) -------------------------------


async def _get_edition(session: AsyncSession, release_id: int, edition_id: int) -> Edition:
    """Busca una edicion QUE PERTENEZCA a `release_id`. Lanza 404 si no cuadra.

    Comprobar `release_id` ademas del id de la edicion evita que, manipulando la
    URL, alguien edite/borre una edicion de OTRA obra pasando un release_id que
    no le corresponde.
    """
    result = await session.execute(
        select(Edition)
        .options(*_EDITION_WITH_CHILDREN)
        .where(Edition.id == edition_id, Edition.release_id == release_id)
    )
    edition = result.scalar_one_or_none()
    if edition is None:
        raise edition_not_found_exception
    return edition


async def _demote_other_primary_editions(
    session: AsyncSession, release_id: int, exclude_edition_id: int | None = None
) -> None:
    """Quita `is_primary` a las demas ediciones de la misma obra.

    Se llama ANTES de marcar una edicion como principal, para que "fijar la
    principal" sea un simple intercambio (la anterior se desmarca sola) en vez
    de un error por violar el indice unico parcial `uq_editions_release_primary`.
    """
    query = select(Edition).where(
        Edition.release_id == release_id, Edition.is_primary.is_(True)
    )
    if exclude_edition_id is not None:
        query = query.where(Edition.id != exclude_edition_id)

    result = await session.execute(query)
    for edition in result.scalars().all():
        edition.is_primary = False


async def create_edition(
    session: AsyncSession, release_id: int, data: EditionCreate
) -> Edition:
    """Anade una edicion (con su tracklist) a una obra existente."""
    await get_release(session, release_id)  # 404 si la obra no existe

    if data.is_primary:
        await _demote_other_primary_editions(session, release_id)

    edition = Edition(
        release_id=release_id,
        country=data.country,
        label=data.label,
        edition_name=data.edition_name,
        catalog_number=data.catalog_number,
        release_date=data.release_date,
        format=data.format,
        credits=data.credits,
        notes=data.notes,
        is_primary=data.is_primary,
        tracks=[
            Track(
                position=track.position,
                title=track.title,
                duration_seconds=track.duration_seconds,
            )
            for track in data.tracks
        ],
    )
    session.add(edition)
    await session.commit()
    await session.refresh(edition, attribute_names=["tracks", "images"])
    return edition


async def update_edition(
    session: AsyncSession, release_id: int, edition_id: int, data: EditionUpdate
) -> Edition:
    """Edita una edicion. Solo toca los campos presentes en el body (PATCH real)."""
    edition = await _get_edition(session, release_id, edition_id)
    updates = data.model_dump(exclude_unset=True)

    if updates.get("is_primary") is True:
        await _demote_other_primary_editions(
            session, release_id, exclude_edition_id=edition_id
        )

    if "tracks" in updates:
        tracks_data = updates.pop("tracks")
        # Vaciar y hacer FLUSH antes de anadir los nuevos: si no, SQLAlchemy
        # puede emitir los INSERT antes que los DELETE de los temas viejos y
        # chocar con el UNIQUE(edition_id, position) cuando se repite un numero
        # de pista entre la tracklist vieja y la nueva.
        edition.tracks = []
        await session.flush()
        edition.tracks = [Track(**track) for track in tracks_data]

    for field, value in updates.items():
        setattr(edition, field, value)

    await session.commit()
    await session.refresh(edition, attribute_names=["tracks", "images"])
    return edition


async def delete_edition(session: AsyncSession, release_id: int, edition_id: int) -> None:
    """Borra una edicion y sus temas (CASCADE)."""
    edition = await _get_edition(session, release_id, edition_id)
    await session.delete(edition)
    await session.commit()


# --- Image (portada, contraportada... de una edicion) ----------------------------


async def upload_image(
    session: AsyncSession,
    storage: StorageBackend,
    release_id: int,
    edition_id: int,
    image_type: ImageType,
    content: bytes,
    content_type: str,
) -> Image:
    """Sube una imagen y la asocia a una edicion.

    `front_cover`/`back_cover` SUSTITUYEN la anterior de su mismo tipo (se borra
    la fila y el fichero viejo): asi el admin no acumula portadas sueltas, basta
    con volver a subir para "reemplazar". `other` se acumula sin limite.

    La posicion se asigna automaticamente:
    - Imagen nueva: max(posiciones existentes) + 1.
    - Reemplazo de front_cover/back_cover: hereda la posicion de la imagen
      sustituida, para que no salte al final de la lista.
    """
    edition = await _get_edition(session, release_id, edition_id)

    extension = validate_image_upload(content, content_type)

    inherited_position: int | None = None
    if image_type != ImageType.OTHER:
        previous = [img for img in edition.images if img.image_type == image_type]
        for old_image in previous:
            inherited_position = old_image.position
            await storage.delete(old_image.url)
            await session.delete(old_image)
        if previous:
            await session.flush()

    if inherited_position is not None:
        position = inherited_position
    elif edition.images:
        position = max(img.position for img in edition.images) + 1
    else:
        position = 1

    url = await storage.save(filename=f"{uuid4().hex}{extension}", content=content)

    image = Image(edition_id=edition_id, image_type=image_type, url=url, position=position)
    session.add(image)
    await session.commit()
    await session.refresh(image)
    return image


async def move_image(
    session: AsyncSession,
    release_id: int,
    edition_id: int,
    image_id: int,
    direction: str,
) -> list[Image]:
    """Mueve una imagen un puesto arriba o abajo dentro de su edicion.

    Intercambia la posicion con la imagen adyacente (ordenadas por position).
    Devuelve la lista completa de imagenes de la edicion en el nuevo orden.
    Lanza 400 si la imagen ya esta en el extremo correspondiente.
    """
    edition = await _get_edition(session, release_id, edition_id)
    sorted_images = sorted(edition.images, key=lambda img: img.position)

    image = next((img for img in sorted_images if img.id == image_id), None)
    if image is None:
        raise image_not_found_exception

    idx = sorted_images.index(image)

    if direction == "up":
        if idx == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La imagen ya esta en la primera posicion",
            )
        neighbor = sorted_images[idx - 1]
    else:
        if idx == len(sorted_images) - 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La imagen ya esta en la ultima posicion",
            )
        neighbor = sorted_images[idx + 1]

    image.position, neighbor.position = neighbor.position, image.position
    await session.commit()
    await session.refresh(edition, attribute_names=["images"])
    return sorted(edition.images, key=lambda img: img.position)


async def delete_image(
    session: AsyncSession,
    storage: StorageBackend,
    release_id: int,
    edition_id: int,
    image_id: int,
) -> None:
    """Borra una imagen: la fila y el fichero subyacente."""
    edition = await _get_edition(session, release_id, edition_id)
    image = next((img for img in edition.images if img.id == image_id), None)
    if image is None:
        raise image_not_found_exception

    await storage.delete(image.url)
    await session.delete(image)
    await session.commit()

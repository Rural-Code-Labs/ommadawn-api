"""Logica de negocio del modulo de discografia.

Igual que en auth: el `service` es quien toca la base de datos y quien lanza los
errores de negocio (p. ej. "no existe"). No sabe nada de HTTP mas alla de
reutilizar `HTTPException`, igual que hace `core/exceptions.py`.
"""

from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.storage import StorageBackend, validate_image_upload
from app.modules.discography.models import (
    Collection,
    Edition,
    Image,
    ImageType,
    Label,
    Recording,
    Release,
    ReleaseType,
    Track,
    collection_editions,
)
from app.modules.discography.schemas import (
    CollectionCreate,
    CollectionDetailRead,
    CollectionEditionRead,
    CollectionListRead,
    CollectionUpdate,
    EditionCreate,
    EditionUpdate,
    LabelRead,
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
recording_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Grabacion no encontrada",
)
label_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Sello no encontrado",
)
collection_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Coleccion no encontrada",
)

# Carga en cadena: ediciones de un Release, y temas/imagenes/recordings de cada
# edicion, en consultas batch (evita N+1 por nivel al serializar).
_RELEASE_WITH_EDITIONS = (
    selectinload(Release.editions).selectinload(Edition.tracks).selectinload(Track.recording),
    selectinload(Release.editions).selectinload(Edition.images),
    selectinload(Release.editions).selectinload(Edition.label),
    selectinload(Release.editions).selectinload(Edition.collections),
)
_EDITION_WITH_CHILDREN = (
    selectinload(Edition.tracks).selectinload(Track.recording),
    selectinload(Edition.images),
    selectinload(Edition.label),
    selectinload(Edition.collections),
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


# --- Consulta para OTROS modulos (via esta capa de service, nunca los modelos) ---


async def release_exists(session: AsyncSession, release_id: int) -> bool:
    """Comprueba si existe una obra con ese id, sin cargar sus ediciones.

    Pensada para que OTROS modulos (p. ej. el foro, al validar a que
    `entity_id` se refiere un hilo) puedan comprobar la existencia sin
    importar `Release` ni consultar `releases` directamente -- mismo criterio
    de fronteras entre modulos que `auth.service.get_users_by_ids`. Mas
    liviana que `get_release`: no necesita la carga en cadena de ediciones
    para una simple comprobacion de existencia.
    """
    return await session.get(Release, release_id) is not None


async def edition_exists(session: AsyncSession, edition_id: int) -> bool:
    """Comprueba si existe una edicion con ese id (de cualquier obra), sin
    cargar sus temas/imagenes. Mismo motivo que `release_exists`."""
    return await session.get(Edition, edition_id) is not None


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


async def _build_tracks(session: AsyncSession, tracks_data: list) -> list[Track]:
    """Construye objetos Track a partir de TrackCreate.

    Valida que los recording_id referenciados existen antes de insertar,
    y crea Recording nuevos en linea para los temas sin recording_id.
    """
    result = []
    for t in tracks_data:
        if t.recording_id is not None:
            rec = await session.get(Recording, t.recording_id)
            if rec is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"recording_id {t.recording_id} no existe",
                )
            result.append(Track(
                recording_id=t.recording_id,
                position=t.position,
                disc_number=t.disc_number,
                side=t.side,
            ))
        else:
            result.append(Track(
                recording=Recording(
                    title=t.title,
                    duration_seconds=t.duration_seconds,
                    credits=t.credits,
                ),
                position=t.position,
                disc_number=t.disc_number,
                side=t.side,
            ))
    return result


async def create_edition(
    session: AsyncSession, release_id: int, data: EditionCreate
) -> Edition:
    """Anade una edicion (con su tracklist) a una obra existente."""
    await get_release(session, release_id)  # 404 si la obra no existe

    if data.is_primary:
        await _demote_other_primary_editions(session, release_id)

    if data.label_id is not None:
        await _get_label_or_404(session, data.label_id)  # 404 si el sello no existe

    tracks = await _build_tracks(session, data.tracks)
    edition = Edition(
        release_id=release_id,
        country=data.country,
        label_id=data.label_id,
        edition_name=data.edition_name,
        catalog_number=data.catalog_number,
        release_date=data.release_date,
        format=data.format,
        credits=data.credits,
        notes=data.notes,
        is_primary=data.is_primary,
        tracks=tracks,
    )
    session.add(edition)
    await session.commit()
    await session.refresh(edition, attribute_names=["tracks", "images", "label", "collections"])
    return edition


async def update_edition(
    session: AsyncSession, release_id: int, edition_id: int, data: EditionUpdate
) -> Edition:
    """Edita una edicion. Solo toca los campos presentes en el body (PATCH real)."""
    edition = await _get_edition(session, release_id, edition_id)
    updates = data.model_dump(exclude_unset=True)

    # Un label_id enviado (y no nulo) tiene que existir; null = quitar el sello.
    if updates.get("label_id") is not None:
        await _get_label_or_404(session, updates["label_id"])

    if updates.get("is_primary") is True:
        await _demote_other_primary_editions(
            session, release_id, exclude_edition_id=edition_id
        )

    if "tracks" in updates:
        tracks_data = updates.pop("tracks")
        # Vaciar y hacer FLUSH antes de anadir los nuevos: si no, SQLAlchemy
        # puede emitir los INSERT antes que los DELETE de los temas viejos y
        # chocar con los indices UNIQUE cuando se repite una posicion.
        edition.tracks = []
        await session.flush()
        from app.modules.discography.schemas import TrackCreate
        edition.tracks = await _build_tracks(
            session,
            [TrackCreate(**track) for track in tracks_data],
        )

    for field, value in updates.items():
        setattr(edition, field, value)

    await session.commit()
    await session.refresh(edition, attribute_names=["tracks", "images", "label", "collections"])
    return edition


async def delete_edition(session: AsyncSession, release_id: int, edition_id: int) -> None:
    """Borra una edicion y sus temas (CASCADE)."""
    edition = await _get_edition(session, release_id, edition_id)
    await session.delete(edition)
    await session.commit()


# --- Label (sello discografico) --------------------------------------------------


_duplicate_label_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Ya existe un sello con ese nombre",
)


async def _get_label_or_404(session: AsyncSession, label_id: int) -> Label:
    label = await session.get(Label, label_id)
    if label is None:
        raise label_not_found_exception
    return label


async def list_labels(session: AsyncSession, q: str | None = None) -> list["LabelRead"]:
    """Lista sellos con su numero de ediciones; orden: edition_count DESC, nombre ASC."""
    count_col = func.count(Edition.id).label("edition_count")
    query = (
        select(Label, count_col)
        .outerjoin(Edition, Edition.label_id == Label.id)
        .group_by(Label.id)
        .order_by(count_col.desc(), Label.name.asc())
    )
    if q:
        query = query.where(Label.name.ilike(f"%{q}%"))
    rows = (await session.execute(query)).all()
    return [
        LabelRead(id=label.id, name=label.name, notes=label.notes, edition_count=count)
        for label, count in rows
    ]


async def create_label(session: AsyncSession, data: "LabelCreate") -> Label:
    """Crea un sello. Lanza 409 si el nombre ya existe (sin distinguir mayusculas)."""
    from sqlalchemy.exc import IntegrityError

    label = Label(name=data.name.strip(), notes=data.notes)
    session.add(label)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_label_exception
    await session.refresh(label)
    return label


async def update_label(
    session: AsyncSession, label_id: int, data: "LabelUpdate"
) -> Label:
    """Edita un sello. Solo toca los campos presentes en el body (PATCH real)."""
    from sqlalchemy.exc import IntegrityError

    label = await _get_label_or_404(session, label_id)
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    for field, value in updates.items():
        setattr(label, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_label_exception
    await session.refresh(label)
    return label


async def delete_label(session: AsyncSession, label_id: int) -> None:
    """Borra un sello. Lanza 409 si alguna edicion lo sigue usando."""
    label = await _get_label_or_404(session, label_id)
    in_use = await session.scalar(
        select(Edition.id).where(Edition.label_id == label_id).limit(1)
    )
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede borrar: el sello esta en uso en una o mas ediciones",
        )
    await session.delete(label)
    await session.commit()


# --- Recording (grabacion real de un tema, compartible entre ediciones) ----------


async def delete_recording(session: AsyncSession, recording_id: int) -> None:
    """Borra una grabacion. Lanza 409 si sigue referenciada por algun Track."""
    recording = await session.get(Recording, recording_id)
    if recording is None:
        raise recording_not_found_exception
    in_use = await session.scalar(
        select(Track.id).where(Track.recording_id == recording_id).limit(1)
    )
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede borrar: la grabacion esta en uso en una o mas ediciones",
        )
    await session.delete(recording)
    await session.commit()


async def update_recording(
    session: AsyncSession, recording_id: int, data: "RecordingUpdate"
) -> "RecordingRead":
    """Edita una grabacion. Solo toca los campos presentes en el body (PATCH real)."""
    result = await session.execute(
        select(Recording)
        .where(Recording.id == recording_id)
        .options(*_RECORDING_WITH_USAGES)
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        raise recording_not_found_exception
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(recording, field, value)
    await session.commit()
    await session.refresh(recording, attribute_names=["tracks"])
    return _build_recording_read(recording)


_RECORDING_WITH_USAGES = (
    selectinload(Recording.tracks)
    .selectinload(Track.edition)
    .selectinload(Edition.release),
)


def _build_recording_read(recording: Recording) -> "RecordingRead":
    """Construye RecordingRead con usages a partir de un Recording cargado."""
    from app.modules.discography.schemas import RecordingRead, RecordingUsageRead

    return RecordingRead(
        id=recording.id,
        title=recording.title,
        duration_seconds=recording.duration_seconds,
        credits=recording.credits,
        usages=[
            RecordingUsageRead(
                release_id=track.edition.release.id,
                release_title=track.edition.release.title,
                edition_id=track.edition.id,
                edition_name=track.edition.edition_name,
                release_date=track.edition.release_date,
            )
            for track in recording.tracks
        ],
    )


async def search_recordings(session: AsyncSession, q: str) -> list["RecordingRead"]:
    """Busca grabaciones por titulo (busqueda parcial, insensible a mayusculas).

    Devuelve cada grabacion con la lista de ediciones donde se usa (usages).
    """
    result = await session.execute(
        select(Recording)
        .where(Recording.title.ilike(f"%{q}%"))
        .options(*_RECORDING_WITH_USAGES)
        .order_by(Recording.title)
        .limit(50)
    )
    return [_build_recording_read(r) for r in result.scalars().all()]


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


# --- Collection (agrupa ediciones de OBRAS DISTINTAS bajo un nombre comun) -------

_duplicate_collection_exception = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Ya existe una coleccion con ese nombre",
)

_COLLECTION_WITH_EDITIONS = (
    selectinload(Collection.editions).selectinload(Edition.images),
)
_COLLECTION_DETAIL = (
    selectinload(Collection.editions).selectinload(Edition.images),
    selectinload(Collection.editions).selectinload(Edition.release),
)


def _sorted_by_release_date(editions: list[Edition]) -> list[Edition]:
    """Ordena ediciones por `release_date`, las sin fecha al final.

    `(release_date is None, release_date)` como clave: agrupa primero las que
    SI tienen fecha (False < True), y dentro de cada grupo solo se comparan
    valores homogeneos (fecha con fecha, o None con None), asi que nunca
    revienta comparando None con una fecha real.
    """
    return sorted(editions, key=lambda e: (e.release_date is None, e.release_date))


def _front_cover_url(edition: Edition) -> str | None:
    """Devuelve la URL de la portada (`front_cover`) de una edicion, si tiene."""
    for image in edition.images:
        if image.image_type == ImageType.FRONT_COVER:
            return image.url
    return None


def _build_collection_list_read(collection: Collection) -> CollectionListRead:
    ordered = _sorted_by_release_date(collection.editions)
    sample_covers = [
        url for e in ordered[:3] if (url := _front_cover_url(e)) is not None
    ]
    return CollectionListRead(
        id=collection.id,
        name=collection.name,
        edition_count=len(collection.editions),
        sample_cover_urls=sample_covers,
    )


def _build_collection_detail_read(collection: Collection) -> CollectionDetailRead:
    ordered = _sorted_by_release_date(collection.editions)
    return CollectionDetailRead(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        editions=[
            CollectionEditionRead(
                id=e.id,
                release_id=e.release.id,
                release_title=e.release.title,
                release_type=e.release.release_type,
                edition_name=e.edition_name,
                release_date=e.release_date,
                cover_url=_front_cover_url(e),
            )
            for e in ordered
        ],
    )


async def _get_collection_or_404(session: AsyncSession, collection_id: int) -> Collection:
    collection = await session.get(Collection, collection_id)
    if collection is None:
        raise collection_not_found_exception
    return collection


async def list_collections(session: AsyncSession) -> list[CollectionListRead]:
    """Lista colecciones con su numero de ediciones y 2-3 portadas de muestra
    (las primeras ediciones por `release_date`)."""
    result = await session.execute(
        select(Collection).options(*_COLLECTION_WITH_EDITIONS).order_by(Collection.name)
    )
    return [_build_collection_list_read(c) for c in result.scalars().all()]


async def get_collection(session: AsyncSession, collection_id: int) -> CollectionDetailRead:
    """Detalle de una coleccion: nombre, descripcion y sus ediciones ordenadas
    por `release_date`, cada una con los datos de su obra de origen."""
    result = await session.execute(
        select(Collection)
        .options(*_COLLECTION_DETAIL)
        .where(Collection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if collection is None:
        raise collection_not_found_exception
    return _build_collection_detail_read(collection)


async def create_collection(session: AsyncSession, data: CollectionCreate) -> CollectionDetailRead:
    """Crea una coleccion. Lanza 409 si el nombre ya existe."""
    from sqlalchemy.exc import IntegrityError

    collection = Collection(name=data.name.strip(), description=data.description)
    session.add(collection)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_collection_exception
    await session.refresh(collection, attribute_names=["editions"])
    return _build_collection_detail_read(collection)


async def update_collection(
    session: AsyncSession, collection_id: int, data: CollectionUpdate
) -> CollectionDetailRead:
    """Edita una coleccion. Solo toca los campos presentes en el body (PATCH
    real). Lanza 409 si el nuevo nombre ya lo usa OTRA coleccion."""
    from sqlalchemy.exc import IntegrityError

    collection = await _get_collection_or_404(session, collection_id)
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    for field, value in updates.items():
        setattr(collection, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _duplicate_collection_exception
    return await get_collection(session, collection_id)


async def delete_collection(session: AsyncSession, collection_id: int) -> None:
    """Borra una coleccion. Lanza 409 si tiene alguna edicion asociada."""
    collection = await _get_collection_or_404(session, collection_id)
    in_use = await session.scalar(
        select(collection_editions.c.edition_id)
        .where(collection_editions.c.collection_id == collection_id)
        .limit(1)
    )
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede borrar: la coleccion tiene ediciones asociadas",
        )
    await session.delete(collection)
    await session.commit()


async def add_edition_to_collection(
    session: AsyncSession, collection_id: int, edition_id: int
) -> CollectionDetailRead:
    """Anade una edicion a una coleccion. Idempotente: si ya estaba, no pasa
    nada (no es un conflicto añadir dos veces la misma edicion)."""
    await _get_collection_or_404(session, collection_id)
    edition = await session.get(Edition, edition_id)
    if edition is None:
        raise edition_not_found_exception

    already = await session.scalar(
        select(collection_editions.c.edition_id).where(
            collection_editions.c.collection_id == collection_id,
            collection_editions.c.edition_id == edition_id,
        )
    )
    if already is None:
        await session.execute(
            collection_editions.insert().values(
                collection_id=collection_id, edition_id=edition_id
            )
        )
        await session.commit()

    return await get_collection(session, collection_id)


async def remove_edition_from_collection(
    session: AsyncSession, collection_id: int, edition_id: int
) -> None:
    """Quita una edicion de una coleccion. Lanza 404 si esa edicion no estaba
    (en esta coleccion) para empezar."""
    await _get_collection_or_404(session, collection_id)

    result = await session.execute(
        delete(collection_editions).where(
            collection_editions.c.collection_id == collection_id,
            collection_editions.c.edition_id == edition_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Esa edicion no esta en esta coleccion",
        )
    await session.commit()

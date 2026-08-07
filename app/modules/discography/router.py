"""Router del modulo de discografia: define los endpoints HTTP.

Prefijo: se monta bajo `/api/v1` en `main.py`, y este router anade `/discography`,
asi que las rutas finales son `/api/v1/discography/releases...`.

Tres niveles, igual que el modelo: `Release` (la obra) -> `Edition` (una
publicacion concreta, anidada bajo su obra) -> `Track` (dentro del body de
cada edicion, no tiene endpoints propios).

Leer el catalogo (listar, ver detalle) es PUBLICO: es el proposito de la app.
Escribir (crear/editar/borrar obras y ediciones) exige ser ADMINISTRADOR.
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ErrorMessage
from app.core.storage import StorageBackend, get_storage_backend
from app.modules.auth.dependencies import require_admin
from app.modules.auth.models import User
from app.modules.discography import service
from app.modules.discography.models import (
    Edition,
    Image,
    ImageType,
    Label,
    Recording,
    Release,
    ReleaseType,
)
from app.modules.discography.schemas import (
    CollectionCreate,
    CollectionDetailRead,
    CollectionEditionAdd,
    CollectionListRead,
    CollectionUpdate,
    EditionCreate,
    EditionRead,
    EditionUpdate,
    ImageMoveRequest,
    ImageRead,
    LabelCreate,
    LabelRead,
    LabelUpdate,
    RecordingRead,
    RecordingUpdate,
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
_IMAGE_NOT_FOUND = {"model": ErrorMessage, "description": "La imagen no existe"}
_INVALID_IMAGE = {
    "model": ErrorMessage,
    "description": "Formato de imagen no soportado (usa JPEG, PNG o WEBP)",
}
_IMAGE_TOO_LARGE = {
    "model": ErrorMessage,
    "description": "La imagen supera el tamano maximo permitido (10 MB)",
}


# --- Label (sellos discograficos) ------------------------------------------------

_LABEL_NOT_FOUND = {"model": ErrorMessage, "description": "El sello no existe"}
_LABEL_DUPLICATE = {
    "model": ErrorMessage,
    "description": "Ya existe un sello con ese nombre",
}


@router.get(
    "/labels",
    response_model=list[LabelRead],
    summary="Listar sellos discograficos",
)
async def list_labels(
    q: str | None = Query(default=None, description="Filtra por texto en el nombre"),
    session: AsyncSession = Depends(get_session),
) -> list[LabelRead]:
    """Lista los sellos ordenados por numero de ediciones (desc) y nombre (asc)."""
    return await service.list_labels(session, q)


@router.post(
    "/labels",
    response_model=LabelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un sello (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_409_CONFLICT: _LABEL_DUPLICATE,
    },
)
async def create_label(
    data: LabelCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Label:
    """Crea un sello. El nombre es unico sin distinguir mayusculas."""
    return await service.create_label(session, data)


@router.patch(
    "/labels/{label_id}",
    response_model=LabelRead,
    summary="Editar un sello (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _LABEL_NOT_FOUND,
        status.HTTP_409_CONFLICT: _LABEL_DUPLICATE,
    },
)
async def update_label(
    label_id: int,
    data: LabelUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> Label:
    """Edita el nombre y/o las notas de un sello."""
    return await service.update_label(session, label_id, data)


@router.delete(
    "/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar un sello (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _LABEL_NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "model": ErrorMessage,
            "description": "El sello esta en uso en una o mas ediciones",
        },
    },
)
async def delete_label(
    label_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Borra un sello. Falla con 409 si alguna edicion lo usa todavia."""
    await service.delete_label(session, label_id)


# --- Recording (busqueda de grabaciones para reutilizar) -------------------------


@router.get(
    "/recordings",
    response_model=list[RecordingRead],
    summary="Buscar grabaciones por titulo",
)
async def search_recordings(
    q: str = Query(min_length=1, description="Texto a buscar en el titulo de la grabacion"),
    session: AsyncSession = Depends(get_session),
) -> list[RecordingRead]:
    """Devuelve las grabaciones cuyo titulo contiene `q` (insensible a mayusculas).

    Util para obtener el `recording_id` de una grabacion antes de reutilizarla
    al curar otra edicion que incluya el mismo tema.
    """
    return await service.search_recordings(session, q)


@router.delete(
    "/recordings/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una grabacion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: {"model": ErrorMessage, "description": "La grabacion no existe"},
        status.HTTP_409_CONFLICT: {"model": ErrorMessage, "description": "La grabacion esta en uso en una o mas ediciones"},
    },
)
async def delete_recording(
    recording_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Borra una grabacion. Falla con 409 si algun Track la referencia todavia."""
    await service.delete_recording(session, recording_id)


@router.patch(
    "/recordings/{recording_id}",
    response_model=RecordingRead,
    summary="Editar una grabacion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: {"model": ErrorMessage, "description": "La grabacion no existe"},
    },
)
async def update_recording(
    recording_id: int,
    data: RecordingUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> RecordingRead:
    """Edita los campos presentes en el body (titulo, duracion y/o creditos)."""
    return await service.update_recording(session, recording_id, data)


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


# --- Image (portada, contraportada... de una edicion) -----------------------------


@router.post(
    "/releases/{release_id}/editions/{edition_id}/images",
    response_model=ImageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Subir una imagen a una edicion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _EDITION_NOT_FOUND,
        status.HTTP_413_CONTENT_TOO_LARGE: _IMAGE_TOO_LARGE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_IMAGE,
    },
)
async def upload_image(
    release_id: int,
    edition_id: int,
    image_type: ImageType = Form(
        description="Tipo de imagen: front_cover, back_cover u other"
    ),
    file: UploadFile = File(description="Fichero de imagen (JPEG, PNG o WEBP)"),
    session: AsyncSession = Depends(get_session),
    storage: StorageBackend = Depends(get_storage_backend),
    _admin: User = Depends(require_admin),
) -> Image:
    """Sube una imagen. `front_cover`/`back_cover` sustituyen la anterior; `other` se acumula."""
    content = await file.read()
    return await service.upload_image(
        session,
        storage,
        release_id,
        edition_id,
        image_type,
        content,
        file.content_type or "",
    )


_ALREADY_AT_EDGE = {
    "model": ErrorMessage,
    "description": "La imagen ya esta en el extremo (primera o ultima posicion)",
}


@router.patch(
    "/releases/{release_id}/editions/{edition_id}/images/{image_id}/position",
    response_model=list[ImageRead],
    summary="Mover una imagen arriba o abajo (requiere administrador)",
    responses={
        status.HTTP_400_BAD_REQUEST: _ALREADY_AT_EDGE,
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _IMAGE_NOT_FOUND,
    },
)
async def move_image(
    release_id: int,
    edition_id: int,
    image_id: int,
    data: ImageMoveRequest,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[Image]:
    """Mueve la imagen un puesto arriba o abajo. Devuelve la lista completa de imagenes en el nuevo orden."""
    return await service.move_image(session, release_id, edition_id, image_id, data.direction)


@router.delete(
    "/releases/{release_id}/editions/{edition_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una imagen (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _IMAGE_NOT_FOUND,
    },
)
async def delete_image(
    release_id: int,
    edition_id: int,
    image_id: int,
    session: AsyncSession = Depends(get_session),
    storage: StorageBackend = Depends(get_storage_backend),
    _admin: User = Depends(require_admin),
) -> None:
    """Borra una imagen: la fila y el fichero subyacente."""
    await service.delete_image(session, storage, release_id, edition_id, image_id)


# --- Collection (agrupa ediciones de OBRAS DISTINTAS bajo un nombre comun) -------

_COLLECTION_NOT_FOUND = {
    "model": ErrorMessage,
    "description": "La coleccion no existe",
}
_COLLECTION_DUPLICATE = {
    "model": ErrorMessage,
    "description": "Ya existe una coleccion con ese nombre",
}
_COLLECTION_EDITION_NOT_FOUND = {
    "model": ErrorMessage,
    "description": "Esa edicion no existe, o no esta en esta coleccion (segun el endpoint)",
}


@router.get(
    "/collections",
    response_model=list[CollectionListRead],
    summary="Listar colecciones de ediciones",
)
async def list_collections(
    session: AsyncSession = Depends(get_session),
) -> list[CollectionListRead]:
    """Lista colecciones (p. ej. "Remasterizaciones HDCD") con su numero de
    ediciones y 2-3 portadas de muestra, ordenadas cronologicamente."""
    return await service.list_collections(session)


@router.get(
    "/collections/{collection_id}",
    response_model=CollectionDetailRead,
    summary="Detalle de una coleccion (con sus ediciones)",
    responses={status.HTTP_404_NOT_FOUND: _COLLECTION_NOT_FOUND},
)
async def get_collection(
    collection_id: int, session: AsyncSession = Depends(get_session)
) -> CollectionDetailRead:
    """Devuelve una coleccion con sus ediciones ordenadas por fecha de
    publicacion (las sin fecha, al final), cada una con los datos de su
    obra de origen."""
    return await service.get_collection(session, collection_id)


@router.post(
    "/collections",
    response_model=CollectionDetailRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una coleccion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_409_CONFLICT: _COLLECTION_DUPLICATE,
    },
)
async def create_collection(
    data: CollectionCreate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> CollectionDetailRead:
    """Crea una coleccion (nombre + descripcion opcional). Sus ediciones se
    anaden por separado."""
    return await service.create_collection(session, data)


@router.patch(
    "/collections/{collection_id}",
    response_model=CollectionDetailRead,
    summary="Editar una coleccion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _COLLECTION_NOT_FOUND,
        status.HTTP_409_CONFLICT: _COLLECTION_DUPLICATE,
    },
)
async def update_collection(
    collection_id: int,
    data: CollectionUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> CollectionDetailRead:
    """Edita los campos presentes en el body (nombre y/o descripcion)."""
    return await service.update_collection(session, collection_id, data)


@router.delete(
    "/collections/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una coleccion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _COLLECTION_NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "model": ErrorMessage,
            "description": "La coleccion tiene ediciones asociadas",
        },
    },
)
async def delete_collection(
    collection_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Borra una coleccion. Falla con 409 si todavia tiene ediciones."""
    await service.delete_collection(session, collection_id)


@router.post(
    "/collections/{collection_id}/editions",
    response_model=CollectionDetailRead,
    status_code=status.HTTP_201_CREATED,
    summary="Anadir una edicion a una coleccion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _COLLECTION_EDITION_NOT_FOUND,
    },
)
async def add_edition_to_collection(
    collection_id: int,
    data: CollectionEditionAdd,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> CollectionDetailRead:
    """Anade una edicion (de cualquier obra) a la coleccion. Idempotente: si
    ya estaba, no pasa nada. Devuelve la coleccion completa actualizada."""
    return await service.add_edition_to_collection(session, collection_id, data.edition_id)


@router.delete(
    "/collections/{collection_id}/editions/{edition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar una edicion de una coleccion (requiere administrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _COLLECTION_EDITION_NOT_FOUND,
    },
)
async def remove_edition_from_collection(
    collection_id: int,
    edition_id: int,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> None:
    """Quita una edicion de la coleccion (no borra la edicion en si)."""
    await service.remove_edition_from_collection(session, collection_id, edition_id)

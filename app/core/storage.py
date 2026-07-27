"""Almacenamiento de ficheros (portadas, contraportadas...).

Abstrae DONDE viven los bytes: en desarrollo, disco local; en produccion, un
bucket de Google Cloud Storage (pendiente de implementar). El resto de la app
solo conoce la interfaz `StorageBackend` (guardar bytes -> URL publica; borrar
por esa URL), nunca el backend concreto -- igual que `database_url` abstrae el
motor de base de datos sin que el resto del codigo sepa si es SQLite o Postgres.

La base de datos SOLO guarda la URL que devuelve `save`, nunca los bytes.
"""

from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

import anyio
from fastapi import HTTPException, status

from app.core.config import get_settings


class StorageBackend(ABC):
    """Puerto: cualquier backend de almacenamiento implementa esto."""

    @abstractmethod
    async def save(self, *, filename: str, content: bytes) -> str:
        """Guarda `content` bajo `filename` y devuelve la URL publica resultante."""

    @abstractmethod
    async def delete(self, url: str) -> None:
        """Borra el fichero identificado por una URL devuelta por `save`.

        No lanza error si el fichero ya no existe: un borrado idempotente, igual
        que el DELETE de un objeto en un bucket real.
        """


class LocalStorageBackend(StorageBackend):
    """Backend de DESARROLLO: guarda en una carpeta local del disco.

    Esa carpeta se sirve luego como archivos estaticos bajo `/media` (ver
    `app/main.py`), asi que la URL devuelta por `save` es directamente
    navegable por el cliente, igual que lo seria una URL de un bucket.
    """

    def __init__(self, media_root: str, media_base_url: str) -> None:
        self._media_root = Path(media_root)
        self._media_base_url = media_base_url.rstrip("/")

    async def save(self, *, filename: str, content: bytes) -> str:
        def _write() -> None:
            self._media_root.mkdir(parents=True, exist_ok=True)
            (self._media_root / filename).write_bytes(content)

        # Escribir a disco bloquea el hilo: se hace en uno aparte (anyio, ya
        # viene con FastAPI) para no congelar el event loop mientras dura.
        await anyio.to_thread.run_sync(_write)
        return f"{self._media_base_url}/{filename}"

    async def delete(self, url: str) -> None:
        filename = url.rsplit("/", 1)[-1]
        path = self._media_root / filename

        def _delete() -> None:
            path.unlink(missing_ok=True)

        await anyio.to_thread.run_sync(_delete)


# --- Validacion de imagenes subidas ---------------------------------------------
#
# Compartida por cualquier modulo que suba imagenes (discografia, avatar de
# usuario...): vive aqui, no en cada `service.py`, para no repetir la misma
# regla dos veces y que ambos consumidores se comporten igual.

# Content-type aceptado -> extension del fichero guardado. Cerrado a proposito
# (formatos de imagen web habituales); cualquier otro se rechaza con 422.
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
invalid_image_type_exception = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    detail="Formato de imagen no soportado (usa JPEG, PNG o WEBP)",
)

# 10 MB: generoso para una foto o portada, pequeno para un ataque de subida masiva.
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
image_too_large_exception = HTTPException(
    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
    detail="La imagen supera el tamano maximo permitido (10 MB)",
)


def validate_image_upload(content: bytes, content_type: str) -> str:
    """Valida un fichero de imagen subido. Devuelve la extension a usar.

    Lanza 422 (formato no soportado) o 413 (demasiado grande) si no pasa la
    validacion. Se llama ANTES de guardar nada en el StorageBackend.
    """
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise invalid_image_type_exception
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise image_too_large_exception
    return ALLOWED_IMAGE_CONTENT_TYPES[content_type]


@lru_cache
def get_storage_backend() -> StorageBackend:
    """Devuelve el backend de almacenamiento segun `Settings.storage_backend`.

    Es la unica funcion que sabe elegir la implementacion concreta; el resto de
    la app la usa como dependencia de FastAPI y solo ve `StorageBackend`.
    Cambiar de backend (el dia de manana, GCS en produccion) es tocar esta
    funcion y el `.env`, no los endpoints ni el service.
    """
    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.media_root, settings.media_base_url)
    raise NotImplementedError(
        f"Backend de almacenamiento no soportado todavia: {settings.storage_backend!r}"
    )

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

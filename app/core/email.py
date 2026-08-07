"""Envio de correo (verificacion de email, y lo que se anada en el futuro).

Mismo patron que `app/core/storage.py`: un puerto (`EmailBackend`) que abstrae
COMO se envia un correo, para que el resto de la app no sepa si es un SMTP
real, un proveedor tipo SendGrid, o (en desarrollo) simplemente un log. El
backend se elige por `Settings.email_backend`, igual que `storage_backend`
elige el motor de almacenamiento.

Un backend real (SMTP/SendGrid) queda PENDIENTE de implementar hasta tener una
cuenta/proyecto real contra el que probarlo: mismo criterio que
`GCSStorageBackend` en `storage.py` (codigo no verificable no se escribe a
ciegas).
"""

import logging
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger("app.email")


class EmailBackend(ABC):
    """Puerto: cualquier backend de envio de correo implementa esto."""

    @abstractmethod
    async def send(self, *, to: str, subject: str, body: str) -> None:
        """Envia un correo de texto plano a `to`."""


class ConsoleEmailBackend(EmailBackend):
    """Backend de DESARROLLO: no envia nada de verdad, lo escribe en el log.

    Suficiente para probar el flujo completo (pedir codigo, verlo en la
    consola del servidor, confirmarlo) sin depender de un proveedor de correo
    real todavia.
    """

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("Email a %s | %s\n%s", to, subject, body)


@lru_cache
def get_email_backend() -> EmailBackend:
    """Devuelve el backend de correo segun `Settings.email_backend`.

    Es la unica funcion que sabe elegir la implementacion concreta; el resto
    de la app la usa como dependencia de FastAPI y solo ve `EmailBackend`.
    Cambiar de backend (el dia de manana, un proveedor real en produccion) es
    tocar esta funcion y el `.env`, no los endpoints ni el service.
    """
    settings = get_settings()
    if settings.email_backend == "console":
        return ConsoleEmailBackend()
    raise NotImplementedError(
        f"Backend de email no soportado todavia: {settings.email_backend!r}"
    )

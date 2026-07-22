"""Dependencias de FastAPI del modulo de auth.

Una "dependencia" es una funcion que FastAPI ejecuta ANTES del endpoint y cuyo
resultado se inyecta como parametro. `get_current_user` es la pieza que protege
los endpoints: si el token es valido, el endpoint recibe el `User`; si no, ni
siquiera llega a ejecutarse (se responde 401 automaticamente).

Vive aqui (y no en el router) a proposito: otros modulos la reutilizaran. Por
ejemplo, en la Fase 5 los endpoints de administracion de la discografia pediran
este mismo `get_current_user` para exigir que haya un usuario autenticado.
"""

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import credentials_exception
from app.core.security import decode_access_token
from app.modules.auth.models import User

# Esquema de seguridad "Bearer": le dice a FastAPI (y a /docs) que espere la
# cabecera `Authorization: Bearer <token>`. Extrae el token por nosotros y, de
# paso, habilita el boton "Authorize" en la documentacion interactiva.
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resuelve el usuario autenticado a partir del access token del header.

    Pasos:
      1. Decodificar el JWT (verifica firma y caducidad). Cualquier fallo aqui
         -> 401. Capturamos tambien KeyError (falta `sub`) y ValueError (un `sub`
         que no es un entero).
      2. Comprobar que es un token de tipo "access" y no otra cosa.
      3. Cargar el usuario de la BD y exigir que exista y este activo.

    Nunca damos detalles del motivo exacto del fallo: siempre el mismo 401.
    """
    try:
        payload = decode_access_token(credentials.credentials)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        # `from None` -> no encadenamos la causa interna: el cliente solo ve un
        # 401 limpio, sin pistas sobre por que fallo exactamente el token.
        raise credentials_exception from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    return user

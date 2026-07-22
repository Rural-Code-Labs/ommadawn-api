"""Router del modulo de auth: define los endpoints HTTP.

El router es DELIBERADAMENTE fino: no tiene logica de negocio. Su unico trabajo
es (1) declarar rutas y sus dependencias (sesion de BD, usuario autenticado) y
(2) traducir entre el mundo HTTP y el `service`. Toda la logica vive en
`service.py`; aqui solo se conecta.

Prefijo: se monta bajo `/api/v1` en `main.py`, y este router anade `/auth`, asi
que las rutas finales son `/api/v1/auth/...`.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ErrorMessage
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Respuestas de error reutilizables para la documentacion (OpenAPI/Swagger).
# `model=ErrorMessage` hace que la doc muestre la forma `{"detail": "..."}`. Con
# esto la app movil sabe de antemano que errores puede recibir de cada endpoint.
_CONFLICT = {
    "model": ErrorMessage,
    "description": "El nombre de usuario o el email ya estan en uso",
}
_BAD_CREDENTIALS = {
    "model": ErrorMessage,
    "description": "Usuario o contrasena incorrectos",
}
_INACTIVE = {"model": ErrorMessage, "description": "La cuenta esta desactivada"}
_INVALID_REFRESH = {
    "model": ErrorMessage,
    "description": "Refresh token invalido, caducado o reutilizado",
}
_NO_AUTH = {
    "model": ErrorMessage,
    "description": "Falta el access token o no es valido",
}


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un usuario nuevo",
    responses={status.HTTP_409_CONFLICT: _CONFLICT},
)
async def register(
    data: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Registra un usuario nuevo y lo devuelve (sin datos sensibles).

    `response_model=UserRead` hace que FastAPI filtre la salida: aunque el
    service devuelve el objeto ORM completo, al cliente solo le llegan los campos
    de `UserRead` (nunca `hashed_password`).
    """
    return await service.register_user(session, data)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Iniciar sesion (por username o email)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _BAD_CREDENTIALS,
        status.HTTP_403_FORBIDDEN: _INACTIVE,
    },
)
async def login(
    data: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    """Valida credenciales (username o email + contrasena) y emite un par de tokens."""
    return await service.login_user(session, data.username_or_email, data.password)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Renovar la sesion (rota el refresh token)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _INVALID_REFRESH,
        status.HTTP_403_FORBIDDEN: _INACTIVE,
    },
)
async def refresh(
    data: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    """Renueva la sesion: rota el refresh token y devuelve un par nuevo."""
    return await service.refresh_tokens(session, data.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar sesion (revoca el refresh token)",
    responses={status.HTTP_401_UNAUTHORIZED: _NO_AUTH},
)
async def logout(
    data: RefreshRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Cierra la sesion revocando el refresh token indicado.

    Exige estar autenticado (`get_current_user`): asi solo un usuario con un
    access token valido puede revocar tokens. Responde 204 (sin cuerpo) tanto si
    habia algo que revocar como si no: el resultado para el cliente es el mismo,
    la sesion queda cerrada.
    """
    await service.revoke_refresh_token(session, data.refresh_token)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Datos del usuario autenticado",
    responses={status.HTTP_401_UNAUTHORIZED: _NO_AUTH},
)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Devuelve el usuario autenticado. Util para que la app pinte el perfil."""
    return current_user

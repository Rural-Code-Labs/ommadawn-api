"""Router del modulo de auth: define los endpoints HTTP.

El router es DELIBERADAMENTE fino: no tiene logica de negocio. Su unico trabajo
es (1) declarar rutas y sus dependencias (sesion de BD, usuario autenticado) y
(2) traducir entre el mundo HTTP y el `service`. Toda la logica vive en
`service.py`; aqui solo se conecta.

Prefijo: se monta bajo `/api/v1` en `main.py`, y este router anade `/auth`, asi
que las rutas finales son `/api/v1/auth/...`.
"""

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ErrorMessage
from app.core.storage import StorageBackend, get_storage_backend
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user, require_superadmin
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    GoogleLoginRequest,
    LoginRequest,
    PasswordUpdate,
    RefreshRequest,
    TokenPair,
    UserAdminUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
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
_INVALID_AVATAR = {
    "model": ErrorMessage,
    "description": "Formato de imagen no soportado (usa JPEG, PNG o WEBP)",
}
_AVATAR_TOO_LARGE = {
    "model": ErrorMessage,
    "description": "La imagen supera el tamano maximo permitido (10 MB)",
}
_SUPERADMIN_REQUIRED = {
    "model": ErrorMessage,
    "description": "El usuario esta autenticado pero no es superadministrador",
}
_USER_NOT_FOUND = {"model": ErrorMessage, "description": "El usuario no existe"}
_INVALID_GOOGLE_TOKEN = {
    "model": ErrorMessage,
    "description": "El ID token de Google no es valido (firma, caducidad o audiencia incorrecta)",
}
_GOOGLE_EMAIL_CONFLICT = {
    "model": ErrorMessage,
    "description": (
        "El email ya pertenece a una cuenta creada por contrasena, sin Google "
        'vinculado. `detail` es el codigo "email_conflict" (no una frase), '
        "pensado para que la app lo distinga sin parsear texto."
    ),
}
_USERNAME_CONFLICT = {
    "model": ErrorMessage,
    "description": (
        "El username ya esta en uso (`detail: \"El nombre de usuario ya esta en "
        'uso"`), o la cuenta ya no puede cambiarlo (`detail: "username_already_set"`, '
        "codigo corto, no frase: ya se registro con uno explicito o ya gasto su "
        "unico cambio permitido)."
    ),
}
_GOOGLE_ALREADY_LINKED = {
    "model": ErrorMessage,
    "description": (
        'Esa cuenta de Google ya esta vinculada a OTRO usuario. `detail` es el '
        'codigo "google_already_linked" (no una frase).'
    ),
}
_GOOGLE_ONLY_ACCESS = {
    "model": ErrorMessage,
    "description": (
        "El usuario no tiene contrasena: Google es su UNICA forma de entrar, no "
        'se puede desvincular. `detail` es el codigo "google_only_access" (no '
        "una frase)."
    ),
}
_INVALID_CURRENT_PASSWORD = {
    "model": ErrorMessage,
    "description": (
        "Falta el access token o no es valido, O (si la cuenta ya tenia "
        "contrasena) `current_password` no coincide con la actual. Un `detail` "
        "propio (no el mismo que credenciales de login) para que la app pueda "
        "distinguirlo de una sesion caducada."
    ),
}
_PASSWORD_ONLY_ACCESS = {
    "model": ErrorMessage,
    "description": (
        "La cuenta no tiene Google vinculado: la contrasena es su UNICA forma "
        'de entrar, no se puede quitar. `detail` es el codigo '
        '"password_only_access" (no una frase).'
    ),
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
    "/google",
    response_model=TokenPair,
    summary="Iniciar sesion o registrarse con Google",
    responses={
        status.HTTP_401_UNAUTHORIZED: _INVALID_GOOGLE_TOKEN,
        status.HTTP_403_FORBIDDEN: _INACTIVE,
        status.HTTP_409_CONFLICT: _GOOGLE_EMAIL_CONFLICT,
    },
)
async def google_login(
    data: GoogleLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    """Verifica el ID token de Google y emite el mismo par de tokens que /login.

    Si el email no existe todavia, da de alta la cuenta (vinculada desde el
    primer momento). Si ya existe vinculada a este mismo Google, es un login
    normal. Si el email existe pero pertenece a una cuenta creada por
    contrasena sin Google vinculado, responde 409 en vez de vincular a ciegas
    o crear un duplicado.
    """
    return await service.google_login(session, data.id_token)


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


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Editar los datos de perfil del usuario autenticado",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_409_CONFLICT: _USERNAME_CONFLICT,
    },
)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Edita los campos de perfil presentes en el body (full_name, country, city,
    birth_date, theme_preference). No toca email/contrasena/avatar/roles.

    `username` es un caso especial: solo se acepta si la cuenta todavia tiene
    el username PROVISIONAL que se genera en un alta por Google
    (`username_is_default=True`); a partir de ese unico cambio (o siempre, si
    se registro por contrasena) queda fijo — ver `service.update_profile`."""
    return await service.update_profile(session, current_user, data)


@router.post(
    "/me/avatar",
    response_model=UserRead,
    summary="Subir (o sustituir) el avatar del usuario autenticado",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_413_CONTENT_TOO_LARGE: _AVATAR_TOO_LARGE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID_AVATAR,
    },
)
async def upload_avatar(
    file: UploadFile = File(description="Imagen de avatar (JPEG, PNG o WEBP)"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageBackend = Depends(get_storage_backend),
) -> User:
    """Sube el avatar del usuario autenticado. Si ya tenia uno, lo sustituye."""
    content = await file.read()
    return await service.upload_avatar(
        session, storage, current_user, content, file.content_type or ""
    )


@router.delete(
    "/me/avatar",
    response_model=UserRead,
    summary="Borrar el avatar del usuario autenticado",
    responses={status.HTTP_401_UNAUTHORIZED: _NO_AUTH},
)
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageBackend = Depends(get_storage_backend),
) -> User:
    """Borra el avatar del usuario autenticado (si tenia uno)."""
    return await service.delete_avatar(session, storage, current_user)


@router.post(
    "/me/google",
    response_model=UserRead,
    summary="Vincular una cuenta de Google al usuario autenticado",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_409_CONFLICT: _GOOGLE_ALREADY_LINKED,
    },
)
async def link_google_account(
    data: GoogleLoginRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Verifica el ID token y vincula esa cuenta de Google al usuario ya
    autenticado (no es un login: el usuario viene de la sesion, no del token).
    No toca `email` ni `username`."""
    return await service.link_google_account(session, current_user, data.id_token)


@router.delete(
    "/me/google",
    response_model=UserRead,
    summary="Desvincular la cuenta de Google del usuario autenticado",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_409_CONFLICT: _GOOGLE_ONLY_ACCESS,
    },
)
async def unlink_google_account(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Desvincula Google del usuario autenticado. Rechaza si es su UNICA forma
    de acceso (sin contrasena, quedaria sin poder volver a entrar)."""
    return await service.unlink_google_account(session, current_user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cambiar la contrasena (o establecerla por primera vez)",
    responses={status.HTTP_401_UNAUTHORIZED: _INVALID_CURRENT_PASSWORD},
)
async def change_password(
    data: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Cambia la contrasena del usuario autenticado.

    Si la cuenta ya tenia una, `current_password` es obligatoria y debe
    coincidir. Si la cuenta se creo puramente por Google (sin contrasena),
    `current_password` no hace falta: esta es la forma de ponerle una por
    primera vez."""
    await service.change_password(session, current_user, data)


@router.delete(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar la contrasena (volver a depender solo de Google)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_409_CONFLICT: _PASSWORD_ONLY_ACCESS,
    },
)
async def remove_password(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Quita la contrasena del usuario autenticado. Rechaza si la cuenta no
    tiene Google vinculado (quedaria sin ninguna forma de acceder)."""
    await service.remove_password(session, current_user)


# --- Administracion de usuarios (requiere SUPERadministrador) ---------------------


@router.get(
    "/users",
    response_model=list[UserRead],
    summary="Listar usuarios (requiere superadministrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _SUPERADMIN_REQUIRED,
    },
)
async def list_users(
    session: AsyncSession = Depends(get_session),
    _superadmin: User = Depends(require_superadmin),
) -> list[User]:
    """Lista todos los usuarios. Pensado para elegir a quien promover a admin."""
    return await service.list_users(session)


@router.patch(
    "/users/{user_id}",
    response_model=UserRead,
    summary="Cambiar si otro usuario es administrador (requiere superadministrador)",
    responses={
        status.HTTP_401_UNAUTHORIZED: _NO_AUTH,
        status.HTTP_403_FORBIDDEN: _SUPERADMIN_REQUIRED,
        status.HTTP_404_NOT_FOUND: _USER_NOT_FOUND,
    },
)
async def update_user_admin_status(
    user_id: int,
    data: UserAdminUpdate,
    session: AsyncSession = Depends(get_session),
    _superadmin: User = Depends(require_superadmin),
) -> User:
    """Promueve o degrada a un usuario como administrador (solo `is_admin`,
    no `is_super_admin`: nombrar un superadmin sigue siendo solo por BD)."""
    return await service.set_admin_status(session, user_id, data.is_admin)

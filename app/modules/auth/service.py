"""Logica de negocio del modulo de auth relacionada con los tokens.

A diferencia de `core/security.py` (funciones puras), este `service` SI toca la
base de datos: crea, valida, rota y revoca refresh tokens. Sigue sin saber nada
de HTTP -> no devuelve respuestas, ni codigos de estado; devuelve datos o None,
y sera el `router` (Fase 4) quien traduzca eso a 200 / 401.

Recordatorio del diseno:
  - El refresh token en CLARO solo lo ve el cliente. En BD guardamos su hash.
  - "Rotar" = al renovar, se revoca el token usado y se emite uno nuevo. Asi un
    token robado deja de servir en cuanto el usuario legitimo renueva.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    credentials_exception,
    email_taken_exception,
    inactive_user_exception,
    invalid_refresh_token_exception,
    username_taken_exception,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.schemas import TokenPair, UserCreate

settings = get_settings()


def _build_refresh_token(session: AsyncSession, user_id: int) -> str:
    """Construye una fila de refresh token y la anade a la sesion, SIN confirmar.

    Devuelve el token en CLARO (el unico momento en que existe fuera de BD).
    No hace `commit` a proposito: asi quien llama decide cuando confirmar, lo que
    permite agrupar varias operaciones en una sola transaccion (clave para que la
    rotacion sea atomica). Es un helper interno (prefijo `_`).
    """
    token = generate_refresh_token()
    row = RefreshToken(
        token_hash=hash_refresh_token(token),
        user_id=user_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    session.add(row)
    return token


async def create_refresh_token(session: AsyncSession, user_id: int) -> str:
    """Emite un refresh token nuevo para un usuario y lo persiste.

    Se usara tras un login correcto. Devuelve el token en claro para entregarselo
    al cliente; en BD queda solo su hash.
    """
    token = _build_refresh_token(session, user_id)
    await session.commit()
    return token


async def get_valid_refresh_token(
    session: AsyncSession, token: str
) -> RefreshToken | None:
    """Busca la fila de un refresh token y comprueba que siga siendo valida.

    "Valida" = existe + no revocada + no caducada. La busqueda es por el HASH del
    token (nunca por el token en claro, que no esta en BD). Devuelve la fila o
    None; no lanza excepcion.
    """
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(token),
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    return result.scalar_one_or_none()


async def rotate_refresh_token(
    session: AsyncSession, token: str
) -> tuple[int, str] | None:
    """Rota un refresh token: revoca el actual y emite uno nuevo (atomico).

    Devuelve `(user_id, nuevo_token_en_claro)` si el token era valido, o `None`
    si no lo era (inexistente, revocado o caducado). Con el `user_id` el router
    podra ademas emitir un access token nuevo.

    Todo ocurre en una sola transaccion: revocar el viejo y crear el nuevo se
    confirman juntos en un unico `commit`. Si algo fallara, no quedaria el token
    viejo revocado "a medias".
    """
    current = await get_valid_refresh_token(session, token)
    if current is None:
        return None

    current.revoked = True
    new_token = _build_refresh_token(session, current.user_id)
    await session.commit()
    return current.user_id, new_token


async def revoke_refresh_token(session: AsyncSession, token: str) -> bool:
    """Revoca un refresh token valido (para el logout).

    Devuelve True si habia un token valido y se ha revocado, False si no habia
    nada que revocar (token inexistente, ya revocado o caducado).
    """
    current = await get_valid_refresh_token(session, token)
    if current is None:
        return False

    current.revoked = True
    await session.commit()
    return True


# --- Usuarios: registro, login y renovacion -----------------------------------


async def _get_by_username_or_email(
    session: AsyncSession, identifier: str
) -> User | None:
    """Busca un usuario cuyo username O email coincida con `identifier`."""
    result = await session.execute(
        select(User).where(
            or_(User.username == identifier, User.email == identifier)
        )
    )
    return result.scalar_one_or_none()


async def register_user(session: AsyncSession, data: UserCreate) -> User:
    """Registra un usuario nuevo. Devuelve el `User` creado (objeto ORM).

    Comprueba que ni el username ni el email esten ya en uso, hashea la
    contrasena con argon2 y persiste. La restriccion UNIQUE de la BD es la red de
    seguridad final ante una posible condicion de carrera entre el check y el
    insert; estas comprobaciones dan un error 409 claro en el caso normal.
    """
    existing = await _get_by_username_or_email(session, data.username)
    if existing is not None:
        raise username_taken_exception
    if await _get_by_username_or_email(session, data.email) is not None:
        raise email_taken_exception

    user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)  # recarga la fila para traer id, created_at, etc.
    return user


async def login_user(
    session: AsyncSession, username_or_email: str, password: str
) -> TokenPair:
    """Valida credenciales y devuelve un par de tokens nuevo.

    Si el usuario no existe O la contrasena falla, se lanza el MISMO error
    generico (401) para no revelar que usuarios existen. `hashed_password` puede
    ser None (usuario que en el futuro entre solo por OAuth): en ese caso no hay
    login por contrasena posible.
    """
    user = await _get_by_username_or_email(session, username_or_email)
    if (
        user is None
        or user.hashed_password is None
        or not verify_password(password, user.hashed_password)
    ):
        raise credentials_exception
    if not user.is_active:
        raise inactive_user_exception

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=await create_refresh_token(session, user.id),
    )


async def refresh_tokens(session: AsyncSession, refresh_token: str) -> TokenPair:
    """Renueva la sesion: valida el refresh token, lo rota y emite tokens nuevos.

    Antes de rotar comprobamos que el usuario siga activo: asi no revocamos el
    token viejo (dejando la sesion a medias) si la cuenta esta desactivada.
    """
    current = await get_valid_refresh_token(session, refresh_token)
    if current is None:
        raise invalid_refresh_token_exception

    user = await session.get(User, current.user_id)
    if user is None or not user.is_active:
        raise inactive_user_exception

    # A partir de aqui la rotacion (revocar el viejo + emitir uno nuevo) es atomica.
    _, new_refresh_token = await rotate_refresh_token(session, refresh_token)  # type: ignore[misc]

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=new_refresh_token,
    )

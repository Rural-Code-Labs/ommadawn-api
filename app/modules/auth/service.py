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

import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from google.auth.exceptions import GoogleAuthError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    credentials_exception,
    email_taken_exception,
    google_already_linked_exception,
    google_email_conflict_exception,
    google_only_access_exception,
    inactive_user_exception,
    invalid_google_token_exception,
    invalid_refresh_token_exception,
    username_already_set_exception,
    username_taken_exception,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_google_id_token,
    verify_password,
)
from app.core.storage import StorageBackend, validate_image_upload
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.schemas import TokenPair, UserCreate, UserUpdate

settings = get_settings()

# 404 -> el usuario objetivo de una operacion de administracion no existe.
# Especifico de este modulo (no vive en core/exceptions.py, que es para lo
# verdaderamente transversal).
user_not_found_exception = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Usuario no encontrado",
)

# Vida del access token en segundos. Es justo lo que dura el JWT (su `exp` se
# calcula con los mismos minutos en core/security.py), y se expone al cliente en
# `TokenPair.expires_in` para que pueda renovar de forma proactiva.
ACCESS_TOKEN_EXPIRES_IN = settings.access_token_expire_minutes * 60


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


async def _get_refresh_token_row(
    session: AsyncSession, token: str
) -> RefreshToken | None:
    """Busca la fila de un refresh token por su hash, SIN filtrar nada mas.

    A diferencia de `get_valid_refresh_token`, devuelve la fila aunque este
    revocada o caducada. Es lo que permite distinguir "el token nunca existio"
    de "existio pero ya estaba revocado" -> la base de la deteccion de reuso.
    """
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(token)
        )
    )
    return result.scalar_one_or_none()


def _is_expired(row: RefreshToken) -> bool:
    """Indica si una fila de refresh token ha caducado.

    Normaliza la fecha a UTC antes de comparar: SQLite (desarrollo) devuelve
    fechas "naive" (sin zona) y PostgreSQL (produccion) las devuelve "aware".
    Como siempre las guardamos en UTC, tratar una naive como UTC es correcto y
    hace que la comparacion funcione igual en ambos motores.
    """
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


async def _revoke_all_refresh_tokens(session: AsyncSession, user_id: int) -> int:
    """Revoca TODOS los refresh tokens activos de un usuario. Devuelve cuantos.

    Se usa cuando detectamos un reuso: ante la sospecha de robo, matamos la
    sesion entera y obligamos a volver a iniciar sesion con contrasena.
    """
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
        )
    )
    rows = result.scalars().all()
    for row in rows:
        row.revoked = True
    return len(rows)


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


async def _issue_token_pair(session: AsyncSession, user_id: int) -> TokenPair:
    """Emite un access token + un refresh token nuevo para un usuario.

    Comun a cualquier flujo de login que ya haya decidido que el usuario esta
    autenticado (contrasena, Google...): a partir de aqui es siempre lo mismo.
    """
    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=await create_refresh_token(session, user_id),
        expires_in=ACCESS_TOKEN_EXPIRES_IN,
    )


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

    return await _issue_token_pair(session, user.id)


async def _generate_random_username(session: AsyncSession) -> str:
    """Genera un username aleatorio ("user-123456") para altas por Google.

    A diferencia del registro por contrasena (donde la persona elige su
    username), Google no da uno: se genera un PROVISIONAL, sin relacion con el
    email ni el nombre. `username_is_default=True` marca esto en el usuario, lo
    que le permite cambiarlo una unica vez desde su perfil (ver
    `update_profile`). Reintenta con otro numero si el candidato ya existe,
    mismo patron que el resto de generacion de identificadores unicos del repo.
    """
    while True:
        candidate = f"user-{secrets.randbelow(1_000_000):06d}"
        if await _get_by_username_or_email(session, candidate) is None:
            return candidate


async def google_login(session: AsyncSession, id_token: str) -> TokenPair:
    """Login o alta con Google: verifica el ID token y emite el mismo TokenPair
    que `login_user`. La app no distingue despues si la sesion vino de Google o
    de contrasena.

    Tres casos, por orden:
      1. Ya existe un usuario con este `google_id` -> login normal.
      2. No existe por `google_id` pero SI por email -> esa cuenta se creo por
         contrasena y no esta vinculada. NO se auto-vincula (seria vincular a
         ciegas solo por coincidir el email) ni se crea un duplicado: 409
         (`google_email_conflict_exception`).
      3. No existe ni por `google_id` ni por email -> alta nueva, vinculada
         desde el primer momento, con un username aleatorio provisional
         (`username_is_default=True`, ver `_generate_random_username`).
    """
    try:
        payload = verify_google_id_token(id_token)
    except (ValueError, GoogleAuthError):
        raise invalid_google_token_exception

    email = payload.get("email")
    if not email or not payload.get("email_verified"):
        raise invalid_google_token_exception
    google_id = payload["sub"]

    result = await session.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user is None:
        existing = await _get_by_username_or_email(session, email)
        if existing is not None:
            raise google_email_conflict_exception

        user = User(
            username=await _generate_random_username(session),
            username_is_default=True,
            email=email,
            full_name=payload.get("name"),
            avatar_url=payload.get("picture"),
            google_id=google_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    if not user.is_active:
        raise inactive_user_exception

    return await _issue_token_pair(session, user.id)


async def refresh_tokens(session: AsyncSession, refresh_token: str) -> TokenPair:
    """Renueva la sesion: valida el refresh token, lo rota y emite tokens nuevos.

    Incluye DETECCION DE REUSO. El flujo, de arriba a abajo:

      1. Buscamos la fila por hash, sin filtrar (revocada o no, caducada o no).
      2. Si no existe o ha caducado -> 401 normal.
      3. Si existe pero YA estaba revocada -> reuso: un token que ya se uso vuelve
         a aparecer. Es senal de robo (hay dos copias circulando), asi que
         revocamos TODA la sesion del usuario y respondemos 401. El atacante y el
         usuario legitimo quedan fuera; solo quien sepa la contrasena vuelve.
      4. Si el usuario esta inactivo -> 403.
      5. Si todo esta bien -> rotamos (revocar el actual + emitir uno nuevo) en
         una unica transaccion atomica, y devolvemos el par nuevo.
    """
    row = await _get_refresh_token_row(session, refresh_token)
    if row is None or _is_expired(row):
        raise invalid_refresh_token_exception

    if row.revoked:
        # Reuso detectado: matamos la sesion entera por si acaso.
        await _revoke_all_refresh_tokens(session, row.user_id)
        await session.commit()
        raise invalid_refresh_token_exception

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise inactive_user_exception

    # Rotacion atomica: revocar el actual y emitir uno nuevo en un solo commit.
    row.revoked = True
    new_refresh_token = _build_refresh_token(session, row.user_id)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=new_refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRES_IN,
    )


# --- Avatar ----------------------------------------------------------------------


async def upload_avatar(
    session: AsyncSession,
    storage: StorageBackend,
    user: User,
    content: bytes,
    content_type: str,
) -> User:
    """Sube (o sustituye) el avatar del usuario autenticado.

    A diferencia de las imagenes de discografia (varias por edicion, con un
    `image_type`), aqui basta un simple campo `avatar_url`: un usuario solo
    tiene UN avatar. Subir uno nuevo borra el fichero anterior antes de guardar
    el que llega.
    """
    extension = validate_image_upload(content, content_type)

    if user.avatar_url:
        await storage.delete(user.avatar_url)

    user.avatar_url = await storage.save(
        filename=f"{uuid4().hex}{extension}", content=content
    )
    await session.commit()
    await session.refresh(user)
    return user


async def delete_avatar(session: AsyncSession, storage: StorageBackend, user: User) -> User:
    """Borra el avatar del usuario autenticado, si tiene uno.

    Idempotente: si no tenia avatar, no hace nada y devuelve el usuario igual.
    """
    if user.avatar_url:
        await storage.delete(user.avatar_url)
        user.avatar_url = None
        await session.commit()
        await session.refresh(user)
    return user


# --- Perfil (el propio usuario) ---------------------------------------------------


async def update_profile(session: AsyncSession, user: User, data: UserUpdate) -> User:
    """Edita los datos de perfil del usuario autenticado.

    PATCH real: `model_dump(exclude_unset=True)` distingue un campo OMITIDO (no
    se toca) de uno enviado como `null` (se aplica, p. ej. borrar una
    `birth_date` puesta por error). Mismo patron que `ReleaseUpdate` en
    discografia.

    `username` se trata aparte del resto (no es un `setattr` generico): solo se
    permite si `username_is_default` es `True` (username provisional de un alta
    por Google, aun no elegido por la persona). Si lo es, se valida unicidad
    igual que en el registro y se apaga el flag: a partir de aqui el username
    queda fijo, igual que el de cualquier otra cuenta. Si NO lo es, se rechaza
    con un 409 distinguible (`username_already_set_exception`) en vez de
    ignorarlo en silencio.
    """
    updates = data.model_dump(exclude_unset=True)

    if "username" in updates:
        new_username = updates.pop("username")
        if not user.username_is_default:
            raise username_already_set_exception
        existing = await _get_by_username_or_email(session, new_username)
        if existing is not None and existing.id != user.id:
            raise username_taken_exception
        user.username = new_username
        user.username_is_default = False

    for field, value in updates.items():
        setattr(user, field, value)

    await session.commit()
    await session.refresh(user)
    return user


async def link_google_account(session: AsyncSession, user: User, id_token: str) -> User:
    """Vincula una cuenta de Google al usuario YA AUTENTICADO (no es un login).

    Verifica el ID token igual que `google_login`, pero aqui el usuario ya se
    conoce (viene de la sesion, no del token): no hay alta ni busqueda por
    email, solo comprobar que ese `google_id` no pertenezca YA a otra cuenta
    (dos usuarios no pueden compartir la misma cuenta de Google) antes de
    guardarlo. No toca `email` ni `username`.
    """
    try:
        payload = verify_google_id_token(id_token)
    except (ValueError, GoogleAuthError):
        raise invalid_google_token_exception

    if not payload.get("email") or not payload.get("email_verified"):
        raise invalid_google_token_exception
    google_id = payload["sub"]

    result = await session.execute(select(User).where(User.google_id == google_id))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.id != user.id:
        raise google_already_linked_exception

    user.google_id = google_id
    await session.commit()
    await session.refresh(user)
    return user


async def unlink_google_account(session: AsyncSession, user: User) -> User:
    """Desvincula la cuenta de Google del usuario autenticado.

    Bloqueado si Google es su UNICA forma de acceso (`hashed_password is
    None`): desvincular lo dejaria sin ninguna manera de volver a entrar. No
    exige reautenticarse con contrasena antes: se confia en que la sesion ya
    esta autenticada (mismo criterio que el resto de `PATCH`/`DELETE /me...`).
    """
    if user.hashed_password is None:
        raise google_only_access_exception

    user.google_id = None
    await session.commit()
    await session.refresh(user)
    return user


# --- Administracion de usuarios (superadmin) --------------------------------------


async def list_users(session: AsyncSession) -> list[User]:
    """Lista todos los usuarios. Solo la usa un superadmin (ver require_superadmin)."""
    result = await session.execute(select(User).order_by(User.username))
    return list(result.scalars().all())


async def set_admin_status(session: AsyncSession, user_id: int, is_admin: bool) -> User:
    """Cambia el `is_admin` de otro usuario. Solo la usa un superadmin.

    No toca `is_super_admin`: nombrar a un superadmin sigue siendo solo por BD
    (ver el docstring de `User.is_super_admin`).
    """
    user = await session.get(User, user_id)
    if user is None:
        raise user_not_found_exception

    user.is_admin = is_admin
    await session.commit()
    await session.refresh(user)
    return user

"""Modelos ORM del modulo de auth.

Un "model" es la representacion de una TABLA de la base de datos como una clase
Python. Aqui solo se describe la ESTRUCTURA de los datos (columnas, tipos,
restricciones). La logica (registrar, loguear, validar contrasenas) NO va aqui:
ira en el `service`.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ThemePreference(str, enum.Enum):
    """Preferencia de apariencia de la app (claro/oscuro/automatico).

    Mismo patron que ReleaseType/ImageType/EditionFormat en discografia: texto
    validado por Python + CHECK, no un enum nativo de PostgreSQL, para poder
    ampliar valores sin `ALTER TYPE`.
    """

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class User(Base):
    """Tabla `users`: una fila por cada usuario registrado."""

    __tablename__ = "users"

    # Identificador interno, autoincremental. Clave primaria.
    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Identidad / login ---
    # Se puede iniciar sesion por username O por email; por eso ambos son
    # unicos. `index=True` acelera las busquedas por estas columnas (que es
    # justo lo que hara el login).
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )

    # Nombre del usuario. Opcional a nivel de BD para no bloquear el futuro
    # login con Google/Facebook (donde puede que solo llegue el email).
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- Datos de perfil (opcionales) ---
    # Ninguno se pide en el registro: se rellenan mas adelante (ver PATCH
    # /auth/me, aun por construir). Texto libre, no un catalogo cerrado de
    # paises/ciudades: mismo criterio que Edition.country en discografia.
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # URL del avatar (ver app/core/storage.py). Solo la URL, nunca los bytes:
    # mismo criterio que Image.url en discografia. Una sola imagen por usuario,
    # sin tabla aparte: a diferencia de una Edition (que puede tener varias
    # imagenes con distinto tipo), un usuario solo tiene UN avatar, asi que un
    # simple campo nullable basta; subir uno nuevo sustituye al anterior.
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Preferencia de tema (claro/oscuro/automatico). A diferencia de
    # country/city/birth_date, NO es nullable: es un ajuste que siempre tiene
    # un valor concreto (por defecto "system"), no un dato "desconocido"
    # pendiente de rellenar. Editable via PATCH /auth/me.
    theme_preference: Mapped[ThemePreference] = mapped_column(
        Enum(
            ThemePreference,
            native_enum=False,
            create_constraint=True,
            name="ck_users_theme_preference",
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ThemePreference.SYSTEM,
        nullable=False,
    )

    # Contrasena SIEMPRE hasheada (argon2), nunca en claro.
    # Nullable a proposito: un usuario que en el futuro entre solo con un
    # proveedor externo (Google...) no tendra contrasena local.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Identificador estable de la cuenta de Google vinculada (el `sub` del ID
    # token), no el email: el email puede cambiar en Google, el `sub` no.
    # Nullable + unique: la mayoria de usuarios (login por contrasena) no
    # tienen ninguno; el que lo tiene, lo tiene una sola vez (no se puede
    # vincular la misma cuenta de Google a dos usuarios). No se auto-vincula
    # nunca a un usuario existente creado por contrasena (ver
    # service.google_login): si el email ya existe sin este campo, es 409.
    google_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )

    # --- Estado / permisos ---
    # Permite desactivar una cuenta sin borrarla (baneos, verificacion de email
    # futura, etc.). El login exigira que este activa.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    # Rol de administrador (para gestionar la discografia en fases futuras).
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Rol de SUPERadministrador: puede cambiar el is_admin de otros usuarios
    # (ver PATCH /auth/users/{id}). Es independiente de is_admin -> un
    # superadmin tiene automaticamente los mismos permisos que un admin
    # (ver require_admin en dependencies.py), aunque su propio is_admin sea
    # False. No hay endpoint para nombrar a un superadmin: se hace en BD,
    # mismo criterio que is_admin hoy.
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Marcas de tiempo ---
    # server_default=func.now() -> lo pone la propia base de datos al insertar.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # onupdate -> se actualiza sola cada vez que se modifica la fila.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        # Representacion util para depurar. Nunca incluimos la contrasena.
        return f"<User id={self.id} username={self.username!r}>"


class RefreshToken(Base):
    """Tabla `refresh_tokens`: una fila por cada refresh token emitido.

    Guarda el HASH del token, nunca el token en claro (ese solo lo tiene el
    cliente). Tener los tokens en BD es lo que permite revocarlos y rotarlos:
    para "invalidar" un token basta con marcar su fila como `revoked`, o dejar
    que caduque por `expires_at`.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Hash SHA-256 (hex) del token -> siempre 64 caracteres. Es unico (dos
    # tokens no pueden colisionar) e indexado, porque al renovar buscaremos la
    # fila justo por este valor.
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    # A que usuario pertenece el token. FK a `users.id`. `ondelete="CASCADE"`:
    # si se borra el usuario, la BD borra automaticamente sus tokens (aplica en
    # PostgreSQL; en SQLite requiere activar PRAGMA foreign_keys). Indexado para
    # poder listar/revocar todos los tokens de un usuario de golpe.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Instante de caducidad. Lo calcula el `service` al crear el token
    # (created_at + refresh_token_expire_days). Un token caducado ya no vale
    # aunque no este revocado.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Marca de "invalidado manualmente". Se pone a True al hacer logout o al
    # rotar (se revoca el token viejo y se emite uno nuevo).
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Cuando se emitio. Lo pone la propia BD al insertar.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        # Nunca mostramos el hash completo; con el id y el usuario basta para depurar.
        return f"<RefreshToken id={self.id} user_id={self.user_id} revoked={self.revoked}>"

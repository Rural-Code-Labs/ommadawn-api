"""Schemas (contratos) del modulo de auth.

Un "schema" es un modelo Pydantic que define la forma de los datos que ENTRAN
(request) o SALEN (response) por la API. Son el contrato con la app movil.

Regla de oro: los modelos ORM (`models.py`) NUNCA se exponen tal cual en la API.
Se traducen a estos schemas. Asi controlamos exactamente que campos se aceptan y
que campos se devuelven (p. ej. `hashed_password` no aparece en ninguno de los
de salida: jamas sale de la BD).
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# --- Entrada (request) ---------------------------------------------------------


class UserCreate(BaseModel):
    """Datos para registrar un usuario nuevo (body de POST /auth/register).

    Pydantic valida estos campos ANTES de que lleguen a la logica: si el email
    no tiene forma de email o la contrasena es muy corta, FastAPI responde 422
    automaticamente y el `service` ni se entera.
    """

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    """Credenciales de login (body de POST /auth/login).

    `username_or_email`: un unico campo que acepta el username O el email, porque
    en nuestro modelo `User` se puede iniciar sesion con cualquiera de los dos.
    """

    username_or_email: str
    password: str


class RefreshRequest(BaseModel):
    """Body de POST /auth/refresh y /auth/logout: solo el refresh token."""

    refresh_token: str


# --- Salida (response) ---------------------------------------------------------


class UserRead(BaseModel):
    """Vista publica de un usuario (respuesta de /auth/register y /auth/me).

    Fijate en lo que NO esta: ni `hashed_password`, ni `updated_at`. Solo lo que
    la app necesita ver. `from_attributes=True` permite construir este schema
    directamente desde un objeto ORM `User` (lee sus atributos).
    """

    id: int
    username: str
    email: str
    full_name: str | None
    is_active: bool
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenPair(BaseModel):
    """Respuesta de /auth/login y /auth/refresh: el par de tokens.

    `token_type="bearer"` es la convencion HTTP: le dice al cliente que el access
    token se envia en la cabecera `Authorization: Bearer <token>`.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"

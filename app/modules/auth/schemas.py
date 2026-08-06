"""Schemas (contratos) del modulo de auth.

Un "schema" es un modelo Pydantic que define la forma de los datos que ENTRAN
(request) o SALEN (response) por la API. Son el contrato con la app movil.

Regla de oro: los modelos ORM (`models.py`) NUNCA se exponen tal cual en la API.
Se traducen a estos schemas. Asi controlamos exactamente que campos se aceptan y
que campos se devuelven (p. ej. `hashed_password` no aparece en ninguno de los
de salida: jamas sale de la BD).
"""

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.country_codes import validate_country_code
from app.modules.auth.models import ThemePreference


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


class GoogleLoginRequest(BaseModel):
    """Body de POST /auth/google: el ID token que obtiene el SDK de Google en el cliente.

    La API lo verifica contra Google (firma, caducidad, audiencia); no confia en
    nada de lo que lleve dentro hasta pasar esa verificacion.
    """

    id_token: str = Field(min_length=1)


class UserUpdate(BaseModel):
    """Datos de perfil editables por el propio usuario (body de PATCH /auth/me).

    PATCH de verdad: solo se aplican los campos PRESENTES en el body (el
    service usa `model_dump(exclude_unset=True)`), igual que en discografia.
    Deliberadamente NO estan aqui `username`, `email`, la contrasena, `avatar`
    (tiene su propio endpoint de subida) ni `is_admin`/`is_super_admin`: cada
    uno tiene sus propias reglas (unicidad, verificacion...) y se abordaran
    aparte si hace falta.
    """

    full_name: str | None = Field(default=None, max_length=120)
    country: str | None = Field(
        default=None, min_length=2, max_length=2, pattern="^[A-Z]{2}$"
    )
    city: str | None = Field(default=None, max_length=100)

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: object) -> object:
        return validate_country_code(v)  # type: ignore[arg-type]
    birth_date: date | None = None
    # NO es `ThemePreference | None`: a diferencia de los campos de arriba,
    # este no admite "borrarlo" (la columna en BD no es nullable). El truco
    # para que siga siendo opcional en el PATCH: un valor por defecto (no
    # None) hace que `exclude_unset` lo ignore si se omite, y que un `null`
    # explicito en el body de 422 (Pydantic lo rechaza) en vez de romper en
    # el commit con un IntegrityError.
    theme_preference: ThemePreference = ThemePreference.SYSTEM


class UserAdminUpdate(BaseModel):
    """Body de PATCH /auth/users/{id}: cambia si un usuario es administrador.

    Solo toca `is_admin`. Deliberadamente no permite tocar `is_super_admin`:
    nombrar a un superadmin sigue siendo solo por BD.
    """

    is_admin: bool


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
    country: str | None
    city: str | None
    birth_date: date | None
    avatar_url: str | None
    theme_preference: ThemePreference
    has_google: bool
    is_active: bool
    is_admin: bool
    is_super_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenPair(BaseModel):
    """Respuesta de /auth/login y /auth/refresh: el par de tokens.

    `token_type="bearer"` es la convencion HTTP: le dice al cliente que el access
    token se envia en la cabecera `Authorization: Bearer <token>`.

    `expires_in` es la vida del access token en SEGUNDOS. Con ella el cliente
    puede renovar de forma PROACTIVA (antes de que caduque) en vez de esperar a
    un 401. Es un campo aditivo: los clientes que no lo miren siguen funcionando.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(
        description="Segundos de vida del access token (p. ej. 900 = 15 min).",
    )

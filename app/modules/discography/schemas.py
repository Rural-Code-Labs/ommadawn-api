"""Schemas (contratos) del modulo de discografia.

Igual que en auth: los models ORM (`models.py`) nunca se exponen tal cual. Estos
schemas son el contrato con la app movil.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.modules.discography.models import ReleaseType

# --- Entrada (request) ---------------------------------------------------------


class TrackCreate(BaseModel):
    """Datos de un tema al crear una publicacion (va anidado en ReleaseCreate)."""

    position: int = Field(gt=0, description="Numero de pista (1, 2, 3...)")
    title: str = Field(min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, gt=0)


class ReleaseCreate(BaseModel):
    """Datos para anadir una publicacion al catalogo (body de POST /releases).

    Los temas van ANIDADOS: se crea la publicacion y su lista de temas en una
    unica peticion (ver `service.create_release`), porque asi es como se cura el
    catalogo en la practica: un disco siempre trae su tracklist consigo.
    """

    title: str = Field(min_length=1, max_length=200)
    release_type: ReleaseType
    release_date: date | None = None
    tracks: list[TrackCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _positions_are_unique(self) -> "ReleaseCreate":
        """Rechaza (422) dos temas con el mismo numero de pista.

        Se valida aqui, antes de tocar la BD, en vez de dejar que lo atrape la
        restriccion UNIQUE de la tabla: un 422 con un mensaje claro es mejor
        experiencia que un 500 por un IntegrityError sin traducir.
        """
        positions = [t.position for t in self.tracks]
        if len(positions) != len(set(positions)):
            raise ValueError("Hay temas con el mismo numero de posicion")
        return self


class ReleaseUpdate(BaseModel):
    """Datos para editar una publicacion (body de PATCH /releases/{id}).

    Es un PATCH de verdad: solo se aplican los campos PRESENTES en el body (el
    service lo resuelve con `model_dump(exclude_unset=True)`). Un campo omitido
    no se toca; uno enviado si se aplica, aunque sea `null` (p. ej. borrar una
    `release_date` que resulto ser incierta).

    `tracks`, si se incluye, REEMPLAZA toda la tracklist existente (aunque sea
    una lista vacia). Si se omite, los temas actuales no se tocan.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    release_type: ReleaseType | None = None
    release_date: date | None = None
    tracks: list[TrackCreate] | None = None

    @model_validator(mode="after")
    def _positions_are_unique(self) -> "ReleaseUpdate":
        """Misma regla que en ReleaseCreate, solo si se ha enviado `tracks`."""
        if self.tracks:
            positions = [t.position for t in self.tracks]
            if len(positions) != len(set(positions)):
                raise ValueError("Hay temas con el mismo numero de posicion")
        return self


# --- Salida (response) ---------------------------------------------------------


class TrackRead(BaseModel):
    """Vista publica de un tema (dentro de la respuesta de un Release)."""

    id: int
    position: int
    title: str
    duration_seconds: int | None

    model_config = {"from_attributes": True}


class ReleaseRead(BaseModel):
    """Vista publica de una publicacion, con su lista de temas incluida."""

    id: int
    title: str
    release_type: ReleaseType
    release_date: date | None
    created_at: datetime
    tracks: list[TrackRead]

    model_config = {"from_attributes": True}

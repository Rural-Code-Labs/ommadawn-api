"""Schemas (contratos) del modulo de discografia.

Igual que en auth: los models ORM (`models.py`) nunca se exponen tal cual. Estos
schemas son el contrato con la app movil, en los mismos tres niveles que los
modelos: Release (la obra) -> Edition (una publicacion concreta) -> Track.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.country_codes import validate_country_code
from app.modules.discography.models import EditionFormat, ImageType, ReleaseType

# --- Entrada (request) ---------------------------------------------------------


class TrackCreate(BaseModel):
    """Datos de un tema al crear/editar una edicion (va anidado)."""

    position: int = Field(gt=0, description="Numero de pista (1, 2, 3...)")
    title: str = Field(min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, gt=0)


def _validate_unique_positions(tracks: list[TrackCreate] | None) -> None:
    """Rechaza (422) dos temas con el mismo numero de posicion.

    Se valida aqui, antes de tocar la BD, en vez de dejar que lo atrape la
    restriccion UNIQUE de la tabla: un 422 con un mensaje claro es mejor
    experiencia que un 500 por un IntegrityError sin traducir. Compartida por
    EditionCreate y EditionUpdate.
    """
    if not tracks:
        return
    positions = [t.position for t in tracks]
    if len(positions) != len(set(positions)):
        raise ValueError("Hay temas con el mismo numero de posicion")


class EditionCreate(BaseModel):
    """Datos para anadir una edicion a una obra (body de POST .../editions).

    Los temas van ANIDADOS: se crea la edicion y su tracklist en una unica
    peticion, porque asi es como se cura el catalogo en la practica.
    """

    country: str | None = Field(
        default=None, min_length=2, max_length=2, pattern="^[A-Z]{2}$"
    )
    label: str | None = Field(default=None, max_length=150)
    edition_name: str | None = Field(default=None, max_length=200)
    catalog_number: str | None = Field(default=None, max_length=100)
    release_date: date | None = None
    format: EditionFormat | None = None
    # Sin max_length: texto libre (musicos, productor... / notas sobre la
    # edicion), no hay un limite razonable que imponer de antemano.
    credits: str | None = None
    notes: str | None = None
    is_primary: bool = False
    tracks: list[TrackCreate] = Field(default_factory=list)

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: object) -> object:
        return validate_country_code(v)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _check_positions(self) -> "EditionCreate":
        _validate_unique_positions(self.tracks)
        return self


class EditionUpdate(BaseModel):
    """Datos para editar una edicion (body de PATCH .../editions/{id}).

    PATCH de verdad: solo se aplican los campos PRESENTES en el body (el
    service usa `model_dump(exclude_unset=True)`). `tracks`, si se envia,
    REEMPLAZA toda la tracklist existente.
    """

    country: str | None = Field(
        default=None, min_length=2, max_length=2, pattern="^[A-Z]{2}$"
    )
    label: str | None = None
    edition_name: str | None = None
    catalog_number: str | None = None
    release_date: date | None = None
    format: EditionFormat | None = None
    credits: str | None = None
    notes: str | None = None
    is_primary: bool | None = None
    tracks: list[TrackCreate] | None = None

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: object) -> object:
        return validate_country_code(v)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _check_positions(self) -> "EditionUpdate":
        _validate_unique_positions(self.tracks)
        return self


class ReleaseCreate(BaseModel):
    """Datos para anadir una obra al catalogo (body de POST /releases).

    Solo el titulo y el tipo: una obra puede existir en el catalogo sin
    ediciones todavia (se anaden despues via POST /releases/{id}/editions).
    """

    title: str = Field(min_length=1, max_length=200)
    release_type: ReleaseType


class ReleaseUpdate(BaseModel):
    """Datos para editar una obra (body de PATCH /releases/{id}). PATCH parcial."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    release_type: ReleaseType | None = None


# --- Salida (response) ---------------------------------------------------------


class TrackRead(BaseModel):
    """Vista publica de un tema."""

    id: int
    position: int
    title: str
    duration_seconds: int | None

    model_config = {"from_attributes": True}


class ImageRead(BaseModel):
    """Vista publica de una imagen (portada, contraportada...) de una edicion.

    No hay `ImageCreate`: la subida es un endpoint de fichero (multipart), no
    un body JSON; sus campos (`image_type`, el propio fichero) se declaran
    directamente en la firma del endpoint (ver router.py).
    """

    id: int
    image_type: ImageType
    url: str
    position: int

    model_config = {"from_attributes": True}


class ImageMoveRequest(BaseModel):
    """Body de PATCH .../images/{id}/position: mueve la imagen un puesto arriba o abajo."""

    direction: Literal["up", "down"]


class EditionRead(BaseModel):
    """Vista publica de una edicion, con su tracklist e imagenes incluidas."""

    id: int
    country: str | None
    label: str | None
    edition_name: str | None
    catalog_number: str | None
    release_date: date | None
    format: EditionFormat | None
    credits: str | None
    notes: str | None
    is_primary: bool
    tracks: list[TrackRead]
    images: list[ImageRead]

    model_config = {"from_attributes": True}


class ReleaseRead(BaseModel):
    """Vista publica de una obra, con todas sus ediciones incluidas."""

    id: int
    title: str
    release_type: ReleaseType
    created_at: datetime
    editions: list[EditionRead]

    model_config = {"from_attributes": True}

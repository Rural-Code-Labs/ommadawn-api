"""Schemas (contratos) del modulo de discografia.

Igual que en auth: los models ORM (`models.py`) nunca se exponen tal cual. Estos
schemas son el contrato con la app movil, en los mismos niveles que los modelos:
Release -> Edition -> Track (que referencia a Recording).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.country_codes import validate_country_code
from app.modules.discography.models import EditionFormat, ImageType, ReleaseType

# --- Entrada (request) ---------------------------------------------------------


class TrackCreate(BaseModel):
    """Datos de un tema al crear/editar una edicion (va anidado en el body).

    Dos formas excluyentes:
    - Grabacion nueva: enviar `title` (y opcionalmente `duration_seconds`,
      `credits`). Se crea una nueva fila en `recordings`.
    - Grabacion existente: enviar `recording_id`. Se reutiliza la grabacion
      tal cual, sin duplicar creditos ni duracion. No se puede enviar `title`
      junto a `recording_id`.
    """

    position: int = Field(gt=0, description="Numero de pista dentro de este disco/cara (1, 2, 3...)")
    disc_number: int = Field(default=1, ge=1, description="Numero de disco (1 para CD unico o Cara A/B del primer disco)")
    side: str | None = Field(default=None, max_length=10, description="Cara del disco: 'A', 'B'... Solo para vinilos; null para CDs")

    # Forma 1: grabacion nueva
    title: str | None = Field(default=None, min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, gt=0)
    credits: str | None = None

    # Forma 2: grabacion existente
    recording_id: int | None = None

    @model_validator(mode="after")
    def _check_recording_source(self) -> "TrackCreate":
        if self.recording_id is not None and self.title is not None:
            raise ValueError("No puedes enviar 'recording_id' y 'title' a la vez")
        if self.recording_id is None and self.title is None:
            raise ValueError("Debes enviar 'title' (grabacion nueva) o 'recording_id' (grabacion existente)")
        return self


def _validate_unique_positions(tracks: list[TrackCreate] | None) -> None:
    """Rechaza (422) si dos temas del mismo disco/cara tienen la misma posicion.

    Se valida aqui, antes de tocar la BD, para devolver un 422 con mensaje claro
    en vez de un 500 por un IntegrityError. Compartida por EditionCreate y
    EditionUpdate.
    """
    if not tracks:
        return
    keys = [(t.disc_number, t.side, t.position) for t in tracks]
    if len(keys) != len(set(keys)):
        raise ValueError("Hay temas con la misma combinacion de disc_number, side y position")


class EditionCreate(BaseModel):
    """Datos para anadir una edicion a una obra (body de POST .../editions).

    Los temas van ANIDADOS: se crea la edicion y su tracklist en una unica
    peticion, porque asi es como se cura el catalogo en la practica.
    """

    country: str | None = Field(
        default=None, min_length=2, max_length=2, pattern="^[A-Z]{2}$"
    )
    label_id: int | None = None
    edition_name: str | None = Field(default=None, max_length=200)
    catalog_number: str | None = Field(default=None, max_length=100)
    release_date: date | None = None
    format: EditionFormat | None = None
    credits: str | None = None
    notes: str | None = None
    is_primary: bool = False
    tracks: list[TrackCreate] = Field(default_factory=list)

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country(cls, v: object) -> object:
        return validate_country_code(v)  # type: ignore[arg-type]

    @field_validator("edition_name", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        return None if v == "" else v

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
    label_id: int | None = None
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

    @field_validator("edition_name", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        return None if v == "" else v

    @model_validator(mode="after")
    def _check_positions(self) -> "EditionUpdate":
        _validate_unique_positions(self.tracks)
        return self


class LabelCreate(BaseModel):
    """Datos para crear un sello (body de POST /labels)."""

    name: str = Field(min_length=1, max_length=150)
    notes: str | None = None


class LabelUpdate(BaseModel):
    """Datos para editar un sello (body de PATCH /labels/{id}). PATCH parcial."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    notes: str | None = None


class RecordingUpdate(BaseModel):
    """Datos para editar una grabacion (body de PATCH /recordings/{id}). PATCH parcial."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, gt=0)
    credits: str | None = None


class ReleaseCreate(BaseModel):
    """Datos para anadir una obra al catalogo (body de POST /releases).

    Solo el titulo, el tipo y la descripcion opcional: una obra puede existir en
    el catalogo sin ediciones todavia (se anaden despues via POST /releases/{id}/editions).
    """

    title: str = Field(min_length=1, max_length=200)
    release_type: ReleaseType
    description: str | None = None


class ReleaseUpdate(BaseModel):
    """Datos para editar una obra (body de PATCH /releases/{id}). PATCH parcial."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    release_type: ReleaseType | None = None
    description: str | None = None


# --- Salida (response) ---------------------------------------------------------


class LabelRead(BaseModel):
    """Vista publica de un sello discografico."""

    id: int
    name: str
    notes: str | None

    model_config = {"from_attributes": True}


class RecordingUsageRead(BaseModel):
    """Donde aparece una grabacion: la edicion y la obra a la que pertenece."""

    release_id: int
    release_title: str
    edition_id: int
    edition_name: str | None
    release_date: date | None


class RecordingRead(BaseModel):
    """Vista publica de una grabacion, con la lista de ediciones donde se usa."""

    id: int
    title: str
    duration_seconds: int | None
    credits: str | None
    usages: list[RecordingUsageRead] = []

    model_config = {"from_attributes": True}


class TrackRead(BaseModel):
    """Vista publica de un tema dentro de una edicion.

    Se presenta 'aplanado': el cliente ve title/duration_seconds/credits
    directamente, sin saber que internamente vienen de Recording. El campo
    recording_id se expone para que la app pueda reutilizarlo al curar
    otras ediciones que incluyan la misma grabacion.
    """

    id: int
    recording_id: int
    position: int
    disc_number: int
    side: str | None
    title: str
    duration_seconds: int | None
    credits: str | None

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
    # Objeto anidado (no una cadena): la app necesita el `id` para poder
    # cambiar el sello, y el `name` para mostrarlo, en una sola respuesta.
    label: LabelRead | None
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
    description: str | None
    created_at: datetime
    editions: list[EditionRead]

    model_config = {"from_attributes": True}

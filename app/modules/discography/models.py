"""Modelos ORM del modulo de discografia.

Tres niveles, de lo abstracto a lo concreto:

  Release (la OBRA: "Tubular Bells", con su tipo: disco, recopilatorio,
           single o bootleg)
    -> Edition (una publicacion CONCRETA de esa obra: pais, sello, fecha y
                portada propios -- la original UK de 1973, la reedicion
                remasterizada de 2009...)
      -> Track (la tracklist de ESA edicion; puede variar entre ediciones:
                bonus tracks, ediciones remasterizadas...)

Se usa `Release` (no `Album`) porque un single o un bootleg no son "un album"
en sentido estricto, pero si son una obra con sus propias ediciones.
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReleaseType(str, enum.Enum):
    """Tipos de obra que catalogamos.

    Es un enum de PYTHON, no un tipo nativo de la base de datos: en la columna se
    guarda como texto validado por un CHECK. Se elige a proposito frente al enum
    nativo de PostgreSQL porque este conjunto de valores va a crecer (p. ej.
    'directo' en una fase futura) y anadir un valor a un CHECK es una migracion
    mas simple que la de un tipo nativo (`ALTER TYPE ... ADD VALUE`).
    """

    STUDIO = "studio"
    COMPILATION = "compilation"
    SINGLE = "single"
    BOOTLEG = "bootleg"


class Release(Base):
    """Tabla `releases`: la obra abstracta, independiente de sus ediciones.

    NO tiene fecha de publicacion ni temas propios: esos datos varian entre
    ediciones (una reedicion tiene otra fecha, un bonus track no esta en el
    original) y viven en `Edition`.
    """

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # `native_enum=False` -> se guarda como String + CHECK, no como tipo nativo
    # de Postgres. Ver el porque en el docstring de ReleaseType.
    # `values_callable` -> que la columna guarde el VALOR ("studio") y no el
    # NOMBRE ("STUDIO") del miembro de Python; asi la BD habla el mismo idioma
    # que el JSON de la API.
    release_type: Mapped[ReleaseType] = mapped_column(
        Enum(
            ReleaseType,
            native_enum=False,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # `cascade="all, delete-orphan"`: borrar el Release borra sus ediciones (y,
    # transitivamente, sus temas). `order_by` ordena cronologicamente.
    editions: Mapped[list["Edition"]] = relationship(
        back_populates="release",
        cascade="all, delete-orphan",
        order_by="Edition.release_date",
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} title={self.title!r} type={self.release_type.value}>"


class Edition(Base):
    """Tabla `editions`: una publicacion CONCRETA de un `Release`.

    Un mismo `Release` puede tener varias `Edition` (la original de un pais, una
    reedicion remasterizada, una edicion limitada de otro pais con otra
    portada...). Cada una tiene su propia fecha, sello y tracklist.
    """

    __tablename__ = "editions"
    __table_args__ = (
        # A lo sumo UNA edicion marcada como principal por Release. Es un
        # indice UNICO PARCIAL (solo sobre filas con is_primary=True): puede
        # haber cualquier numero de ediciones con is_primary=False sin chocar.
        # El service se encarga de "desmarcar" la anterior al fijar una nueva
        # (ver _demote_other_primary_editions), asi que este indice actua como
        # red de seguridad, no como algo con lo que un admin choque a diario.
        Index(
            "uq_editions_release_primary",
            "release_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    release_id: Mapped[int] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Todos nullable: no siempre se conocen (p. ej. bootlegs sin pais/sello claro).
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Nombre descriptivo de la edicion, p. ej. "Reedicion remasterizada 2009".
    edition_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Marca la edicion "por defecto" a mostrar cuando un Release tiene varias
    # (p. ej. en una lista del catalogo, que portada ensenar).
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    release: Mapped["Release"] = relationship(back_populates="editions")
    tracks: Mapped[list["Track"]] = relationship(
        back_populates="edition",
        cascade="all, delete-orphan",
        order_by="Track.position",
    )
    images: Mapped[list["Image"]] = relationship(
        back_populates="edition",
        cascade="all, delete-orphan",
        order_by="Image.image_type",
    )

    def __repr__(self) -> str:
        return (
            f"<Edition id={self.id} release_id={self.release_id} "
            f"country={self.country!r} is_primary={self.is_primary}>"
        )


class Track(Base):
    """Tabla `tracks`: un tema dentro de una edicion concreta.

    Cada Track pertenece a UNA sola edicion (1:N, sin compartir temas entre
    ediciones ni publicaciones). Si el mismo tema aparece en dos ediciones (o en
    un recopilatorio), hoy son filas independientes: simplificacion deliberada.
    """

    __tablename__ = "tracks"
    __table_args__ = (
        # Dos temas de la MISMA edicion no pueden tener el mismo numero.
        UniqueConstraint("edition_id", "position", name="uq_tracks_edition_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    edition_id: Mapped[int] = mapped_column(
        ForeignKey("editions.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Numero de pista dentro de la edicion (1, 2, 3...). Determina el orden.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Nullable: no siempre se conoce la duracion exacta (p. ej. bootlegs).
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    edition: Mapped["Edition"] = relationship(back_populates="tracks")

    def __repr__(self) -> str:
        return (
            f"<Track id={self.id} edition_id={self.edition_id} "
            f"position={self.position} title={self.title!r}>"
        )


class ImageType(str, enum.Enum):
    """Tipos de imagen de una edicion. Mismo patron que ReleaseType: texto
    validado por Python + CHECK, ampliable sin tocar tipos nativos."""

    FRONT_COVER = "front_cover"
    BACK_COVER = "back_cover"
    OTHER = "other"


class Image(Base):
    """Tabla `images`: una imagen (portada, contraportada...) de una edicion.

    Solo guarda la URL (la devuelve el StorageBackend al subir el fichero,
    ver app/core/storage.py); los bytes NUNCA viven en la base de datos.

    `front_cover`/`back_cover` se SUSTITUYEN al subir una nueva (lo gestiona el
    service, no hay restriccion UNIQUE aqui): como mucho una de cada por
    edicion. `other` si se acumula: varias paginas de un librillo, fotos
    sueltas...
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)

    edition_id: Mapped[int] = mapped_column(
        ForeignKey("editions.id", ondelete="CASCADE"), index=True, nullable=False
    )

    image_type: Mapped[ImageType] = mapped_column(
        Enum(
            ImageType,
            native_enum=False,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    url: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    edition: Mapped["Edition"] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return (
            f"<Image id={self.id} edition_id={self.edition_id} "
            f"type={self.image_type.value}>"
        )

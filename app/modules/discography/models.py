"""Modelos ORM del modulo de discografia.

  Release   (la OBRA abstracta: "Tubular Bells", tipo: studio/live/bootleg...)
    -> Edition  (publicacion CONCRETA: pais, sello, fecha, formato, portada...)
         -> Track  (aparicion de una grabacion en ESA edicion: posicion, disco, cara)
              -> Recording  (la grabacion real: titulo, duracion, creditos --
                             COMPARTIDA entre ediciones que incluyan el mismo tema)

La separacion Track/Recording permite que "Tubular Bells Part One" de la edicion
original UK y la misma pista en Boxed compartan una unica fila en `recordings`
(y sus creditos se escriban solo una vez), mientras que cada `Track` guarda los
datos que si varian por edicion: posicion, numero de disco y cara.
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
    Text,
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
    LIVE = "live"


class EditionFormat(str, enum.Enum):
    """Formato fisico de una edicion. Mismo patron que ReleaseType/ImageType:
    texto validado por Python + CHECK, ampliable sin tocar tipos nativos."""

    VINYL = "vinyl"
    CD = "cd"
    SINGLE = "single"
    MAXI_SINGLE = "maxi_single"
    CD_SINGLE = "cd_single"
    CASSETTE = "cassette"


class Release(Base):
    """Tabla `releases`: la obra abstracta, independiente de sus ediciones.

    NO tiene fecha de publicacion ni temas propios: esos datos varian entre
    ediciones (una reedicion tiene otra fecha, un bonus track no esta en el
    original) y viven en `Edition`.
    """

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Texto libre: historia, contexto y curiosidades de la obra. Text (sin
    # limite de longitud) porque puede ser tan largo como haga falta.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # `native_enum=False` -> se guarda como String + CHECK, no como tipo nativo
    # de Postgres. Ver el porque en el docstring de ReleaseType.
    # `create_constraint=True` -> emite de verdad el CHECK. SQLAlchemy lo trae a
    # False por defecto desde 1.4, asi que sin esto la validacion seria SOLO de
    # Python y un UPDATE a mano en psql podria colar cualquier cadena.
    # `values_callable` -> que la columna guarde el VALOR ("studio") y no el
    # NOMBRE ("STUDIO") del miembro de Python; asi la BD habla el mismo idioma
    # que el JSON de la API.
    release_type: Mapped[ReleaseType] = mapped_column(
        Enum(
            ReleaseType,
            native_enum=False,
            create_constraint=True,
            name="ck_releases_release_type",
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


class Label(Base):
    """Tabla `labels`: un sello discografico (Virgin, Mercury, Warner...).

    Se saco del texto libre que antes vivia en `Edition.label` para poder
    gestionarlo desde la app (crear, renombrar) y para que dos ediciones del
    mismo sello apunten de verdad a la misma fila, en vez de repetir la cadena
    con el riesgo de erratas ("Virgin" / "virgin" / "Virgin Records").

    La unicidad del nombre es INSENSIBLE A MAYUSCULAS (indice funcional sobre
    `lower(name)`): evita acabar con "Virgin" y "virgin" como sellos distintos.
    """

    __tablename__ = "labels"
    __table_args__ = (
        Index("uq_labels_name_lower", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(150), nullable=False)

    # Texto libre para cualquier apunte sobre el sello (historia, matices...).
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    editions: Mapped[list["Edition"]] = relationship(back_populates="label")

    def __repr__(self) -> str:
        return f"<Label id={self.id} name={self.name!r}>"


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
    # El sello vive en su propia tabla (ver Label): se gestiona desde la app y
    # se reutiliza entre ediciones, en vez de repetir el texto en cada fila.
    # RESTRICT igual que Track.recording_id: no se borra un sello en uso.
    label_id: Mapped[int | None] = mapped_column(
        ForeignKey("labels.id", ondelete="RESTRICT"), index=True, nullable=True
    )
    # Nombre descriptivo de la edicion, p. ej. "Reedicion remasterizada 2009".
    edition_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Referencia del sello para ESTA edicion, p. ej. "V2001" o "CDV 2002".
    catalog_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # `Text`, no `String(n)`: son campos de informacion libre (musicos,
    # productor, ingeniero de sonido... / cualquier nota sobre la edicion), sin
    # limite de longitud razonable que imponer de antemano.
    credits: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Formato fisico (vinilo, CD, cassette...). Nullable: no siempre se conoce
    # o no aplica (p. ej. una edicion solo digital).
    format: Mapped[EditionFormat | None] = mapped_column(
        Enum(
            EditionFormat,
            native_enum=False,
            create_constraint=True,
            name="ck_editions_format",
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )

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
    label: Mapped["Label | None"] = relationship(back_populates="editions")
    tracks: Mapped[list["Track"]] = relationship(
        back_populates="edition",
        cascade="all, delete-orphan",
        order_by="Track.position",
    )
    images: Mapped[list["Image"]] = relationship(
        back_populates="edition",
        cascade="all, delete-orphan",
        order_by="Image.position",
    )

    def __repr__(self) -> str:
        return (
            f"<Edition id={self.id} release_id={self.release_id} "
            f"country={self.country!r} is_primary={self.is_primary}>"
        )


class Recording(Base):
    """Tabla `recordings`: la grabacion real de un tema.

    Representa "la toma concreta": titulo, duracion y creditos. Se separa de
    `Track` para poder compartir la misma grabacion entre varias ediciones
    (p. ej. "Tubular Bells Part One" de la edicion original y la misma pista
    en un recopilatorio como Boxed). Asi los creditos se escriben UNA sola vez.

    Una `Recording` sin creditos es perfectamente valida: no siempre se conocen.
    """

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Nullable: no siempre se conoce la duracion exacta (p. ej. bootlegs).
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Texto libre: instrumentistas, productor, ingeniero de sonido...
    credits: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tracks: Mapped[list["Track"]] = relationship(back_populates="recording")

    def __repr__(self) -> str:
        return f"<Recording id={self.id} title={self.title!r}>"


class Track(Base):
    """Tabla `tracks`: la aparicion de una Recording en una Edition concreta.

    Guarda los datos que SI varian por edicion: posicion, disco y cara. El
    titulo, duracion y creditos viven en `Recording` y se comparten entre
    todas las ediciones que incluyen esa grabacion.

    `disc_number` + `side` permiten agrupar las pistas:
      - CDs: disc_number=1/2/3, side=None
      - Vinilos: disc_number=1/2, side="A"/"B"

    La unicidad de posicion se garantiza con dos indices parciales:
      - Cuando side IS NULL: UNIQUE(edition_id, disc_number, position)
      - Cuando side IS NOT NULL: UNIQUE(edition_id, disc_number, side, position)
    Se usan dos indices porque PostgreSQL trata NULL != NULL en restricciones
    UNIQUE, lo que dejaria pasar duplicados cuando side es NULL.
    """

    __tablename__ = "tracks"
    __table_args__ = (
        Index(
            "uq_tracks_edition_disc_null_side_pos",
            "edition_id", "disc_number", "position",
            unique=True,
            postgresql_where=text("side IS NULL"),
            sqlite_where=text("side IS NULL"),
        ),
        Index(
            "uq_tracks_edition_disc_side_pos",
            "edition_id", "disc_number", "side", "position",
            unique=True,
            postgresql_where=text("side IS NOT NULL"),
            sqlite_where=text("side IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    edition_id: Mapped[int] = mapped_column(
        ForeignKey("editions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    # Numero de pista dentro de este disco/cara (1, 2, 3...).
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Numero de disco dentro de la edicion. Por defecto 1 (la mayoria de albums).
    disc_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Cara del disco (solo en vinilos: "A", "B"). None para CDs y digitales.
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)

    edition: Mapped["Edition"] = relationship(back_populates="tracks")
    recording: Mapped["Recording"] = relationship(back_populates="tracks")

    # Propiedades que "aplanan" Recording hacia Track para que TrackRead
    # funcione con from_attributes=True sin necesitar un schema anidado.
    @property
    def title(self) -> str:
        return self.recording.title

    @property
    def duration_seconds(self) -> int | None:
        return self.recording.duration_seconds

    @property
    def credits(self) -> str | None:
        return self.recording.credits

    def __repr__(self) -> str:
        return (
            f"<Track id={self.id} edition_id={self.edition_id} "
            f"disc={self.disc_number} side={self.side!r} pos={self.position}>"
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
            create_constraint=True,
            name="ck_images_image_type",
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Orden de visualizacion dentro de la edicion. Se asigna automaticamente al
    # subir (max existente + 1) y se puede reordenar con el endpoint de posicion.
    # Sin restriccion UNIQUE: el servicio gestiona el orden; la unicidad aqui
    # complicaria el swap de dos imagenes sin aportar integridad real.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    edition: Mapped["Edition"] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return (
            f"<Image id={self.id} edition_id={self.edition_id} "
            f"type={self.image_type.value}>"
        )

"""Modelos ORM del modulo de discografia.

Cubre discos de estudio, recopilatorios, singles y bootlegs bajo un unico
concepto: `Release` (publicacion). Se usa este nombre paraguas y no `Album`
porque un single o un bootleg no son "un album" en sentido estricto, pero si son
una publicacion con su propia lista de temas.
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReleaseType(str, enum.Enum):
    """Tipos de publicacion que catalogamos.

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
    """Tabla `releases`: una fila por cada disco, recopilatorio, single o bootleg."""

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

    # Nullable a proposito: la fecha de algunos bootlegs puede ser incierta o
    # desconocida.
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # `cascade="all, delete-orphan"`: si se borra el Release (o se quita un Track
    # de la lista en memoria), sus Track se borran con el. `order_by` asegura que
    # al leer `release.tracks` siempre vengan en orden de pista.
    tracks: Mapped[list["Track"]] = relationship(
        back_populates="release",
        cascade="all, delete-orphan",
        order_by="Track.position",
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} title={self.title!r} type={self.release_type.value}>"


class Track(Base):
    """Tabla `tracks`: un tema dentro de una publicacion.

    Cada Track pertenece a UNA sola publicacion (relacion 1:N, sin compartir
    temas entre publicaciones). Si el mismo tema aparece en el disco original y
    en un recopilatorio, hoy son dos filas independientes: es la simplificacion
    deliberada de esta fase. El dia que haga falta un tema "canonico" compartido
    entre publicaciones, se modela como una relacion N:M aparte.
    """

    __tablename__ = "tracks"
    __table_args__ = (
        # Dos temas de la MISMA publicacion no pueden tener el mismo numero.
        UniqueConstraint("release_id", "position", name="uq_tracks_release_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    release_id: Mapped[int] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Numero de pista dentro de la publicacion (1, 2, 3...). Determina el orden.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Nullable: no siempre se conoce la duracion exacta (p. ej. bootlegs).
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    release: Mapped["Release"] = relationship(back_populates="tracks")

    def __repr__(self) -> str:
        return (
            f"<Track id={self.id} release_id={self.release_id} "
            f"position={self.position} title={self.title!r}>"
        )

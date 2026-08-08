"""Modelos ORM del modulo de foro.

Foro de discusion atado al catalogo: la gente propone/discute cambios y
mejoras sobre discos/ediciones (o temas generales), y un administrador decide
que se aplica -- A MANO, con las herramientas de edicion que ya existen en
discografia. Esta fase NO aplica cambios automaticamente, solo organiza la
conversacion.

  ForumThread   (el hilo: titulo, mensaje inicial, a que se refiere, estado)
    -> ForumComment  (respuestas al hilo, en orden cronologico)

Frontera entre modulos: `author_id`/`thread_id`/etc. son FK sueltas (enteros
con `ForeignKey`), pero este modulo NO define relaciones ORM hacia `User`
(en `auth`) ni hacia `Release`/`Edition` (en `discografia`). Pedir datos de
esas tablas (username del autor, que exista el `entity_id`...) pasa siempre
por la capa de `service` del modulo dueno (`auth.service.get_users_by_ids`,
`discography.service.release_exists`/`edition_exists`), nunca importando sus
modelos aqui -- misma regla de fronteras que ya sigue el resto del proyecto.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ForumEntityType(str, enum.Enum):
    """A que se refiere un hilo. Enum ABIERTO: texto validado por Python +
    CHECK, mismo patron que ReleaseType/ImageType/EditionFormat en
    discografia (no un enum nativo de PostgreSQL) porque se espera que crezca
    (conciertos, libros...) sin tener que tocar el TIPO de la columna, solo
    el CHECK.

    `DISCOGRAPHY` es el "general, sin disco concreto" (p. ej. "deberiamos
    anadir un tipo de release 'directo'"). Quedan fuera de este enum, a
    proposito, los temas SIN `entity_type` en absoluto (ver
    `ForumThread.entity_type`, nullable): eso es "sin tema", un caso
    distinto de "tema general sobre discografia".
    """

    RELEASE = "release"
    EDITION = "edition"
    DISCOGRAPHY = "discography"


class ThreadStatus(str, enum.Enum):
    """Estado de un hilo. Mismo patron enum-como-texto que ForumEntityType."""

    OPEN = "open"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ForumThread(Base):
    """Tabla `forum_threads`: un hilo de discusion sobre el catalogo (o
    general, sin disco concreto).
    """

    __tablename__ = "forum_threads"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Mensaje inicial. Text (sin limite de longitud), igual que
    # Release.description o Edition.notes en discografia.
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # FK "suelta": sin relationship() hacia User (ver docstring del modulo).
    # ondelete=CASCADE: si se borra el usuario, sus hilos desaparecen con el.
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # A que entidad del catalogo se refiere el hilo. Nullable DESDE YA aunque
    # la app todavia no cree hilos con entity_type=None: es el hueco para
    # "posts sin tema" (llegara mas adelante) sin tener que tocar el esquema
    # otra vez.
    entity_type: Mapped[ForumEntityType | None] = mapped_column(
        Enum(
            ForumEntityType,
            native_enum=False,
            create_constraint=True,
            name="ck_forum_threads_entity_type",
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    # El disco/edicion concreto cuando entity_type es "release"/"edition";
    # None en cualquier otro caso (validado en el schema y en el service, ver
    # forum/schemas.py::ThreadCreate y forum/service.py::_validate_entity).
    # SIN FK real: el destino cambia segun entity_type (releases.id O
    # editions.id), y una FK no puede apuntar a "una tabla u otra".
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[ThreadStatus] = mapped_column(
        Enum(
            ThreadStatus,
            native_enum=False,
            create_constraint=True,
            name="ck_forum_threads_status",
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ThreadStatus.OPEN,
        nullable=False,
    )
    # Motivo opcional al resolver/cerrar (p. ej. "Aplicado en la edicion X").
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    comments: Mapped[list["ForumComment"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ForumComment.created_at",
    )

    def __repr__(self) -> str:
        return f"<ForumThread id={self.id} title={self.title!r} status={self.status.value}>"


class ForumComment(Base):
    """Tabla `forum_comments`: una respuesta dentro de un hilo."""

    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(primary_key=True)

    thread_id: Mapped[int] = mapped_column(
        ForeignKey("forum_threads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # FK suelta, mismo motivo que ForumThread.author_id.
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    thread: Mapped["ForumThread"] = relationship(back_populates="comments")

    def __repr__(self) -> str:
        return f"<ForumComment id={self.id} thread_id={self.thread_id}>"

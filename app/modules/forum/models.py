"""Modelos ORM del modulo de foro.

Foro de discusion atado al catalogo: la gente propone/discute cambios y
mejoras sobre discos/ediciones (o temas generales), y un administrador decide
que se aplica -- A MANO, con las herramientas de edicion que ya existen en
discografia. Esta fase NO aplica cambios automaticamente, solo organiza la
conversacion.

  Subforum      (seccion del foro: "Discusiones", futuro "Anuncios"...)
    -> ForumThread   (el hilo: titulo, mensaje inicial, a que se refiere, estado)
         -> ForumComment  (respuestas al hilo, en orden cronologico)

`Subforum` y `ForumThread` viven en el MISMO modulo, asi que su relacion es una
`relationship()` de SQLAlchemy normal (a diferencia de `author_id`/`entity_id`,
que cruzan a `auth`/`discografia` -- ver mas abajo).

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


class Subforum(Base):
    """Tabla `subforums`: una seccion del foro (p. ej. "Discusiones", futuro
    "Anuncios", "Ayuda"...). Todo `ForumThread` vive dentro de un subforo.

    Hoy solo existe uno ("Discusiones", sembrado por la migracion que anadio
    esta tabla), que agrupa todos los hilos que ya existian (los que se abren
    desde un disco, una edicion, o de discografia en general). El modelo ya
    esta pensado para varios sin tener que volver a tocar el esquema; el CRUD
    de subforos desde la API queda pendiente hasta que haga falta un segundo.
    """

    __tablename__ = "subforums"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nombre de un SF Symbol (icono nativo de iOS), p. ej.
    # "bubble.left.and.bubble.right". Texto libre: la API no valida que sea un
    # SF Symbol real, eso es responsabilidad de la app.
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Orden de aparicion en el listado de subforos. Entero simple, SIN
    # restriccion UNIQUE (mismo criterio que Image.position en discografia):
    # con pocos subforos gestionados a mano, no hace falta mas.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    threads: Mapped[list["ForumThread"]] = relationship(back_populates="subforum")

    def __repr__(self) -> str:
        return f"<Subforum id={self.id} name={self.name!r}>"


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

    # Todo hilo vive dentro de un subforo (obligatorio, a diferencia de
    # entity_type/entity_id). RESTRICT: no se puede borrar un subforo con
    # hilos dentro (mismo criterio que Label/Recording en discografia) --
    # relevante el dia que exista un DELETE de subforos, hoy no hay ninguno.
    subforum_id: Mapped[int] = mapped_column(
        ForeignKey("subforums.id", ondelete="RESTRICT"), index=True, nullable=False
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

    subforum: Mapped["Subforum"] = relationship(back_populates="threads")
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

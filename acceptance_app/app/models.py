"""SQLAlchemy модели доменной области «Сдача-приёмка квартир»."""
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, Boolean, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Справочники статусов и типов (порядок важен — используется для шахматки)
# ---------------------------------------------------------------------------

VIOLATION_STATUSES = [
    ("to_fix", "К устранению", "#e53935"),        # красный
    ("in_work", "В работе", "#fb8c00"),           # оранжевый
    ("on_check", "На проверке", "#1e88e5"),       # синий
    ("fixed", "Устранено", "#43a047"),            # зелёный
    ("closed", "Закрыто", "#9e9e9e"),             # серый
]

ROOM_STATUSES = [
    ("not_inspected", "Не осмотрено", "#bdbdbd"),
    ("ready_to_transfer", "Готово к передаче", "#43a047"),
    ("warranty", "Гарантия", "#8e24aa"),
    ("violations_found", "Выявлены нарушения", "#e53935"),
    ("transferred_with_remarks", "Переданы с замечанием", "#fdd835"),
    ("finishing_accepted", "Приняты отделочные работы", "#00acc1"),
    ("refused", "Отказано", "#37474f"),
]

FINISH_TYPES = [
    ("rough", "Черновая"),
    ("white_box", "White box"),
    ("final", "Чистовая"),
    ("hybrid_white_box", "Гибридный white box"),
]

PREMISES_KINDS = [("residential", "Жилое"), ("non_residential", "Нежилое")]


def status_keys(pairs):
    return [k for k, *_ in pairs]


VIOLATION_STATUS_KEYS = status_keys(VIOLATION_STATUSES)
ROOM_STATUS_KEYS = status_keys(ROOM_STATUSES)
FINISH_TYPE_KEYS = status_keys([ (k, v) for k, v in FINISH_TYPES ])
PREMISES_KIND_KEYS = status_keys(PREMISES_KINDS)


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Пользователи и сотрудники
# ---------------------------------------------------------------------------

class User(Base):
    """Учётная запись сотрудника. access_level: 1 — просмотр,
    2 — инспектор (осмотры/нарушения), 3 — администратор (объекты)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    hashed_password: Mapped[str] = mapped_column(String(256))
    access_level: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    assignments: Mapped[list["ObjectEmployee"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan")


class Object(Base):
    """Объект строительства (ЖК)."""
    __tablename__ = "objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    buildings: Mapped[list["Building"]] = relationship(
        back_populates="object", cascade="all, delete-orphan")
    employees: Mapped[list["ObjectEmployee"]] = relationship(
        back_populates="object", cascade="all, delete-orphan")


class Building(Base):
    """Корпус, прикреплённый к объекту."""
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("object_id", "name", name="uq_building_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(String(300), default="")
    name: Mapped[str] = mapped_column(String(120))          # напр. «Корпус 1»
    floors: Mapped[int] = mapped_column(Integer, default=1)
    apartments_per_floor: Mapped[int] = mapped_column(Integer, default=1)  # квартир на этаж ОДНОГО подъезда
    entrances: Mapped[int] = mapped_column(Integer, default=1)  # количество подъездов

    @property
    def total_rooms(self) -> int:
        """Общее количество помещений: этажи × подъезды × квартир на этаж."""
        return self.floors * max(self.entrances or 1, 1) * self.apartments_per_floor

    object: Mapped["Object"] = relationship(back_populates="buildings")
    rooms: Mapped[list["Room"]] = relationship(
        back_populates="building", cascade="all, delete-orphan")


class ObjectEmployee(Base):
    """Прикрепление сотрудника к объекту."""
    __tablename__ = "object_employees"
    __table_args__ = (UniqueConstraint("object_id", "employee_id", name="uq_object_employee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    object: Mapped["Object"] = relationship(back_populates="employees")
    employee: Mapped["User"] = relationship(back_populates="assignments")


class Room(Base):
    """Помещение (квартира). kind: residential / non_residential."""
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("building_id", "number", name="uq_room_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"))
    number: Mapped[str] = mapped_column(String(32))
    floor: Mapped[int] = mapped_column(Integer, default=1)
    entrance: Mapped[int] = mapped_column(Integer, default=1)   # подъезд
    kind: Mapped[str] = mapped_column(String(32), default="residential")
    finish_type: Mapped[str] = mapped_column(String(32), default="rough")
    status: Mapped[str] = mapped_column(String(40), default="not_inspected")
    area: Mapped[float] = mapped_column(Integer, default=0)  # м² (целое достаточно для UI)
    buyer_info: Mapped[str] = mapped_column(Text, default="")
    acceptance_act_filename: Mapped[str] = mapped_column(String(300), default="")
    acceptance_act_path: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow)

    building: Mapped["Building"] = relationship(back_populates="rooms")
    violations: Mapped[list["Violation"]] = relationship(
        back_populates="room", cascade="all, delete-orphan",
        order_by="Violation.created_at")


class Violation(Base):
    """Карточка нарушения. История (events) не удаляется — только добавляется."""
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300), default="Нарушение")
    status: Mapped[str] = mapped_column(String(20), default="to_fix")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow)

    room: Mapped["Room"] = relationship(back_populates="violations")
    events: Mapped[list["ViolationEvent"]] = relationship(
        back_populates="violation", cascade="all, delete-orphan",
        order_by="ViolationEvent.created_at")


class ViolationEvent(Base):
    """Запись истории осмотра: фото нарушения + текст ИЛИ фото исправления + текст.
    Сообщения из истории удалять нельзя (API DELETE отсутствует намеренно)."""
    __tablename__ = "violation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="inspection")  # inspection|fix
    text: Mapped[str] = mapped_column(Text, default="")
    photo_filename: Mapped[str] = mapped_column(String(300), default="")
    photo_path: Mapped[str] = mapped_column(String(500), default="")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    violation: Mapped["Violation"] = relationship(back_populates="events")
    author: Mapped["User"] = relationship()

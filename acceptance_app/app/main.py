"""FastAPI-приложение для системы сдачи-приёмки квартир."""
import base64
import io
import json
import os
import shutil
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import (
    FastAPI, Depends, HTTPException, UploadFile, File, Form, Request,
)
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select, delete
from sqlalchemy.orm import Session, sessionmaker, selectinload

from .models import (
    Base, User, Object, Building, ObjectEmployee, Room, Violation, ViolationEvent,
    VIOLATION_STATUSES, ROOM_STATUSES, FINISH_TYPES, PREMISES_KINDS,
    VIOLATION_STATUS_KEYS, ROOM_STATUS_KEYS, FINISH_TYPE_KEYS, PREMISES_KIND_KEYS,
    utcnow,
)

# ---------------------------------------------------------------------------
# Настройка БД / пути
# ---------------------------------------------------------------------------

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # acceptance_app/
DATA_DIR = os.path.join(APP_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_URL = os.environ.get("ACCEPTANCE_DB_URL", f"sqlite:///{os.path.join(DATA_DIR, 'acceptance.sqlite3')}")
SECRET_KEY = os.environ.get("ACCEPTANCE_SECRET", "dev-secret-change-me")
TOKEN_TTL_HOURS = 12

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="Сдача-приёмка квартир", version="1.0")


@app.exception_handler(405)
def _405_handler(request: Request, exc):
    """Дружелюбный ответ вместо голого «Method Not Allowed»: подсказываем,
    какой метод нужен для данного пути (защита от старого закешированного JS)."""
    from starlette.routing import Match
    route_methods = set()
    for r in app.routes:
        match, _ = r.matches(request.scope)
        if match == Match.FULL and hasattr(r, "methods"):
            route_methods |= r.methods
    hint = ""
    if route_methods:
        hint = f". Допустимые методы для этого пути: {', '.join(sorted(route_methods))}"
    return JSONResponse({"detail": f"Метод {request.method} не поддерживается для {request.url.path}{hint}. "
                                   f"Обновите страницу с очисткой кэша (Ctrl+F5)."}, status_code=405)


class NoCacheStaticFiles(StaticFiles):
    """Статика без кэширования: браузер всегда получает свежий JS/CSS
    (защита от «Method Not Allowed» из-за закешированного старого app.js)."""

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp


app.mount("/static", NoCacheStaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ---------------------------------------------------------------------------
# Простые подписные токены (HMAC-SHA256), без внешних JWT-зависимостей
# ---------------------------------------------------------------------------

import hashlib
import hmac

SHA256 = hashlib.sha256


def _make_token(user_id: int, level: int) -> str:
    payload = json.dumps(
        {"uid": user_id, "lvl": level,
         "exp": (datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()},
        separators=(",", ":")).encode()
    b64 = base64.urlsafe_b64encode(payload).decode()
    sig = hmac.new(SECRET_KEY.encode(), b64.encode(), SHA256).hexdigest()[:32]
    return f"{b64}.{sig}"


def _check_token(token: str) -> Optional[int]:
    try:
        b64, sig = token.rsplit(".", 1)
        expect = hmac.new(SECRET_KEY.encode(), b64.encode(), SHA256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64.encode()))
        if payload["exp"] < datetime.now(timezone.utc).timestamp():
            return None
        return payload["uid"]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Пароли: pbkdf2 (стандартная библиотека, без bcrypt-проблем)
# ---------------------------------------------------------------------------

import hashlib as _h
import secrets as _s

PBKDF2_ROUNDS = 120_000


def hash_password(password: str) -> str:
    salt = _s.token_bytes(16)
    dk = _h.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        dk = _h.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ROUNDS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Зависимости авторизации и уровней доступа
# ---------------------------------------------------------------------------

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("token", "")
    uid = _check_token(token) if token else None
    if not uid:
        raise HTTPException(401, "Не авторизован")
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(401, "Учётная запись неактивна")
    return user


def require_level(min_level: int):
    def dep(user: User = Depends(current_user)) -> User:
        if user.access_level < min_level:
            raise HTTPException(403, f"Требуется уровень доступа {min_level}")
        return user
    return dep


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    access_level: int = Field(1, ge=1, le=3)


class ObjectIn(BaseModel):
    name: str
    description: str = ""


class BuildingIn(BaseModel):
    name: str
    address: str = ""
    floors: int = Field(1, ge=1, le=200)
    apartments_per_floor: int = Field(1, ge=1, le=100)
    entrances: int = Field(1, ge=1, le=50)   # количество подъездов
    generate_rooms: bool = True


class RoomIn(BaseModel):
    number: str
    floor: int = 1
    entrance: int = 1
    kind: str = "residential"
    finish_type: str = "rough"
    status: str = "not_inspected"
    area: float = 0
    buyer_info: str = ""


class RoomPatch(BaseModel):
    number: Optional[str] = None
    floor: Optional[int] = None
    entrance: Optional[int] = None
    kind: Optional[str] = None
    finish_type: Optional[str] = None
    status: Optional[str] = None
    area: Optional[float] = None
    buyer_info: Optional[str] = None


class ViolationIn(BaseModel):
    title: str = "Нарушение"
    status: str = "to_fix"


class ViolationStatusIn(BaseModel):
    status: str


class EmployeeAssignIn(BaseModel):
    employee_id: int


# ---------------------------------------------------------------------------
# Утилиты сериализации
# ---------------------------------------------------------------------------

LABELS = {
    "violation_status": {k: (t, c) for k, t, c in VIOLATION_STATUSES},
    "room_status": {k: (t, c) for k, t, c in ROOM_STATUSES},
    "finish": {k: t for k, t in FINISH_TYPES},
    "kind": {k: t for k, t in PREMISES_KINDS},
}


def room_json(r: Room) -> dict:
    st = LABELS["room_status"].get(r.status, (r.status, "#bdbdbd"))
    return {
        "id": r.id, "number": r.number, "floor": r.floor,
        "entrance": getattr(r, "entrance", 1) or 1,
        "kind": r.kind, "kind_label": LABELS["kind"].get(r.kind, r.kind),
        "finish_type": r.finish_type,
        "finish_label": LABELS["finish"].get(r.finish_type, r.finish_type),
        "status": r.status, "status_label": st[0], "status_color": st[1],
        "area": r.area, "buyer_info": r.buyer_info,
        "acceptance_act_filename": r.acceptance_act_filename,
        "violations_count": len(r.violations),
        "open_violations": sum(1 for v in r.violations if v.status not in ("fixed", "closed")),
    }


def status_counts(rooms: list[Room]) -> dict:
    counts = {k: 0 for k, *_ in ROOM_STATUSES}
    for r in rooms:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {
        "total": len(rooms),
        "by_status": [
            {"key": k, "label": t, "color": c, "count": counts.get(k, 0)}
            for k, t, c in ROOM_STATUSES
        ],
    }


def violation_json(v: Violation) -> dict:
    st = LABELS["violation_status"].get(v.status, (v.status, "#9e9e9e"))
    return {
        "id": v.id, "title": v.title, "status": v.status,
        "status_label": st[0], "status_color": st[1],
        "created_at": v.created_at.isoformat(),
        "events": [{
            "id": e.id, "kind": e.kind, "text": e.text,
            # храним имя файла на диске — так бекап/восстановление не теряют фото;
            # в UI отображается исходное имя через photo_original
            "photo": e.photo_path and os.path.basename(e.photo_path) or "",
            "photo_original": e.photo_filename,
            "author": e.author.full_name or e.author.username if e.author else "",
            "created_at": e.created_at.isoformat(),
        } for e in v.events],
    }


def save_upload(f: UploadFile) -> tuple[str, str]:
    """Сохраняет файл в uploads/, возвращает (stored_name, original_name)."""
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".doc", ".docx"):
        raise HTTPException(400, f"Недопустимый тип файла: {ext or 'без расширения'}")
    stored = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as out:
        shutil.copyfileobj(f.file, out)
    return stored, f.filename or stored


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

@app.post("/api/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username))
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "Неверный логин или пароль")
    if not user.is_active:
        raise HTTPException(403, "Учётная запись заблокирована")
    token = _make_token(user.id, user.access_level)
    resp = JSONResponse({
        "token": token,
        "user": {"id": user.id, "username": user.username,
                 "full_name": user.full_name, "access_level": user.access_level},
    })
    resp.set_cookie("token", token, httponly=True, samesite="lax",
                    max_age=TOKEN_TTL_HOURS * 3600)
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("token")
    return resp


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username,
            "full_name": user.full_name, "access_level": user.access_level}


# --- справочники ---
@app.get("/api/meta")
def meta(user: User = Depends(current_user)):
    return {
        "violation_statuses": [{"key": k, "label": t, "color": c} for k, t, c in VIOLATION_STATUSES],
        "room_statuses": [{"key": k, "label": t, "color": c} for k, t, c in ROOM_STATUSES],
        "finish_types": [{"key": k, "label": t} for k, t in FINISH_TYPES],
        "premises_kinds": [{"key": k, "label": t} for k, t in PREMISES_KINDS],
    }


# ---------------------------------------------------------------------------
# Сотрудники (уровень 3)
# ---------------------------------------------------------------------------

@app.get("/api/employees")
def list_employees(db: Session = Depends(get_db), user: User = Depends(require_level(3))):
    users = db.scalars(select(User).order_by(User.username)).all()
    return [{"id": u.id, "username": u.username, "full_name": u.full_name,
             "access_level": u.access_level, "is_active": u.is_active} for u in users]


@app.post("/api/employees", status_code=201)
def create_employee(data: UserIn, db: Session = Depends(get_db),
                    user: User = Depends(require_level(3))):
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(409, "Логин уже существует")
    u = User(username=data.username, full_name=data.full_name,
             hashed_password=hash_password(data.password),
             access_level=data.access_level)
    db.add(u)
    db.commit()
    return {"id": u.id}


@app.patch("/api/employees/{uid}")
def update_employee(uid: int, full_name: str | None = None, access_level: int | None = None,
                    is_active: bool | None = None, password: str | None = None,
                    db: Session = Depends(get_db), user: User = Depends(require_level(3))):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Сотрудник не найден")
    if full_name is not None:
        u.full_name = full_name
    if access_level is not None and 1 <= access_level <= 3:
        u.access_level = access_level
    if is_active is not None:
        u.is_active = is_active
    if password:
        u.hashed_password = hash_password(password)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Объекты
# ---------------------------------------------------------------------------

@app.get("/api/objects")
def list_objects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    objs = db.scalars(
        select(Object).options(
            selectinload(Object.buildings).selectinload(Building.rooms)
        ).order_by(Object.name)
    ).all()
    result = []
    for o in objs:
        all_rooms = [r for b in o.buildings for r in b.rooms]
        result.append({
            "id": o.id, "name": o.name, "description": o.description,
            "buildings_count": len(o.buildings),
            "stats": status_counts(all_rooms),
        })
    return result


@app.get("/api/objects/{oid}")
def get_object(oid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    o = db.scalar(select(Object).where(Object.id == oid).options(
        selectinload(Object.buildings).selectinload(Building.rooms).selectinload(Room.violations),
        selectinload(Object.employees).selectinload(ObjectEmployee.employee),
    ))
    if not o:
        raise HTTPException(404, "Объект не найден")
    buildings = []
    for b in sorted(o.buildings, key=lambda x: x.name):
        buildings.append({
            "id": b.id, "name": b.name, "address": b.address,
            "floors": b.floors, "apartments_per_floor": b.apartments_per_floor,
            "entrances": getattr(b, "entrances", 1) or 1,
            "total_rooms": b.total_rooms,
            "stats": status_counts(b.rooms),
        })
    employees = [{
        "assignment_id": a.id, "id": a.employee.id,
        "username": a.employee.username, "full_name": a.employee.full_name,
        "access_level": a.employee.access_level,
    } for a in o.employees]
    return {"id": o.id, "name": o.name, "description": o.description,
            "buildings": buildings, "employees": employees}


@app.post("/api/objects", status_code=201)
def create_object(data: ObjectIn, db: Session = Depends(get_db),
                  user: User = Depends(require_level(3))):
    if db.scalar(select(Object).where(Object.name == data.name)):
        raise HTTPException(409, "Объект с таким названием уже существует")
    o = Object(name=data.name, description=data.description)
    db.add(o)
    db.commit()
    return {"id": o.id}


@app.patch("/api/objects/{oid}")
def update_object(oid: int, data: ObjectIn, db: Session = Depends(get_db),
                  user: User = Depends(require_level(3))):
    o = db.get(Object, oid)
    if not o:
        raise HTTPException(404, "Объект не найден")
    clash = db.scalar(select(Object).where(Object.name == data.name, Object.id != oid))
    if clash:
        raise HTTPException(409, "Объект с таким названием уже существует")
    o.name, o.description = data.name, data.description
    db.commit()
    return {"ok": True}


@app.delete("/api/objects/{oid}")
def delete_object(oid: int, db: Session = Depends(get_db),
                  user: User = Depends(require_level(3))):
    o = db.get(Object, oid)
    if not o:
        raise HTTPException(404, "Объект не найден")
    db.delete(o)
    db.commit()
    return {"ok": True}


# --- корпуса ---

@app.post("/api/objects/{oid}/buildings", status_code=201)
def create_building(oid: int, data: BuildingIn, db: Session = Depends(get_db),
                    user: User = Depends(require_level(3))):
    o = db.get(Object, oid)
    if not o:
        raise HTTPException(404, "Объект не найден")
    if db.scalar(select(Building).where(Building.object_id == oid, Building.name == data.name)):
        raise HTTPException(409, "Корпус с таким названием уже есть в объекте")
    b = Building(object_id=oid, name=data.name, address=data.address,
                 floors=data.floors, apartments_per_floor=data.apartments_per_floor,
                 entrances=data.entrances)
    db.add(b)
    db.flush()
    if data.generate_rooms:
        # apartments_per_floor — квартир на этаж ОДНОГО подъезда;
        # всего помещений = этажи × подъезды × квартир на этаж.
        # Нумерация сквозная по подъездам: сначала весь 1-й подъезд
        # (снизу вверх), затем 2-й и т.д.
        per = data.apartments_per_floor
        for en in range(1, data.entrances + 1):
            for fl in range(1, data.floors + 1):
                for i in range(1, per + 1):
                    n = (en - 1) * data.floors * per + (fl - 1) * per + i
                    db.add(Room(building_id=b.id, number=str(n), floor=fl,
                                entrance=en,
                                kind="residential", finish_type="rough",
                                status="not_inspected"))
    db.commit()
    return {"id": b.id}


@app.patch("/api/buildings/{bid}")
def update_building(bid: int, data: BuildingIn, db: Session = Depends(get_db),
                    user: User = Depends(require_level(3))):
    b = db.get(Building, bid)
    if not b:
        raise HTTPException(404, "Корпус не найден")
    b.name, b.address = data.name, data.address
    b.floors, b.apartments_per_floor = data.floors, data.apartments_per_floor
    b.entrances = data.entrances
    db.commit()
    return {"ok": True}


@app.delete("/api/buildings/{bid}")
def delete_building(bid: int, db: Session = Depends(get_db),
                    user: User = Depends(require_level(3))):
    b = db.get(Building, bid)
    if not b:
        raise HTTPException(404, "Корпус не найден")
    db.delete(b)
    db.commit()
    return {"ok": True}


@app.post("/api/buildings/{bid}/generate")
async def regenerate_rooms(bid: int, request: Request,
                           db: Session = Depends(get_db), user: User = Depends(require_level(3))):
    """Массовая генерация квартир по этажам. Существующие номера сохраняются.

    Параметры floors / per_floor / entrances принимаются и как JSON-тело,
    и как query-параметры или форма — чтобы любой вариант клиента работал.
    """
    b = db.get(Building, bid)
    if not b:
        raise HTTPException(404, "Корпус не найден")
    data = {}
    try:
        ct = request.headers.get("content-type", "")
        if "application/json" in ct:
            data = await request.json()
        elif "multipart/form-data" in ct or "application/x-www-form-urlencoded" in ct:
            fd = await request.form()
            data = {k: fd[k] for k in fd}
    except Exception:
        data = {}
    def pick(key, default=None):
        v = data.get(key, request.query_params.get(key, default))
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    floors = pick("floors")
    per_floor = pick("per_floor")
    entrances = pick("entrances")
    if floors is None or per_floor is None:
        raise HTTPException(422, "Укажите floors и per_floor")
    b.floors, b.apartments_per_floor = floors, per_floor
    b.entrances = max(entrances or b.entrances or 1, 1)
    existing_numbers = {r.number for r in b.rooms}
    added = 0
    # apartments_per_floor — квартир на этаж одного подъезда.
    # Нумерация сквозная по подъездам: сначала весь 1-й подъезд (снизу вверх),
    # затем 2-й и т.д.
    for en in range(1, b.entrances + 1):
        for fl in range(1, floors + 1):
            for i in range(1, per_floor + 1):
                n = (en - 1) * floors * per_floor + (fl - 1) * per_floor + i
                if str(n) not in existing_numbers:
                    db.add(Room(building_id=b.id, number=str(n), floor=fl,
                                entrance=en, status="not_inspected"))
                    existing_numbers.add(str(n))
                    added += 1
    db.commit()
    return {"added": added, "total_numbers": floors * b.entrances * per_floor}


# --- сотрудники объекта ---

@app.post("/api/objects/{oid}/employees", status_code=201)
def assign_employee(oid: int, data: EmployeeAssignIn, db: Session = Depends(get_db),
                    user: User = Depends(require_level(3))):
    if not db.get(Object, oid):
        raise HTTPException(404, "Объект не найден")
    emp = db.get(User, data.employee_id)
    if not emp:
        raise HTTPException(404, "Сотрудник не найден")
    exists = db.scalar(select(ObjectEmployee).where(
        ObjectEmployee.object_id == oid, ObjectEmployee.employee_id == data.employee_id))
    if exists:
        raise HTTPException(409, "Сотрудник уже прикреплён")
    a = ObjectEmployee(object_id=oid, employee_id=data.employee_id)
    db.add(a)
    db.commit()
    return {"id": a.id}


@app.delete("/api/objects/{oid}/employees/{assignment_id}")
def unassign_employee(oid: int, assignment_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_level(3))):
    a = db.get(ObjectEmployee, assignment_id)
    if not a or a.object_id != oid:
        raise HTTPException(404, "Прикрепление не найдено")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Помещения (просмотр — ≥1, редактирование — ≥2)
# ---------------------------------------------------------------------------

@app.get("/api/buildings/{bid}/rooms")
def list_rooms(bid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = db.get(Building, bid)
    if not b:
        raise HTTPException(404, "Корпус не найден")
    rooms = db.scalars(select(Room).where(Room.building_id == bid)
                       .options(selectinload(Room.violations))
                       .order_by(Room.floor.desc(), Room.number)).all()
    return {"rooms": [room_json(r) for r in rooms],
            "entrances": getattr(b, "entrances", 1) or 1}


@app.get("/api/rooms/{rid}")
def get_room(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.scalar(select(Room).where(Room.id == rid).options(
        selectinload(Room.violations).selectinload(Violation.events).selectinload(ViolationEvent.author),
        selectinload(Room.building).selectinload(Building.object)))
    b = r.building
    return {
        **room_json(r),
        "building": {"id": b.id, "name": b.name, "address": b.address,
                       "entrances": getattr(b, "entrances", 1) or 1},
        "object": {"id": b.object.id, "name": b.object.name},
        "violations": [violation_json(v) for v in r.violations],
    }


@app.post("/api/buildings/{bid}/rooms", status_code=201)
def create_room(bid: int, data: RoomIn, db: Session = Depends(get_db),
                user: User = Depends(require_level(2))):
    b = db.get(Building, bid)
    if not b:
        raise HTTPException(404, "Корпус не найден")
    if data.kind not in PREMISES_KIND_KEYS:
        raise HTTPException(400, "Неверный тип помещения")
    if data.finish_type not in FINISH_TYPE_KEYS:
        raise HTTPException(400, "Неверный тип отделки")
    if data.status not in ROOM_STATUS_KEYS:
        raise HTTPException(400, "Неверный статус")
    if db.scalar(select(Room).where(Room.building_id == bid, Room.number == data.number)):
        raise HTTPException(409, "Помещение с таким номером уже существует")
    r = Room(building_id=bid, **data.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@app.patch("/api/rooms/{rid}")
def patch_room(rid: int, data: RoomPatch, db: Session = Depends(get_db),
               user: User = Depends(require_level(2))):
    r = db.get(Room, rid)
    if not r:
        raise HTTPException(404, "Помещение не найдено")
    upd = data.model_dump(exclude_none=True)
    if "kind" in upd and upd["kind"] not in PREMISES_KIND_KEYS:
        raise HTTPException(400, "Неверный тип помещения")
    if "finish_type" in upd and upd["finish_type"] not in FINISH_TYPE_KEYS:
        raise HTTPException(400, "Неверный тип отделки")
    if "status" in upd and upd["status"] not in ROOM_STATUS_KEYS:
        raise HTTPException(400, "Неверный статус")
    if "number" in upd:
        clash = db.scalar(select(Room).where(Room.building_id == r.building_id,
                                             Room.number == upd["number"], Room.id != rid))
        if clash:
            raise HTTPException(409, "Помещение с таким номером уже существует")
    if "entrance" in upd and upd["entrance"] < 1:
        raise HTTPException(400, "Некорректный подъезд")
    for k, v in upd.items():
        setattr(r, k, v)
    db.commit()
    return {"ok": True}


@app.delete("/api/rooms/{rid}")
def delete_room(rid: int, db: Session = Depends(get_db),
                user: User = Depends(require_level(3))):
    r = db.get(Room, rid)
    if not r:
        raise HTTPException(404, "Помещение не найдено")
    db.delete(r)
    db.commit()
    return {"ok": True}


# --- акт приёма-передачи ---

@app.post("/api/rooms/{rid}/act")
async def upload_act(rid: int, file: UploadFile = File(...),
                     db: Session = Depends(get_db), user: User = Depends(require_level(2))):
    r = db.get(Room, rid)
    if not r:
        raise HTTPException(404, "Помещение не найдено")
    stored, orig = save_upload(file)
    r.acceptance_act_path, r.acceptance_act_filename = stored, orig
    db.commit()
    return {"ok": True, "filename": orig}


@app.get("/api/rooms/{rid}/act")
def download_act(rid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(Room, rid)
    if not r or not r.acceptance_act_path:
        raise HTTPException(404, "Акт не прикреплён")
    path = os.path.join(UPLOAD_DIR, r.acceptance_act_path)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл акта утерян")
    return FileResponse(path, filename=r.acceptance_act_filename)


# ---------------------------------------------------------------------------
# Нарушения и история осмотров (уровень 2)
# ---------------------------------------------------------------------------

@app.post("/api/rooms/{rid}/violations", status_code=201)
async def create_violation(rid: int, title: str = Form("Нарушение"),
                           status: str = Form("to_fix"),
                           text: str = Form(""), photo: Optional[UploadFile] = File(None),
                           db: Session = Depends(get_db), user: User = Depends(require_level(2))):
    r = db.get(Room, rid)
    if not r:
        raise HTTPException(404, "Помещение не найдено")
    if status not in VIOLATION_STATUS_KEYS:
        raise HTTPException(400, "Неверный статус нарушения")
    v = Violation(room_id=rid, title=title, status=status, created_by_id=user.id)
    db.add(v)
    db.flush()
    stored, orig = ("", "")
    if photo and photo.filename:
        stored, orig = save_upload(photo)
    db.add(ViolationEvent(violation_id=v.id, kind="inspection", text=text,
                          photo_filename=orig, photo_path=stored, author_id=user.id))
    if r.status == "not_inspected":
        r.status = "violations_found"
    db.commit()
    return {"id": v.id}


@app.get("/api/violations/{vid}")
def get_violation(vid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    v = db.scalar(select(Violation).where(Violation.id == vid).options(
        selectinload(Violation.events).selectinload(ViolationEvent.author)))
    if not v:
        raise HTTPException(404, "Нарушение не найдено")
    return violation_json(v)


@app.patch("/api/violations/{vid}/status")
def set_violation_status(vid: int, data: ViolationStatusIn, db: Session = Depends(get_db),
                         user: User = Depends(require_level(2))):
    v = db.get(Violation, vid)
    if not v:
        raise HTTPException(404, "Нарушение не найдено")
    if data.status not in VIOLATION_STATUS_KEYS:
        raise HTTPException(400, "Неверный статус нарушения")
    v.status = data.status
    db.commit()
    st = LABELS["violation_status"][data.status]
    return {"ok": True, "status_label": st[0], "status_color": st[1]}


@app.post("/api/violations/{vid}/events")
async def add_violation_event(vid: int, kind: str = Form("inspection"),
                              text: str = Form(""), photo: Optional[UploadFile] = File(None),
                              db: Session = Depends(get_db), user: User = Depends(require_level(2))):
    """Добавить запись в историю осмотра. УДАЛЕНИЕ записей истории не предусмотрено."""
    v = db.get(Violation, vid)
    if not v:
        raise HTTPException(404, "Нарушение не найдено")
    if kind not in ("inspection", "fix"):
        raise HTTPException(400, "Неверный тип записи")
    if not text and not (photo and photo.filename):
        raise HTTPException(400, "Укажите текст или приложите фото")
    stored, orig = ("", "")
    if photo and photo.filename:
        stored, orig = save_upload(photo)
    e = ViolationEvent(violation_id=vid, kind=kind, text=text,
                       photo_filename=orig, photo_path=stored, author_id=user.id)
    db.add(e)
    db.commit()
    return {"id": e.id}


# ---------------------------------------------------------------------------
# Бекап / восстановление (zip: data.json + файлы uploads)
# ---------------------------------------------------------------------------

@app.get("/api/backup")
def make_backup(db: Session = Depends(get_db), user: User = Depends(require_level(3))):
    def dt(x):
        return x.isoformat() if isinstance(x, datetime) else x

    data = {"exported_at": utcnow().isoformat(), "version": 1,
            "users": [], "objects": [], "buildings": [], "object_employees": [],
            "rooms": [], "violations": [], "violation_events": []}
    for u in db.scalars(select(User)):
        data["users"].append({c.name: dt(getattr(u, c.name)) for c in u.__table__.columns})
    for model, key in [(Object, "objects"), (Building, "buildings"),
                       (ObjectEmployee, "object_employees"), (Room, "rooms"),
                       (Violation, "violations"), (ViolationEvent, "violation_events")]:
        for row in db.scalars(select(model)):
            data[key].append({c.name: dt(getattr(row, c.name)) for c in model.__table__.columns})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(data, ensure_ascii=False))
        if os.path.isdir(UPLOAD_DIR):
            for fn in os.listdir(UPLOAD_DIR):
                p = os.path.join(UPLOAD_DIR, fn)
                if os.path.isfile(p):
                    z.write(p, f"uploads/{fn}")
    buf.seek(0)
    fname = f"acceptance_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(buf.read(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/restore")
async def restore_backup(file: UploadFile = File(...),
                         db: Session = Depends(get_db), user: User = Depends(require_level(3))):
    """Полное восстановление из zip-бекапа (данные замещаются целиком)."""
    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        data = json.loads(zf.read("data.json").decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Некорректный файл бекапа (ожидался zip с data.json)")

    for model in [ViolationEvent, Violation, Room, ObjectEmployee, Building, Object, User]:
        db.execute(delete(model))
    db.commit()

    order = ["users", "objects", "buildings", "object_employees", "rooms",
             "violations", "violation_events"]
    tables = {"users": User, "objects": Object, "buildings": Building,
              "object_employees": ObjectEmployee, "rooms": Room,
              "violations": Violation, "violation_events": ViolationEvent}
    for key in order:
        for row in data.get(key, []):
            for k, v in row.items():
                if isinstance(v, str) and len(v) >= 19 and v[4:5] == "-" and v[10:11] == "T":
                    try:
                        row[k] = datetime.fromisoformat(v)
                    except ValueError:
                        pass
            db.merge(tables[key](**row))
    db.commit()

    if os.path.isdir(UPLOAD_DIR):
        for fn in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, fn)
            if os.path.isfile(p):
                os.remove(p)
    restored_files = 0
    for name in zf.namelist():
        if name.startswith("uploads/") and not name.endswith("/"):
            fn = os.path.basename(name)
            with open(os.path.join(UPLOAD_DIR, fn), "wb") as out:
                out.write(zf.read(name))
            restored_files += 1
    return {"ok": True, "restored_files": restored_files,
            "counts": {k: len(data.get(k, [])) for k in order}}


# ---------------------------------------------------------------------------
# Веб-интерфейс
# ---------------------------------------------------------------------------

INDEX_HTML_PATH = os.path.join(APP_DIR, "static", "index.html")


@app.get("/", response_class=HTMLResponse)
def index():
    with open(INDEX_HTML_PATH, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Инициализация БД и демо-данных
# ---------------------------------------------------------------------------

def _migrate_add_columns():
    """Добавляет новые колонки (entrances/entrance) в уже существующую SQLite-базу."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            def cols(table):
                return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            bc = cols("buildings")
            if bc and "entrances" not in bc:
                conn.execute(text("ALTER TABLE buildings ADD COLUMN entrances INTEGER NOT NULL DEFAULT 1"))
            rc = cols("rooms")
            if rc and "entrance" not in rc:
                conn.execute(text("ALTER TABLE rooms ADD COLUMN entrance INTEGER NOT NULL DEFAULT 1"))
    except Exception as e:  # база ещё не создана или не SQLite — не страшно
        print("migrate skip:", e)


def init_db():
    Base.metadata.create_all(engine)
    _migrate_add_columns()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User)) == 0:
            demo = [
                ("admin", "admin123", "Иванов Иван Иванович", 3),
                ("inspector", "inspector123", "Петров Пётр Петрович", 2),
                ("viewer", "viewer123", "Сидорова Анна Сергеевна", 1),
            ]
            for uname, pwd, fio, lvl in demo:
                db.add(User(username=uname, full_name=fio,
                            hashed_password=hash_password(pwd), access_level=lvl))
            db.commit()

            o = Object(name="ЖК «Северный парк»", description="Первая очередь строительства")
            db.add(o)
            db.flush()
            b = Building(object_id=o.id, name="Корпус 1", address="г. Москва, ул. Парковая, д. 1",
                         floors=3, apartments_per_floor=4, entrances=2)
            db.add(b)
            db.flush()
            statuses = ["not_inspected", "ready_to_transfer", "violations_found",
                        "warranty", "transferred_with_remarks", "finishing_accepted", "refused"]
            finishes = FINISH_TYPE_KEYS
            admin = db.scalar(select(User).where(User.username == "admin"))
            insp = db.scalar(select(User).where(User.username == "inspector"))
            db.add(ObjectEmployee(object_id=o.id, employee_id=insp.id))
            n = 0
            # нумерация сквозная по подъездам: сначала весь 1-й подъезд (снизу вверх), затем 2-й
            for en in (1, 2):
                for fl in range(1, 4):
                    for i in range(1, 5):
                        n += 1
                        db.add(Room(building_id=b.id, number=str(n), floor=fl,
                                    entrance=en,
                                    kind="residential" if n % 7 else "non_residential",
                                    finish_type=finishes[n % 4],
                                    status=statuses[n % 7],
                                    area=35 + n * 3,
                                    buyer_info=f"Покупатель №{n}, ДДУ-{1000 + n}" if n % 2 else ""))
            db.commit()
            room1 = db.scalar(select(Room).where(Room.building_id == b.id, Room.number == "3"))
            v = Violation(room_id=room1.id, title="Трещина на стене балкона",
                          status="to_fix", created_by_id=insp.id)
            db.add(v)
            db.flush()
            db.add(ViolationEvent(violation_id=v.id, kind="inspection",
                                  text="Выявлена сквозная трещина ~40 см при осмотре.",
                                  author_id=insp.id))
            db.add(ViolationEvent(violation_id=v.id, kind="fix",
                                  text="Подрядчик заделал трещину, ждёт проверки.",
                                  author_id=admin.id))
            db.commit()
            print("Инициализирована БД и демо-данные (admin/admin123, inspector/inspector123, viewer/viewer123)")


init_db()

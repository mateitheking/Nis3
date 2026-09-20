"""FastAPI-приложение: живая проверка сессии поверх auth.py/db.py/vault.py.

Костыльно и без дизайна — задача не показать интерфейс, а убедиться, что
кука браузера переживает перезагрузку страницы, что пароль реально не
уходит с сервера повторно на каждый клик, и что источники дают настоящие
данные через ту же сессию.

Запуск: uvicorn apps.api.main:app --reload
"""

from __future__ import annotations

import sys
import json

# Windows-консоль по умолчанию берёт cp1252 для stdout, и print() с
# кириллицей роняет процесс UnicodeEncodeError'ом — не в терминальном
# скрипте с флагом -X utf8, а внутри самого сервера, где такого флага нет.
# Чиним раз и навсегда на уровне процесса, а не понадеявшись на то, чем
# именно его запустят.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")

import os
import random
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from apps.api import assistant as assistant_mod
from apps.api import photos as photos_mod
from apps.api.auth import (
    AppSessionExpired,
    AuthService,
    CircuitOpen,
    EmailTaken,
    InvalidCredentials,
    SESSION_TTL,
)
from apps.api.db import (
    AccountCredential,
    CustomScheduleEntry,
    GradeSnapshot,
    Photo,
    Source,
    SourceCredential,
    SourceSession,
    Student,
    init_db,
    make_engine,
    make_session_factory,
    utcnow,
)
from apps.api.sources.edupage import AuthError as EdupageAuthError
from apps.api.sources.edupage import CaptchaRequired as EdupageCaptchaRequired
from apps.api.sources.edupage import SourceError as EdupageSourceError
from apps.api.sources.sush import AuthError as SushAuthError
from apps.api.sources.sush import ContractError as SushContractError
from apps.api.sources.sush import NetworkError as SushNetworkError
from apps.api.sources.sush import SessionExpired as SushSessionExpired
from apps.api.sources.sush import SourceError as SushSourceError
from apps.api.sources.sush import SushClient
from apps.api.vault import Vault, VaultError, generate_key
from dotenv import load_dotenv

# Корневой .env (гитигнорнут, см. .gitignore) — сюда кладём секреты вроде
# OPENAI_API_KEY, которые не хочется держать голыми в переменных окружения
# системы или запоминать выставлять перед каждым запуском вручную. Явный
# путь, а не полагание на cwd — uvicorn могут запустить из любой директории.
load_dotenv(Path(__file__).parent.parent.parent / ".env")

COOKIE_NAME = "nis_session"
STATIC_DIR = Path(__file__).parent / "static"
_DEV_KEY_FILE = Path(__file__).parent.parent.parent / ".dev-vault-key"


def _load_vault() -> Vault:
    key = os.environ.get("VAULT_KEY")
    if not key:
        # dev-режим: ключ сохраняется в гитигнорённый файл рядом с БД, а не
        # генерируется заново каждый запуск. `uvicorn --reload` перезапускает
        # процесс на каждую правку файла — с ключом только в памяти это
        # обесценивало бы все сохранённые пароли/куки после любого моего
        # редактирования кода, а не только при настоящем перезапуске сервера.
        if _DEV_KEY_FILE.exists():
            key = _DEV_KEY_FILE.read_text(encoding="ascii").strip()
        else:
            key = generate_key()
            _DEV_KEY_FILE.write_text(key, encoding="ascii")
            print(f"[dev] сгенерирован и сохранён ключ в {_DEV_KEY_FILE}")
        os.environ["VAULT_KEY"] = key
    return Vault.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./nis.db")
    app.state.engine = make_engine(db_url)
    init_db(app.state.engine)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.vault = _load_vault()
    yield


app = FastAPI(title="НИШ — костыльная демонстрация сессии", lifespan=lifespan)

# Собранный фронт (apps/web/dist) кладётся сюда шагом сборки Docker-образа —
# см. Dockerfile. Локально в разработке этой папки с ассетами нет (фронт
# крутится отдельно на Vite :5173, см. vite.config.ts), поэтому монтируем
# только если она реально существует — иначе `uvicorn --reload` не
# поднимется вообще на чистом дев-окружении.
_STATIC_ASSETS_DIR = STATIC_DIR / "assets"
if _STATIC_ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_ASSETS_DIR), name="assets")


def get_db():
    db: DbSession = app.state.session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_auth(db: DbSession = Depends(get_db)) -> AuthService:
    return AuthService(db, app.state.vault)


def get_current_student(
    nis_session: Optional[str] = Cookie(None), auth: AuthService = Depends(get_auth)
) -> Student:
    if not nis_session:
        raise HTTPException(401, "не авторизован")
    try:
        return auth.resolve_app_session(nis_session)
    except AppSessionExpired:
        raise HTTPException(401, "сессия истекла, войди заново")


# ---- статика: в проде здесь собранный React (apps/web/dist), см. Dockerfile;
# локально в этой папке остаётся голая демо-страница-заглушка, не дизайн —
# реальная разработка идёт через Vite :5173, сюда никто не заходит вручную.


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---- аккаунт на нашем сайте -------------------------------------------------


class RegisterBody(BaseModel):
    display_name: str
    email: str
    password: str


def _set_session_cookie(response: Response, token: str, *, remember: bool = True) -> None:
    """``remember=False`` — кука сессионная (без ``max_age``): браузер её
    забудет при закрытии, хотя на сервере сама сессия всё ещё жива
    ``SESSION_TTL`` дней — «запомнить меня» решает, переживает ли кука
    закрытие браузера, а не то, сколько живёт сессия на сервере."""
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()) if remember else None,
    )


@app.post("/auth/register")
def register(body: RegisterBody, response: Response, auth: AuthService = Depends(get_auth)):
    if "@" not in body.email or "." not in body.email.split("@")[-1]:
        raise HTTPException(400, "похоже, это не почта")
    if len(body.password) < 8:
        raise HTTPException(400, "пароль слишком короткий (минимум 8 символов)")
    if not body.display_name.strip():
        raise HTTPException(400, "имя не может быть пустым")
    try:
        student = auth.register_account(body.display_name.strip(), body.email, body.password)
    except EmailTaken:
        raise HTTPException(409, "эта почта уже зарегистрирована")
    token = auth.issue_app_session(student)
    _set_session_cookie(response, token)
    return {"student_id": student.id, "display_name": student.display_name}


class LoginBody(BaseModel):
    email: str
    password: str
    remember: bool = True


@app.post("/auth/login")
def login(body: LoginBody, response: Response, auth: AuthService = Depends(get_auth)):
    try:
        student = auth.authenticate(body.email, body.password)
    except InvalidCredentials:
        raise HTTPException(401, "неверная почта или пароль")
    token = auth.issue_app_session(student)
    _set_session_cookie(response, token, remember=body.remember)
    return {"student_id": student.id, "display_name": student.display_name}


@app.post("/auth/logout")
def logout(response: Response, nis_session: Optional[str] = Cookie(None),
           auth: AuthService = Depends(get_auth)):
    if nis_session:
        auth.revoke_app_session(nis_session)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


def _me_json(student: Student, cred: AccountCredential | None) -> dict:
    return {
        "student_id": student.id,
        "display_name": student.display_name,
        "email": cred.email if cred else None,
        "avatar_url": "/api/me/avatar" if student.avatar_storage_path else None,
    }


@app.get("/api/me")
def me(student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)):
    cred = db.scalar(
        select(AccountCredential).where(AccountCredential.student_id == student.id)
    )
    return _me_json(student, cred)


class UpdateMeBody(BaseModel):
    display_name: str


@app.patch("/api/me")
def update_me(
    body: UpdateMeBody,
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    name = body.display_name.strip()
    if not name:
        raise HTTPException(400, "имя не может быть пустым")
    student.display_name = name
    db.flush()
    cred = db.scalar(
        select(AccountCredential).where(AccountCredential.student_id == student.id)
    )
    return _me_json(student, cred)


@app.post("/api/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    data = await file.read()
    content_type = file.content_type or "application/octet-stream"
    try:
        photos_mod.validate_upload(content_type, len(data))
    except photos_mod.UploadRejected as exc:
        raise HTTPException(400, str(exc))

    old_path = student.avatar_storage_path
    storage_path = photos_mod.new_storage_path(student.id, file.filename or "avatar")
    photos_mod.save_bytes(storage_path, data)
    student.avatar_storage_path = storage_path
    student.avatar_content_type = content_type
    db.flush()
    if old_path:
        photos_mod.delete_file(old_path)

    cred = db.scalar(
        select(AccountCredential).where(AccountCredential.student_id == student.id)
    )
    return _me_json(student, cred)


@app.get("/api/me/avatar")
def get_my_avatar(student: Student = Depends(get_current_student)):
    if not student.avatar_storage_path:
        raise HTTPException(404, "аватар не установлен")
    full_path = photos_mod.UPLOADS_DIR / student.avatar_storage_path
    if not full_path.exists():
        raise HTTPException(404, "файл потерян на диске")
    # no-store — иначе браузер может продолжить показывать старую аватарку
    # с того же /api/me/avatar после замены (URL не меняется).
    return FileResponse(
        full_path, media_type=student.avatar_content_type or "image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/api/me/avatar")
def delete_my_avatar(
    student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)
):
    if student.avatar_storage_path:
        photos_mod.delete_file(student.avatar_storage_path)
        student.avatar_storage_path = None
        student.avatar_content_type = None
        db.flush()
    cred = db.scalar(
        select(AccountCredential).where(AccountCredential.student_id == student.id)
    )
    return _me_json(student, cred)


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/me/password")
def change_password(
    body: ChangePasswordBody,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    if len(body.new_password) < 8:
        raise HTTPException(400, "новый пароль слишком короткий (минимум 8 символов)")
    try:
        auth.change_password(student, body.current_password, body.new_password)
    except InvalidCredentials:
        raise HTTPException(401, "текущий пароль неверный")
    return {"ok": True}


# ---- привязка источников ---------------------------------------------------


@app.get("/api/sources/status")
def sources_status(
    student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)
):
    """Статус привязки по каждому источнику — читаем прямо из БД, не логинимся
    заново только чтобы проверить статус (лишний логин — лишний шанс на
    капчу, см. docs/sources.md). ``connected`` — есть привязка и автомат не
    разомкнут (не значит, что кука прямо сейчас жива, только что источник не
    требует ручного входа).

    ``session_cached``/``last_verified_at`` — честный, но не «живой» сигнал:
    это не проверка прямо сейчас (та же причина — не логинимся лишний раз),
    а факт из БД: есть ли вообще сохранённая сессия и когда её ПОСЛЕДНИЙ РАЗ
    реально подтвердили (переиспользованием кук или свежим логином, см.
    ``AuthService.get_sush_client``/``get_edupage_client``). Если давно —
    кука вполне может быть уже мертва, мы просто ещё не сходили и не
    узнали это; следующий реальный запрос сам перелогинится, если нужно."""

    def one(source: Source) -> dict:
        cred = db.scalar(
            select(SourceCredential).where(
                SourceCredential.student_id == student.id, SourceCredential.source == source
            )
        )
        row = db.scalar(
            select(SourceSession).where(
                SourceSession.student_id == student.id, SourceSession.source == source
            )
        )
        circuit_open = bool(row and row.circuit_open)
        return {
            "linked": cred is not None,
            "connected": cred is not None and not circuit_open,
            "circuit_open": circuit_open,
            "reason": row.circuit_reason if row else None,
            "school": cred.school if cred else None,
            "username": cred.username if cred else None,
            "session_cached": bool(row and row.encrypted_cookies),
            "last_verified_at": row.last_verified_at.isoformat() if row and row.last_verified_at else None,
        }

    return {"sush": one(Source.SUSH), "edupage": one(Source.EDUPAGE)}


class LinkSushBody(BaseModel):
    school: str
    iin: str
    password: str


@app.post("/auth/link/sush")
def link_sush(
    body: LinkSushBody,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    auth.save_credential(student, Source.SUSH, body.school, body.iin, body.password)
    try:
        auth.get_sush_client(student).close()
    except CircuitOpen as exc:
        return JSONResponse(
            {"linked": True, "session_ok": False, "reason": f"капча/2FA: {exc.reason}"},
            status_code=200,
        )
    except SushAuthError as exc:
        raise HTTPException(400, f"неверный логин/пароль: {exc}")
    except VaultError:
        # не должно случиться сразу после save_credential (пароль только что
        # зашифрован текущим ключом) — но если случилось, честно об этом
        raise HTTPException(500, "не удалось прочитать только что сохранённые данные")
    return {"linked": True, "session_ok": True}


class LinkEdupageBody(BaseModel):
    # Необязателен — просьба пользователя 16 сентября 2026: настоящее
    # приложение EduPage не спрашивает школу отдельно, только логин/пароль
    # (см. AuthService.link_edupage_auto). Оставлен как явный ручной путь —
    # официально не задокументированный автовход может не сработать для
    # какой-то школы, тогда это резервный вариант.
    subdomain: Optional[str] = None
    username: str
    password: str


@app.post("/auth/link/edupage")
def link_edupage(
    body: LinkEdupageBody,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    if not body.subdomain:
        try:
            client = auth.link_edupage_auto(student, body.username, body.password)
        except EdupageCaptchaRequired as exc:
            raise HTTPException(
                400, f"EduPage потребовал капчу при автовходе — укажи поддомен школы вручную: {exc}"
            )
        except EdupageAuthError as exc:
            raise HTTPException(400, f"неверный логин/пароль: {exc}")
        except EdupageSourceError as exc:
            # Общий случай: сеть недоступна, не удалось определить школу по
            # редиректу, или нужна 2FA — сама причина уже в тексте exc,
            # отдельно про поддомен добавляем только как подсказку к действию.
            raise HTTPException(400, f"не получилось войти автоматически — попробуй указать поддомен вручную: {exc}")
        except VaultError:
            raise HTTPException(500, "не удалось прочитать только что сохранённые данные")
        return {"linked": True, "session_ok": True, "subdomain": client.subdomain}

    auth.save_credential(student, Source.EDUPAGE, body.subdomain, body.username, body.password)
    try:
        auth.get_edupage_client(student)
    except CircuitOpen as exc:
        return JSONResponse(
            {"linked": True, "session_ok": False, "reason": f"капча: {exc.reason}"},
            status_code=200,
        )
    except EdupageAuthError as exc:
        raise HTTPException(400, f"неверный логин/пароль: {exc}")
    except EdupageSourceError as exc:
        raise HTTPException(400, f"не получилось войти: {exc}")
    except VaultError:
        raise HTTPException(500, "не удалось прочитать только что сохранённые данные")
    return {"linked": True, "session_ok": True}


def _unlink(db: DbSession, student: Student, source: Source) -> None:
    db.execute(
        delete(SourceCredential).where(
            SourceCredential.student_id == student.id, SourceCredential.source == source
        )
    )
    db.execute(
        delete(SourceSession).where(
            SourceSession.student_id == student.id, SourceSession.source == source
        )
    )


@app.delete("/auth/link/sush")
def unlink_sush(student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)):
    _unlink(db, student, Source.SUSH)
    return {"unlinked": True}


@app.delete("/auth/link/edupage")
def unlink_edupage(
    student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)
):
    _unlink(db, student, Source.EDUPAGE)
    return {"unlinked": True}


# ---- реальные данные через переиспользованную сессию источника ------------


def _snapshot_key(school_year: Optional[str]) -> str:
    """Сырой параметр запроса, не GUID — см. GradeSnapshot.school_year_key."""
    return school_year if school_year else "__current__"


def _load_snapshot(
    db: DbSession, student_id: str, quarter: int, school_year: Optional[str]
) -> Optional[GradeSnapshot]:
    return (
        db.query(GradeSnapshot)
        .filter(
            GradeSnapshot.student_id == student_id,
            GradeSnapshot.school_year_key == _snapshot_key(school_year),
            GradeSnapshot.quarter == quarter,
        )
        .first()
    )


def _save_snapshot(
    db: DbSession, student_id: str, quarter: int, school_year: Optional[str], body: dict
) -> GradeSnapshot:
    snap = _load_snapshot(db, student_id, quarter, school_year)
    if snap is None:
        snap = GradeSnapshot(
            student_id=student_id,
            school_year_key=_snapshot_key(school_year),
            quarter=quarter,
        )
        db.add(snap)
    snap.data = json.dumps(body)
    snap.fetched_at = utcnow()
    db.commit()
    return snap


def _strip_topics(body: dict) -> dict:
    """Проекция снэпшота под ``detailed=false`` — тот же быстрый агрегат,
    что раньше отдавал ``client.subjects()`` без похода за темами."""
    return {
        **body,
        "subjects": [
            {**s, "evaluations": [{**ev, "topics": []} for ev in s["evaluations"]]}
            for s in body["subjects"]
        ],
    }


def _fetch_grades_live(
    auth: AuthService, student: Student, quarter: int, school_year: Optional[str]
) -> dict:
    """Полный живой поход в СУШ — всегда с темами (``subjects_detailed``),
    чтобы один поход закрывал и /api/grades, и последующие клики по
    предметам в /api/grades/subject из того же снэпшота, а не гонял СУШ
    заново на каждый клик.

    До двух попыток: живой случай 18.09.2026 — СУШ рвёт нашу фоновую
    сессию («Текущая сессия завершена по причине входа с другой рабочей
    станции») даже когда ученик точно не заходил сам, просто сессия
    протухла между restore_cookies()/has_session() (лёгкая проверка) и
    самим запросом. Раньше это было конечной 409-ошибкой — ученику
    приходилось жать «Обновить» второй раз руками. Один retry здесь
    безопасен и не противоречит правилу «не перебирать пароль при капче»
    (см. get_sush_client): капча/2FA — это CircuitOpen, отдельная ветка,
    сюда не попадает и не ретраится."""
    for attempt in (1, 2):
        try:
            client = auth.get_sush_client(student)
        except CircuitOpen as exc:
            raise HTTPException(409, f"нужен ручной вход в СУШ: {exc.reason}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except VaultError:
            # пароль сохранён под ключом, которого сейчас нет (например, ключ
            # сменился с прошлой привязки) — самим не восстановить, только
            # перепривязать источник заново
            raise HTTPException(409, "данные СУШ не читаются текущим ключом — привяжи заново")

        # SushClient держит curl_cffi-сессию (нативный libcurl-хендл, тяжелее
        # httpx) — не закрывать её значило копить их по одной на каждый запрос
        # и получить OOM на машине с 256MB (живой случай 16.09.2026).
        try:
            school_year_id = _resolve_school_year_id(client, school_year)
            try:
                subjects = client.subjects_detailed(school_year_id=school_year_id, quarter=quarter)
            except SushContractError:
                raise  # источник изменил форму ответа — это баг, не глотаем молча
            except SushSessionExpired as exc:
                if attempt == 1:
                    continue  # get_sush_client() увидит мёртвую сессию и перелогинится
                raise HTTPException(409, f"сессия СУШ истекла на середине запроса: {exc}")
            except SushNetworkError as exc:
                # Живой случай 18.09.2026: резидентный прокси иногда не успевает
                # за 30с — это сбой сети, а не «данных на эту четверть нет».
                # Раньше это ловилось общим SushSourceError и уходило в note
                # как честный пустой ответ — ученик видел сырой текст curl-
                # ошибки вместо пустого списка предметов. Явный 502 — фронт
                # покажет его как ошибку с возможностью повторить, не как
                # «Обновить» вместо пустой четверти.
                raise HTTPException(502, f"СУШ временно недоступен, попробуй обновить ещё раз: {exc}")
            except SushSourceError as exc:
                # «Нет утвержденной нагрузки на данную четверть!» и подобные бизнес-
                # ответы — честное «данных ещё нет», не ошибка сервера
                return {"subjects": [], "note": str(exc)}

            if subjects:
                return {"subjects": [_subject_json(s) for s in subjects], "note": None}
            return {"subjects": [_stub_subject_json(r) for r in _report_card_rows(client, school_year_id)], "note": None}
        finally:
            client.close()
    raise AssertionError("недостижимо")  # цикл всегда либо return, либо raise на attempt==2


@app.get("/api/grades")
def grades(
    quarter: int = 1,
    school_year: Optional[str] = None,
    detailed: bool = True,
    force: bool = False,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
    db: DbSession = Depends(get_db),
):
    """``quarter`` по умолчанию 1 — у СУШ нет признака «текущая четверть»
    (см. docstring SushClient.subjects), не гадаем по календарю.

    ``school_year`` — человекочитаемое имя или подстрока, например
    ``"2025-2026"``, **не GUID**. Id учебных лет — внутренние идентификаторы
    источника, не проверено (и не стоит полагаться), что они стабильны
    между сессиями или у разных учеников; узнаём их каждый раз заново у
    текущей живой сессии, а не берём откуда-то заранее сохранённое —
    ровно на этом уже споткнулись при живой проверке.

    ``detailed`` — проекция уже сохранённого снэпшота (см. GradeSnapshot),
    не признак похода в СУШ: темы внутри evaluations либо есть, либо нет в
    ответе, сам снэпшот всегда полный. ``detailed=false`` — быстрый ответ
    только с агрегатами (Score/Mark/веса), без тем.

    По умолчанию читаем последний сохранённый снэпшот без похода в СУШ
    вообще — быстрый путь, счёт на миллисекунды. Живой поход через
    резидентный прокси (10+ секунд, см. docs/sources.md) — только когда
    снэпшота ещё нет или явно передан ``force=true`` («Обновить» в
    интерфейсе)."""
    if not force:
        snap = _load_snapshot(db, student.id, quarter, school_year)
        if snap is not None:
            body = json.loads(snap.data)
            return {**(body if detailed else _strip_topics(body)), "fetched_at": snap.fetched_at.isoformat()}

    body = _fetch_grades_live(auth, student, quarter, school_year)
    snap = _save_snapshot(db, student.id, quarter, school_year, body)
    return {**(body if detailed else _strip_topics(body)), "fetched_at": snap.fetched_at.isoformat()}


def _report_card_rows(client: SushClient, school_year_id: Optional[str]) -> list:
    """Живой случай 16 сентября 2026: в начале четверти дневник
    (``/Jce/Diary/GetSubjects``) пуст — по предметам ещё нет НИ ОДНОЙ
    оценки, и раньше это выглядело как честное, но вводящее в заблуждение
    «Предметов не найдено», хотя все 11 предметов класса реально есть,
    просто пока без оценок. Табель (``report_card``) — отдельная подсистема
    СУШ, не завязанная на наличие оценок в дневнике: список предметов
    класса виден там всегда. Используем его только как fallback за именами,
    когда дневник честно пуст — сам табель не даёт разбивку по темам
    внутри СОР/СОЧ (только годовые/четвертные итоги), так что калькулятор
    и разбор по темам для таких предметов недоступны, пока учитель не
    откроет оценивание в дневнике."""
    try:
        return client.report_card(school_year_id=school_year_id)
    except SushSourceError:
        return []


def _stub_subject_json(row) -> dict:
    return {"journal_id": row.Id, "name": row.SubjectName, "score": 0.0, "mark": 0, "evaluations": []}


def _resolve_school_year_id(client: SushClient, school_year: Optional[str]) -> Optional[str]:
    """Человекочитаемое имя/подстрока года (например ``"2025-2026"``) → GUID
    у живой сессии. Общее для /api/grades и /api/grades/subject — не
    дублируем резолвинг."""
    if school_year is None:
        return None
    try:
        years = client.school_years()
    except SushSourceError as exc:
        raise HTTPException(502, f"не удалось получить список лет: {exc}")
    matches = [y for y in years if school_year in y.Name]
    if len(matches) != 1:
        available = ", ".join(y.Name for y in years)
        raise HTTPException(
            400,
            f"'{school_year}' не даёт ровно одно совпадение "
            f"({len(matches)}); есть: {available}",
        )
    return matches[0].Id


def _subject_json(s) -> dict:
    return {
        # JournalId меняется от вызова к вызову (см. докстринг
        # grades_subject) — только для отображения/отладки, НЕ ключ.
        "journal_id": s.JournalId,
        "name": s.Name,
        "score": s.Score,
        "mark": s.Mark,
        "evaluations": [
            {
                "kind": ev.ShortName,  # "СОР" | "СОЧ"
                "weight": ev.Percent,
                "earned": ev.earned,
                "possible": ev.possible,
                "topics": [
                    {"name": r.Name, "score": r.Score, "max_score": r.MaxScore}
                    for r in ev.results
                ],
            }
            for ev in s.Evaluations
        ],
    }


@app.get("/api/grades/subject")
def grades_subject(
    name: str,
    quarter: int = 1,
    school_year: Optional[str] = None,
    force: bool = False,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
    db: DbSession = Depends(get_db),
):
    """Разбивка по темам ОДНОГО предмета — то, что подгружается лениво при
    открытии карточки в интерфейсе (см. design_handoff_navigation/
    README.md, "Two-tier loading").

    Читает из того же снэпшота, что /api/grades (см. GradeSnapshot) — тот
    уже хранит темы по всем предметам разом, так что клик по предмету
    после первой загрузки списка ничего не качает из СУШ, просто достаёт
    один элемент из уже сохранённого JSON. Живой поход — только если
    снэпшота ещё нет вообще (открыли сразу по прямой ссылке на предмет,
    минуя список) или передан ``force=true``.

    Адресуемся по ``name`` (имени предмета), не по ``JournalId``/``Id`` —
    живой прогон 14 сентября показал, что оба это идентификаторы, которые
    СУШ выдаёт заново на каждый вызов ``subjects()`` (они завязаны на
    сессию внутреннего дневника, открываемую заново каждым запросом), а не
    стабильный ключ предмета. Имя предмета внутри одной четверти уникально
    (16 разных предметов) и не меняется между запросами — это и есть
    настоящий признак, «выбор по признаку, не по индексу», применённый ещё
    раз."""
    if not force:
        snap = _load_snapshot(db, student.id, quarter, school_year)
        if snap is not None:
            body = json.loads(snap.data)
            subject = next((s for s in body["subjects"] if s["name"] == name), None)
            if subject is not None:
                return subject
            raise HTTPException(404, f"предмет с name={name!r} не найден в этой четверти")

    body = _fetch_grades_live(auth, student, quarter, school_year)
    _save_snapshot(db, student.id, quarter, school_year, body)
    subject = next((s for s in body["subjects"] if s["name"] == name), None)
    if subject is None:
        raise HTTPException(404, f"предмет с name={name!r} не найден в этой четверти")
    return subject


@app.get("/api/schedule/today")
def schedule_today(
    date_: Optional[str] = Query(None, alias="date"),
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    """Несмотря на имя (осталось от первой версии), берёт расписание любого
    дня через ``?date=YYYY-MM-DD`` — по умолчанию сегодня. Нужен и
    сегодняшний, и завтрашний день (карточка «Расписание на завтра» на
    Главной), заводить второй почти идентичный эндпоинт не стали."""
    if date_ is not None:
        try:
            target = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(400, f"'{date_}' не похоже на дату (YYYY-MM-DD)")
    else:
        target = date.today()
    try:
        client = auth.get_edupage_client(student)
    except CircuitOpen as exc:
        raise HTTPException(409, f"нужен ручной вход в EduPage: {exc.reason}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except VaultError:
        raise HTTPException(409, "данные EduPage не читаются текущим ключом — привяжи заново")
    lessons = client.timetable(target)
    return [
        {
            "period": l.period,
            "start": l.start.strftime("%H:%M") if l.start else None,
            "end": l.end.strftime("%H:%M") if l.end else None,
            "subject": l.subject,
            "teachers": l.teachers, "classrooms": l.classrooms,
            "is_cancelled": l.is_cancelled,
        }
        for l in lessons
    ]


@app.get("/api/schedule/exams")
def schedule_exams(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    """СОР/СОЧ/БЖБ на диапазон дат ``[from, to]`` — бейдж «есть СОР» прямо
    в расписании дня, как в самом EduPage (просьба пользователя
    16 сентября 2026). Один вызов на весь видимый диапазон (неделя грида +
    выбранный день списка), а не по дню — ``calendar_events()`` сам по себе
    тяжёлый (тянет ``get_notification_history`` за 60 дней), плодить его на
    каждый из 11 дневных запросов Расписания нельзя."""
    try:
        from_date = date.fromisoformat(from_)
        to_date = date.fromisoformat(to)
    except ValueError:
        raise HTTPException(400, "даты должны быть в формате YYYY-MM-DD")
    try:
        client = auth.get_edupage_client(student)
    except CircuitOpen as exc:
        raise HTTPException(409, f"нужен ручной вход в EduPage: {exc.reason}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except VaultError:
        raise HTTPException(409, "данные EduPage не читаются текущим ключом — привяжи заново")
    events = [
        e
        for e in client.calendar_events(from_date)
        if e.kind == "assessment" and from_date <= e.event_date <= to_date
    ]
    return [
        {
            "event_date": e.event_date.isoformat(),
            "subject_name": e.subject_name,
            "badge": e.badge,
            "title": e.title,
        }
        for e in events
    ]


@app.get("/api/consultations")
def consultations(
    date_: Optional[str] = Query(None, alias="date"),
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    """Консультации на один день, отфильтрованные под класс ученика (см.
    EdupageClient.schedule_changes). Источник отдаёт консультацию одной
    свободной строкой (``title``), без отдельных полей предмет/учитель/
    кабинет — фронт показывает как есть, не пытается это разобрать."""
    if date_ is not None:
        try:
            target = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(400, f"'{date_}' не похоже на дату (YYYY-MM-DD)")
    else:
        target = date.today()
    try:
        client = auth.get_edupage_client(student)
    except CircuitOpen as exc:
        raise HTTPException(409, f"нужен ручной вход в EduPage: {exc.reason}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except VaultError:
        raise HTTPException(409, "данные EduPage не читаются текущим ключом — привяжи заново")
    try:
        changes = client.schedule_changes(target)
    except EdupageSourceError as exc:
        raise HTTPException(502, str(exc))
    items = [c for c in changes if c.kind == "consultation"]
    return [
        {
            "title": c.title,
            "period_from": c.period_from,
            "period_to": c.period_to,
            "time_from": c.time_from.strftime("%H:%M") if c.time_from else None,
            "time_to": c.time_to.strftime("%H:%M") if c.time_to else None,
        }
        for c in items
    ]


class CustomEntryBody(BaseModel):
    entry_date: str  # YYYY-MM-DD
    subject: str
    teacher: Optional[str] = None
    room: Optional[str] = None
    time_from: Optional[str] = None  # "HH:MM"
    time_to: Optional[str] = None
    period: Optional[int] = None


def _custom_entry_json(e: CustomScheduleEntry) -> dict:
    # Сырые поля, не готовая строка — фронт сам собирает из этого either
    # урок в сетке Расписания (когда есть period) либо строку в списке дня
    # (см. apps/web/src/pages/schedule/useScheduleData.ts), а не карточку
    # "Консультации на неделе": своя запись — часть расписания, не отдельная
    # лента, это и была явная просьба пользователя 15 сентября 2026.
    return {
        "id": e.id,
        "subject": e.subject,
        "teacher": e.teacher,
        "room": e.room,
        "period": e.period,
        "time_from": e.time_from,
        "time_to": e.time_to,
    }


@app.get("/api/custom-entries")
def list_custom_entries(
    date_: Optional[str] = Query(None, alias="date"),
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    """Свои записи на день — независимо от EduPage/СУШ (см. docstring
    CustomScheduleEntry): отдельный эндпоинт от /api/consultations, чтобы
    падение/отвязку источника не утягивало за собой то, что ученик завёл
    сам."""
    if date_ is not None:
        try:
            target = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(400, f"'{date_}' не похоже на дату (YYYY-MM-DD)")
    else:
        target = date.today()
    rows = db.scalars(
        select(CustomScheduleEntry)
        .where(
            CustomScheduleEntry.student_id == student.id,
            CustomScheduleEntry.entry_date == target,
        )
        .order_by(CustomScheduleEntry.created_at)
    ).all()
    return [_custom_entry_json(e) for e in rows]


@app.post("/api/custom-entries")
def create_custom_entry(
    body: CustomEntryBody,
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    try:
        entry_date = date.fromisoformat(body.entry_date)
    except ValueError:
        raise HTTPException(400, f"'{body.entry_date}' не похоже на дату (YYYY-MM-DD)")
    subject = body.subject.strip()
    if not subject:
        raise HTTPException(400, "укажи предмет")
    row = CustomScheduleEntry(
        id=str(uuid.uuid4()),
        student_id=student.id,
        entry_date=entry_date,
        subject=subject[:200],
        teacher=(body.teacher or "").strip()[:200] or None,
        room=(body.room or "").strip()[:100] or None,
        time_from=body.time_from or None,
        time_to=body.time_to or None,
        period=body.period,
    )
    db.add(row)
    db.flush()
    return _custom_entry_json(row)


@app.delete("/api/custom-entries/{entry_id}")
def delete_custom_entry(
    entry_id: str,
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    row = db.scalar(
        select(CustomScheduleEntry).where(
            CustomScheduleEntry.id == entry_id, CustomScheduleEntry.student_id == student.id
        )
    )
    if row is None:
        raise HTTPException(404, "запись не найдена")
    db.delete(row)
    return {"deleted": True}


@app.get("/api/events/upcoming")
def events_upcoming(
    limit: int = 5,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    """СОР/СОЧ/БЖБ/собрания на ближайшие 30 дней вперёд от сегодня, самые
    близкие первыми. Даты/подписи форматирует фронт — сервер отдаёт только
    честный ISO, не строит «через N дн.» сам (это чистая арифметика от даты,
    ей не место в контракте API, см. обсуждение секции «Ближайшие события»)."""
    try:
        client = auth.get_edupage_client(student)
    except CircuitOpen as exc:
        raise HTTPException(409, f"нужен ручной вход в EduPage: {exc.reason}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except VaultError:
        raise HTTPException(409, "данные EduPage не читаются текущим ключом — привяжи заново")
    today = date.today()
    events = [e for e in client.calendar_events(today) if e.event_date >= today][:limit]
    return [
        {
            "kind": e.kind,
            "badge": e.badge,
            "title": e.title,
            "event_date": e.event_date.isoformat(),
            "subject_name": e.subject_name,
        }
        for e in events
    ]


@app.get("/api/notifications")
def notifications(
    limit: int = 20,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
):
    """Единая лента уведомлений EduPage за последние 30 дней (календарные
    события + настоящие сообщения вместе, новые по публикации первыми) —
    то же самое, что ученик видит в самом EduPage под Notifications. См.
    докстринг NotificationItem в apps/api/sources/edupage.py про то, что
    сознательно не включено (групповой чат, внерасписанные занятия —
    те уже честно показаны на Расписании)."""
    try:
        client = auth.get_edupage_client(student)
    except CircuitOpen as exc:
        raise HTTPException(409, f"нужен ручной вход в EduPage: {exc.reason}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except VaultError:
        raise HTTPException(409, "данные EduPage не читаются текущим ключом — привяжи заново")
    since = date.today() - timedelta(days=30)
    items = client.notifications(since)[:limit]
    return [
        {
            "id": n.event_id,
            "kind": n.kind,
            "badge": n.badge,
            "title": n.title,
            "posted_at": n.posted_at.isoformat(),
            "event_date": n.event_date.isoformat() if n.event_date else None,
            "author": n.author,
            "subject_name": n.subject_name,
        }
        for n in items
    ]


# ---- NisAI ------------------------------------------------------------------


@app.get("/api/assistant/status")
def assistant_status():
    """Ключ подключат позже — фронт заранее знает, показывать чат или честное
    "ассистент пока не настроен", не дожидаясь первого проваленного запроса."""
    return {"configured": assistant_mod.is_configured()}


class AssistantChatBody(BaseModel):
    # Плоская история [{role, content}] без внутренностей tool use — см.
    # докстринг assistant.chat про то, почему цикл вызовов не сериализуется
    # обратно между ходами.
    history: list[dict] = []
    message: str


@app.post("/api/assistant/chat")
def assistant_chat(
    body: AssistantChatBody,
    student: Student = Depends(get_current_student),
    auth: AuthService = Depends(get_auth),
    db: DbSession = Depends(get_db),
):
    if not assistant_mod.is_configured():
        raise HTTPException(409, "AI-ассистент пока не настроен — ключ добавят позже")
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "пустое сообщение")
    if len(message) > 2000:
        raise HTTPException(400, "сообщение слишком длинное (максимум 2000 символов)")
    try:
        reply = assistant_mod.chat(body.history, message, auth=auth, student=student, db=db)
    except assistant_mod.AssistantError as exc:
        raise HTTPException(502, str(exc))
    return {"reply": reply}


# ---- фото («Файлы») ---------------------------------------------------------


def _photo_json(p: Photo) -> dict:
    return {
        "id": p.id,
        "filename": p.filename,
        "content_type": p.content_type,
        "size_bytes": p.size_bytes,
        "created_at": p.created_at.isoformat(),
        "url": f"/api/photos/{p.id}/file",
        "pos_x": p.pos_x,
        "pos_y": p.pos_y,
        "width": p.width,
    }


PHOTO_DEFAULT_WIDTH = 170.0
PHOTO_MIN_WIDTH = 80.0
PHOTO_MAX_WIDTH = 420.0


class PhotoPositionBody(BaseModel):
    # Все поля опциональны — перетаскивание шлёт только pos_x/pos_y,
    # изменение размера только width, кнопка "вернуть исходный размер"
    # тоже только width. Один и тот же эндпоинт на все три случая, вместо
    # трёх почти одинаковых.
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    width: Optional[float] = None


@app.get("/api/photos")
def list_photos(student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(Photo).where(Photo.student_id == student.id).order_by(Photo.created_at.desc())
    ).all()
    return [_photo_json(p) for p in rows]


@app.post("/api/photos")
async def upload_photo(
    file: UploadFile = File(...),
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    existing_count = len(db.scalars(select(Photo.id).where(Photo.student_id == student.id)).all())
    if existing_count >= photos_mod.MAX_PHOTOS_PER_STUDENT:
        raise HTTPException(409, f"достигнут лимит фото ({photos_mod.MAX_PHOTOS_PER_STUDENT})")

    data = await file.read()
    content_type = file.content_type or "application/octet-stream"
    try:
        photos_mod.validate_upload(content_type, len(data))
    except photos_mod.UploadRejected as exc:
        raise HTTPException(400, str(exc))

    storage_path = photos_mod.new_storage_path(student.id, file.filename or "photo")
    photos_mod.save_bytes(storage_path, data)

    row = Photo(
        id=str(uuid.uuid4()),
        student_id=student.id,
        filename=(file.filename or "photo")[:255],
        content_type=content_type,
        size_bytes=len(data),
        storage_path=storage_path,
        # Новое фото падает на «стол» в случайном месте, не строго по
        # центру — иначе все новые фото ложились бы друг на друга ровным
        # стопкам в одной точке.
        pos_x=random.uniform(15, 85),
        pos_y=random.uniform(15, 80),
    )
    db.add(row)
    db.flush()
    return _photo_json(row)


@app.patch("/api/photos/{photo_id}/position")
def update_photo_position(
    photo_id: str,
    body: PhotoPositionBody,
    student: Student = Depends(get_current_student),
    db: DbSession = Depends(get_db),
):
    row = db.scalar(
        select(Photo).where(Photo.id == photo_id, Photo.student_id == student.id)
    )
    if row is None:
        raise HTTPException(404, "фото не найдено")
    if body.pos_x is not None:
        row.pos_x = min(100.0, max(0.0, body.pos_x))
    if body.pos_y is not None:
        row.pos_y = min(100.0, max(0.0, body.pos_y))
    if body.width is not None:
        row.width = min(PHOTO_MAX_WIDTH, max(PHOTO_MIN_WIDTH, body.width))
    db.flush()
    return _photo_json(row)


@app.get("/api/photos/{photo_id}/file")
def get_photo_file(
    photo_id: str, student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)
):
    row = db.scalar(
        select(Photo).where(Photo.id == photo_id, Photo.student_id == student.id)
    )
    if row is None:
        # 404, не 403 — не подтверждаем чужому ученику даже сам факт
        # существования фото с этим id
        raise HTTPException(404, "фото не найдено")
    full_path = photos_mod.UPLOADS_DIR / row.storage_path
    if not full_path.exists():
        raise HTTPException(404, "файл потерян на диске")
    return FileResponse(full_path, media_type=row.content_type)


@app.delete("/api/photos/{photo_id}")
def delete_photo(
    photo_id: str, student: Student = Depends(get_current_student), db: DbSession = Depends(get_db)
):
    row = db.scalar(
        select(Photo).where(Photo.id == photo_id, Photo.student_id == student.id)
    )
    if row is None:
        raise HTTPException(404, "фото не найдено")
    photos_mod.delete_file(row.storage_path)
    db.delete(row)
    return {"deleted": True}

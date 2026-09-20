"""Хранилище: SQLAlchemy 2.0, SQLite.

Три уровня секретов, каждый со своим сроком жизни и назначением:

* **пароль ученика** (СУШ/EduPage) — шифруется Vault'ом с `aad=student.id`,
  меняется редко, нужен только чтобы получить сессионные куки заново;
* **сессионные куки источника** — тоже шифруются, живут часы-дни, дают
  переиспользовать вход без пароля (это и есть защита от капчи из плана —
  логинимся редко, а не при каждом запросе);
* **токен сессии нашего сайта** — НЕ шифруется, а хешируется (SHA-256) перед
  записью в БД, как обычный пароль: сама БД не должна быть достаточной для
  входа под чужим именем, если её утащат.

Модели домена (Subject/Grade/…) сюда не входят — это отдельный слой,
что кэшировать и когда инвалидировать, решим в Фазе 2 отдельно.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


def utcnow() -> datetime:
    """Naive UTC — намеренно, не half-мера.

    SQLite не знает про часовые пояса: SQLAlchemy для него хранит дату как
    текст и при чтении всегда отдаёт naive datetime, даже если колонка
    объявлена ``DateTime()`` и писали в неё aware-значение.
    Сравнение naive/aware после этого падает с TypeError. Раз БД честно
    не хранит таймзону — не притворяемся, что хранит: везде naive UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Source(str, enum.Enum):
    """Источник, к которому привязаны учётные данные/сессия."""

    SUSH = "sush"
    EDUPAGE = "edupage"


class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    display_name: Mapped[str] = mapped_column(String(200))
    # Аватарка — тот же диск-плюс-метаданные приём, что и Photo/photos.py:
    # путь относительно photos.UPLOADS_DIR, сами байты не в БД. NULL —
    # аватарки нет, фронт показывает инициалы (см. ui/dashboardParts.tsx).
    avatar_storage_path: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    avatar_content_type: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    credentials: Mapped[list["SourceCredential"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    source_sessions: Mapped[list["SourceSession"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    app_sessions: Mapped[list["AppSession"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class AccountCredential(Base):
    """Логин/пароль в АККАУНТ НАШЕГО САЙТА — отдельно от Student.display_name.

    Раньше регистрация была просто именем без пароля («костыльно», для
    проверки сессии). Реальный логин нужен, чтобы один и тот же ученик мог
    зайти с телефона и с компьютера и увидеть одни и те же данные — иначе
    каждое открытие сайта создавало бы нового Student (см. main.py::register
    до этого изменения). Отдельная таблица, а не новые колонки на Student —
    чтобы не трогать существующую схему и не терять уже привязанные
    источники у строк, созданных до этого поля.

    Пароль хранится ХЕШЕМ (bcrypt), не Vault-шифрованием — в отличие от
    паролей СУШ/EduPage, этот пароль никогда не должен расшифровываться
    обратно, только сравниваться при входе.
    """

    __tablename__ = "account_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    # Подтверждение почты — токен хранится ХЕШЕМ (sha256), как токен сессии
    # сайта (см. auth.py), не в открытом виде. sent_at — для кулдауна на
    # повторную отправку в main.py, не для чего-то другого.
    email_verified: Mapped[bool] = mapped_column(Boolean(), default=False)
    email_verify_token_hash: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    email_verify_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), default=None)
    email_verify_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), default=None)

    student: Mapped[Student] = relationship()


class SourceCredential(Base):
    """Пароль ученика от одного источника — зашифрован Vault'ом.

    Один ученик — не больше одной привязки на источник (school/username
    вместе с зашифрованным паролем; ИИН для СУШ хранится в username).
    """

    __tablename__ = "source_credentials"
    __table_args__ = (UniqueConstraint("student_id", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"))
    source: Mapped[Source] = mapped_column(Enum(Source))
    school: Mapped[str] = mapped_column(String(100))  # sms.{school} / {school}.edupage.org
    username: Mapped[str] = mapped_column(String(100))  # ИИН для СУШ, логин для EduPage
    encrypted_password: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), default=utcnow, onupdate=utcnow
    )

    student: Mapped[Student] = relationship(back_populates="credentials")


class SourceSession(Base):
    """Кэш сессионных кук источника — чтобы не логиниться на каждый запрос.

    ``circuit_open`` — сюда падает circuit breaker при капче/2FA (см. план):
    фоновая синхронизация останавливается для этого ученика+источника,
    в интерфейсе просьба войти вручную. Сбрасывается успешным логином.
    """

    __tablename__ = "source_sessions"
    __table_args__ = (UniqueConstraint("student_id", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"))
    source: Mapped[Source] = mapped_column(Enum(Source))
    encrypted_cookies: Mapped[bytes] = mapped_column(LargeBinary)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    circuit_open: Mapped[bool] = mapped_column(Boolean, default=False)
    circuit_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    student: Mapped[Student] = relationship(back_populates="source_sessions")


class AppSession(Base):
    """Сессия браузера на НАШЕМ сайте. Токен хешируется, не хранится в открытую —
    как пароль: утечка БД не должна означать вход под чужим именем."""

    __tablename__ = "app_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)

    student: Mapped[Student] = relationship(back_populates="app_sessions")

    @property
    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        return utcnow() < self.expires_at


class Photo(Base):
    """Метаданные загруженного фото — «Файлы» на фронте. Сами байты на
    диске (``storage_path``, см. apps/api/photos.py), в БД — только
    метаданные. Раздельно, а не BLOB в БД: фото заметно крупнее любых
    других данных проекта и растут неограниченно, а не как пароль/куки
    источника, которых всегда ровно одна запись на источник."""

    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column()
    storage_path: Mapped[str] = mapped_column(String(500))  # относительно UPLOADS_DIR
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    # Позиция на «столе» (см. Files.tsx) — проценты (0..100) от размера
    # холста, не пиксели: холст на разных экранах разной ширины, а
    # фотографии должны оставаться на тех же относительных местах.
    pos_x: Mapped[float] = mapped_column(default=50.0)
    pos_y: Mapped[float] = mapped_column(default=50.0)
    # Ширина карточки на столе, в пикселях (высота всегда следует из неё —
    # у картинки object-fit не задан, так что высота держит собственную
    # пропорцию сама, отдельно хранить её не нужно). 170 — тот же дефолт,
    # что был раньше зашит в CSS как фиксированная ширина .files-card.
    width: Mapped[float] = mapped_column(default=170.0)


class CustomScheduleEntry(Base):
    """Своя запись в Расписании — консультация/занятие, которого нет у
    EduPage/СУШ (кружок, репетитор, что угодно личное). Источник данных —
    сам ученик, не источник; живёт независимо от состояния сессии
    EduPage/СУШ и должна показываться, даже если оба отвязаны или сессия
    истекла (см. apps/api/main.py::/api/custom-entries — отдельный
    эндпоинт от /api/consultations ровно поэтому)."""

    __tablename__ = "custom_schedule_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"))
    entry_date: Mapped[date] = mapped_column(Date())
    subject: Mapped[str] = mapped_column(String(200))
    teacher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    room: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # "HH:MM" строкой, не Time — тот же формат, в котором время уже ходит
    # по JSON везде в проекте (см. Lesson.start/end в apps/web/src/types.ts),
    # не нужно отдельной сериализации туда-обратно.
    time_from: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    time_to: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    # Номер урока — необязательный: даёт своей записи слот в сетке
    # Расписания (см. apps/web/src/pages/schedule/useScheduleData.ts),
    # ровно как у настоящего урока. Без него запись видна только в
    # списочном виде дня, привязать её к колонке грида нечем.
    period: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    student: Mapped[Student] = relationship()

    student: Mapped[Student] = relationship()


class GradeSnapshot(Base):
    """Последний снятый с СУШ срез оценок одной четверти — отдаём его сразу
    вместо живого похода за резидентный прокси на КАЖДОЕ открытие страницы
    или клик по предмету (см. main.py::grades, grades_subject). Живой поход
    остаётся, но по явному ``force=true`` — снэпшот и есть быстрый путь по
    умолчанию, а обновление ученик запускает сам, когда готов подождать.

    ``school_year_key`` — сырой параметр ``school_year`` запроса (человеко-
    читаемое имя вроде "2025-2026") или ``"__current__"``, если не передан.
    Намеренно НЕ резолвим его в GUID года для ключа кэша: сам резолвинг —
    живой запрос к СУШ (``school_years()``), а весь смысл снэпшота в том,
    чтобы совсем не ходить в сеть на быстром пути.

    ``data`` — JSON тела ответа ``/api/grades`` целиком (``{"subjects":
    [...], "note": ...}``), уже с темами внутри evaluations: /api/grades и
    /api/grades/subject читают из одного и того же снэпшота, второй просто
    достаёт из него один предмет по имени."""

    __tablename__ = "grade_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    school_year_key: Mapped[str] = mapped_column(String(100))
    quarter: Mapped[int]
    data: Mapped[str] = mapped_column(Text())
    fetched_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    student: Mapped[Student] = relationship()

    __table_args__ = (
        UniqueConstraint("student_id", "school_year_key", "quarter", name="uq_grade_snapshot"),
    )


def make_engine(url: str = "sqlite:///./nis.db"):
    # timeout=30 — SQLite позволяет ровно одному писателю за раз; страница
    # вроде Расписания бьёт по API параллельно (неделя = 5 дней расписания
    # + 5 дней консультаций разом), и каждый такой запрос пишет в
    # SourceSession (см. auth.py::get_edupage_client) ДО собственного
    # медленного похода в EduPage — транзакция остаётся открытой (держит
    # write-lock) на всё это время. Дефолтный busy-timeout sqlite3 (5с)
    # реально словился на живом прогоне — "database is locked" вместо
    # честной последовательной очереди. 30с — не чинит корень (держать
    # незакоммиченную запись поперёк сетевого похода всё ещё не идеально),
    # но даёт достаточно запаса, чтобы параллельные запросы с одной
    # страницы просто дождались своей очереди, а не падали.
    connect_args = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    return engine


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_columns(
        engine, "photos",
        [("pos_x", "REAL NOT NULL DEFAULT 50"), ("pos_y", "REAL NOT NULL DEFAULT 50"), ("width", "REAL NOT NULL DEFAULT 170")],
    )
    _ensure_columns(engine, "custom_schedule_entries", [("period", "INTEGER")])
    _ensure_columns(
        engine, "students",
        [("avatar_storage_path", "VARCHAR(500)"), ("avatar_content_type", "VARCHAR(100)")],
    )
    _ensure_columns(
        engine, "account_credentials",
        [
            ("email_verified", "BOOLEAN NOT NULL DEFAULT 0"),
            ("email_verify_token_hash", "VARCHAR(64)"),
            ("email_verify_expires_at", "DATETIME"),
            ("email_verify_sent_at", "DATETIME"),
        ],
    )


def _ensure_columns(engine, table: str, columns: list[tuple[str, str]]) -> None:
    """Проект без Alembic (одна dev-БД) — create_all создаёт только
    отсутствующие ТАБЛИЦЫ, а колонки вроде ``photos.pos_x`` или
    ``custom_schedule_entries.period`` добавились в модели уже после того,
    как таблица могла быть создана. Досоздаём такие колонки вручную, если
    их ещё нет, вместо того чтобы требовать удалить nis.db и потерять
    данные. ``columns`` — [(имя, DDL-тип с опциональным DEFAULT), ...]."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    with engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        conn.commit()

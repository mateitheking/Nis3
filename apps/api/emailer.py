"""Транзакционные письма через Resend (https://resend.com) — REST API,
без отдельного SDK (проект уже держит ``httpx`` как зависимость).

``RESEND_API_KEY`` подключается позже — до этого ``is_configured()``
честно отвечает False, и вызывающий код (main.py::register) не падает,
просто не отправляет письмо (тот же приём, что у assistant.py с
OPENAI_API_KEY).

Важно: пока в Resend не подтверждён свой домен, письма с
``onboarding@resend.dev`` уходят только на почту, которой владеет сам
аккаунт Resend (ограничение песочницы, не наш код) — для реальной
рассылки ученикам нужен подтверждённый домен и ``RESEND_FROM``."""

from __future__ import annotations

import os

import httpx

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Nis3 <onboarding@resend.dev>"


class EmailSendError(RuntimeError):
    """Письмо не ушло — невалидный ключ, песочница Resend, сеть и т.п."""


def is_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def _from_address() -> str:
    return os.environ.get("RESEND_FROM", DEFAULT_FROM)


def send_verification_email(to_email: str, verify_url: str) -> None:
    if not is_configured():
        raise EmailSendError("RESEND_API_KEY не задан")

    html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2>Подтвердите почту в Nis3</h2>
      <p>Перейдите по ссылке ниже, чтобы подтвердить, что эта почта принадлежит вам:</p>
      <p>
        <a href="{verify_url}"
           style="display: inline-block; padding: 12px 20px; background: #d4af5a;
                  color: #0a0a0a; text-decoration: none; border-radius: 8px; font-weight: 700;">
          Подтвердить почту
        </a>
      </p>
      <p style="color: #888; font-size: 13px;">Ссылка действует 24 часа. Если вы не регистрировались в Nis3 — просто проигнорируйте это письмо.</p>
    </div>
    """
    try:
        resp = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            json={
                "from": _from_address(),
                "to": [to_email],
                "subject": "Подтвердите почту — Nis3",
                "html": html,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise EmailSendError(f"сеть недоступна: {exc}") from exc
    if resp.status_code >= 400:
        raise EmailSendError(f"Resend ответил {resp.status_code}: {resp.text[:300]}")

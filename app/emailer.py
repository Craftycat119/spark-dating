"""Отправка писем: коды подтверждения, уведомления о метчах, рассылки об обновлениях."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from .config import settings

log = logging.getLogger("spark.email")


def _layout(title: str, body_html: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#121110;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 12px">
<table width="480" cellpadding="0" cellspacing="0" style="background:#1d1b19;border-radius:28px;color:#f2ede6">
<tr><td style="padding:28px 32px 8px;font-size:22px;font-weight:bold;color:#ff5b1f;letter-spacing:-1px">{escape(settings.app_name)}</td></tr>
<tr><td style="padding:8px 32px 4px;font-size:18px;font-weight:bold">{escape(title)}</td></tr>
<tr><td style="padding:8px 32px 32px;font-size:15px;line-height:1.55;color:#b9b2aa">{body_html}</td></tr>
</table></td></tr></table></body></html>"""


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Отправляет письмо. Без SMTP-настроек (режим разработки) пишет письмо в лог."""
    if not settings.smtp_host:
        log.warning("SMTP не настроен — письмо не отправлено.\nКому: %s\nТема: %s\n%s", to, subject, text)
        print(f"\n=== ПИСЬМО для {to} ===\n{subject}\n{text}\n========================\n", flush=True)
        return settings.dev_mode

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if settings.smtp_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ssl.create_default_context(), timeout=20) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — письмо не должно ронять запрос
        log.exception("Не удалось отправить письмо на %s", to)
        return False


def send_code(to: str, code: str, purpose: str) -> bool:
    if purpose == "reset":
        title, intro = "Сброс пароля", "Код для сброса пароля:"
    else:
        title, intro = "Подтвердите почту", "Ваш код подтверждения:"
    ttl = settings.code_ttl_minutes
    text = f"{intro} {code}\nКод действует {ttl} минут. Если это были не вы — просто проигнорируйте письмо."
    html = _layout(
        title,
        f"{intro}<div style='font-size:34px;letter-spacing:10px;font-weight:bold;color:#fff;"
        f"padding:18px 0'>{code}</div>Код действует {ttl} минут. Если это были не вы — просто проигнорируйте письмо.",
    )
    return send_email(to, f"{settings.app_name}: {title.lower()} — {code}", text, html)


def send_match_email(to: str, other_name: str, common: list[str]) -> bool:
    together = f" Общее: {', '.join(common[:5])}." if common else ""
    text = f"Вы и {other_name} понравились друг другу.{together} Напишите первым: {settings.base_url}"
    html = _layout(
        "Взаимно!",
        f"Вы и <b>{escape(other_name)}</b> понравились друг другу.{escape(together)}<br><br>"
        f"<a href='{escape(settings.base_url)}' style='display:inline-block;background:#ff5b1f;color:#160b05;"
        f"padding:12px 22px;border-radius:12px;text-decoration:none'>Открыть чат</a>",
    )
    return send_email(to, f"{settings.app_name}: новый метч!", text, html)


def send_broadcast(to: str, subject: str, body: str) -> bool:
    html = _layout(subject, escape(body).replace("\n", "<br>"))
    footer = "\n\n—\nОтключить такие письма можно в настройках профиля."
    return send_email(to, subject, body + footer, html)

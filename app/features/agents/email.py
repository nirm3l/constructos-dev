from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from shared.settings import (
    MCP_EMAIL_ALLOWED_DOMAINS,
    MCP_EMAIL_ALLOWED_RECIPIENTS,
    MCP_EMAIL_FROM,
    MCP_EMAIL_SMTP_HOST,
    MCP_EMAIL_SMTP_PASSWORD,
    MCP_EMAIL_SMTP_PORT,
    MCP_EMAIL_SMTP_SSL,
    MCP_EMAIL_SMTP_STARTTLS,
    MCP_EMAIL_SMTP_USERNAME,
)


def _domain(addr: str) -> str:
    parts = (addr or "").rsplit("@", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip().lower()


def _assert_recipient_allowed(addr: str):
    addr_norm = (addr or "").strip().lower()
    if not addr_norm:
        raise RuntimeError("Invalid recipient email address")

    # If neither allowlist is configured, allow sending to any address.
    if not MCP_EMAIL_ALLOWED_RECIPIENTS and not MCP_EMAIL_ALLOWED_DOMAINS:
        return

    if addr_norm in MCP_EMAIL_ALLOWED_RECIPIENTS:
        return

    dom = _domain(addr_norm)
    if dom and dom in MCP_EMAIL_ALLOWED_DOMAINS:
        return

    raise RuntimeError("Recipient is outside email allowlist")


def send_email_smtp(
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not MCP_EMAIL_SMTP_HOST:
        raise RuntimeError("Email is not configured (MCP_EMAIL_SMTP_HOST is missing)")
    if not MCP_EMAIL_FROM:
        raise RuntimeError("Email is not configured (MCP_EMAIL_FROM is missing)")

    cc = cc or []
    bcc = bcc or []
    to = [a.strip() for a in (to or []) if a and a.strip()]
    cc = [a.strip() for a in (cc or []) if a and a.strip()]
    bcc = [a.strip() for a in (bcc or []) if a and a.strip()]

    if not to and not cc and not bcc:
        raise RuntimeError("At least one recipient is required")

    recipients = to + cc + bcc
    for addr in recipients:
        _assert_recipient_allowed(addr)

    msg = EmailMessage()
    msg["From"] = MCP_EMAIL_FROM
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = (subject or "").strip()

    if html:
        msg.add_alternative(body or "", subtype="html")
    else:
        msg.set_content(body or "")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "smtp_host": MCP_EMAIL_SMTP_HOST,
            "smtp_port": MCP_EMAIL_SMTP_PORT,
            "from": MCP_EMAIL_FROM,
            "to": to,
            "cc": cc,
            "bcc_count": len(bcc),
            "subject": msg["Subject"],
        }

    if MCP_EMAIL_SMTP_SSL:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(MCP_EMAIL_SMTP_HOST, MCP_EMAIL_SMTP_PORT, timeout=15)
    else:
        smtp = smtplib.SMTP(MCP_EMAIL_SMTP_HOST, MCP_EMAIL_SMTP_PORT, timeout=15)

    try:
        smtp.ehlo()
        if MCP_EMAIL_SMTP_STARTTLS and not MCP_EMAIL_SMTP_SSL:
            smtp.starttls()
            smtp.ehlo()

        if MCP_EMAIL_SMTP_USERNAME:
            smtp.login(MCP_EMAIL_SMTP_USERNAME, MCP_EMAIL_SMTP_PASSWORD or "")

        smtp.send_message(msg, from_addr=MCP_EMAIL_FROM, to_addrs=recipients)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

    return {
        "ok": True,
        "dry_run": False,
        "from": MCP_EMAIL_FROM,
        "to": to,
        "cc": cc,
        "bcc_count": len(bcc),
        "subject": msg["Subject"],
    }


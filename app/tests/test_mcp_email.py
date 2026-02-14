from __future__ import annotations


def test_send_email_dry_run_allows_any_recipient_when_no_allowlist(monkeypatch):
    from features.agents import email as email_module

    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_PORT", 587)
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_USERNAME", "")
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_PASSWORD", "")
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_STARTTLS", True)
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_SSL", False)
    monkeypatch.setattr(email_module, "MCP_EMAIL_FROM", "noreply@example.test")
    monkeypatch.setattr(email_module, "MCP_EMAIL_ALLOWED_RECIPIENTS", set())
    monkeypatch.setattr(email_module, "MCP_EMAIL_ALLOWED_DOMAINS", set())

    out = email_module.send_email_smtp(
        to=["user@anywhere.test"],
        subject="Hello",
        body="Body",
        dry_run=True,
    )
    assert out["ok"] is True
    assert out["dry_run"] is True


def test_send_email_respects_allowlist(monkeypatch):
    from features.agents import email as email_module

    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_PORT", 587)
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_USERNAME", "")
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_PASSWORD", "")
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_STARTTLS", True)
    monkeypatch.setattr(email_module, "MCP_EMAIL_SMTP_SSL", False)
    monkeypatch.setattr(email_module, "MCP_EMAIL_FROM", "noreply@example.test")
    monkeypatch.setattr(email_module, "MCP_EMAIL_ALLOWED_RECIPIENTS", {"allowed@x.test"})
    monkeypatch.setattr(email_module, "MCP_EMAIL_ALLOWED_DOMAINS", set())

    out = email_module.send_email_smtp(
        to=["allowed@x.test"],
        subject="Hello",
        body="Body",
        dry_run=True,
    )
    assert out["ok"] is True

    try:
        email_module.send_email_smtp(
            to=["blocked@x.test"],
            subject="Hello",
            body="Body",
            dry_run=True,
        )
        assert False, "expected allowlist rejection"
    except RuntimeError as exc:
        assert "allowlist" in str(exc).lower()


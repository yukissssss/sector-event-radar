from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional


def send_gmail_html(
    gmail_user: str,
    gmail_app_password: str,
    to_addrs: List[str],
    subject: str,
    html_body: str,
    plain_fallback: str = "",
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = ", ".join(to_addrs)

    if plain_fallback:
        msg.attach(MIMEText(plain_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_user, gmail_app_password)
        smtp.sendmail(gmail_user, to_addrs, msg.as_string())

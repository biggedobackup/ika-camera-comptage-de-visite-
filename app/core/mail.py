"""Envoi d'e-mails (SMTP). Sans SMTP_HOST hors production : le contenu est écrit dans les journaux."""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import settings

logger = logging.getLogger("app.mail")


def _construire_message(destinataire: str, sujet: str, texte: str, html: str | None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((settings.MAIL_FROM_NAME, settings.MAIL_FROM))
    message["To"] = destinataire
    message["Subject"] = sujet
    message["Message-ID"] = make_msgid(domain=settings.MAIL_FROM.rsplit("@", 1)[-1])
    message.set_content(texte)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _envoyer_smtp(message: EmailMessage) -> None:
    contexte = ssl.create_default_context()
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=contexte, timeout=15) as serveur:
            if settings.SMTP_USER:
                serveur.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            serveur.send_message(message)
        return
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as serveur:
        if settings.SMTP_TLS:
            serveur.starttls(context=contexte)
        if settings.SMTP_USER:
            serveur.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        serveur.send_message(message)


async def envoyer_email(destinataire: str, sujet: str, texte: str, html: str | None = None) -> bool:
    """Envoie un e-mail. Retourne True si envoyé (ou écrit dans les journaux en développement).

    - SMTP_HOST vide hors production : le contenu complet (liens compris) est écrit dans les journaux.
    - SMTP_HOST vide en production : rien n'est envoyé ni journalisé (contenu sensible), retourne False.
    - Erreur SMTP : journalisée sans le contenu, retourne False.
    """
    if not settings.SMTP_HOST:
        if settings.est_production:
            logger.error("SMTP non configuré : e-mail « %s » non envoyé à %s.", sujet, destinataire)
            return False
        logger.info(
            "E-MAIL (développement, non envoyé)\nÀ : %s\nSujet : %s\n\n%s", destinataire, sujet, texte
        )
        return True
    message = _construire_message(destinataire, sujet, texte, html)
    try:
        await asyncio.to_thread(_envoyer_smtp, message)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Échec d'envoi de l'e-mail « %s » à %s : %s", sujet, destinataire, exc.__class__.__name__)
        return False
    logger.info("E-mail « %s » envoyé à %s.", sujet, destinataire)
    return True

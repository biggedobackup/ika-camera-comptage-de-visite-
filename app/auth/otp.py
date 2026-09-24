"""Double authentification TOTP (pyotp) et QR code de configuration (PNG en data: URI)."""

import base64
import io

import pyotp
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.pil import PilImage

from app.core.config import settings

# Tolérance de décalage d'horloge : le code précédent et le suivant (± 30 s) sont acceptés.
FENETRE_VALIDITE = 1


def generer_secret() -> str:
    """Nouveau secret TOTP aléatoire (base32, 160 bits)."""
    return pyotp.random_base32(length=32)


def uri_provisionnement(secret: str, email: str) -> str:
    """URI otpauth:// à scanner par l'application d'authentification."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.APP_NAME)


def qr_code_data_uri(contenu: str) -> str:
    """QR code PNG encodé en data: URI (autorisé par la CSP : img-src 'self' data:)."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=2, image_factory=PilImage)
    qr.add_data(contenu)
    qr.make(fit=True)
    tampon = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(tampon, format="PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def formater_secret(secret: str) -> str:
    """Secret groupé par 4 caractères pour une saisie manuelle lisible."""
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


def verifier_code(secret: str, code: str) -> bool:
    """Vrai si le code TOTP est valide pour ce secret (fenêtre de ± 30 secondes)."""
    return pyotp.TOTP(secret).verify(code, valid_window=FENETRE_VALIDITE)

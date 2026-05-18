"""
encryption.py
=============

Gestione della chiave di cifratura e helper per encrypt/decrypt.

Usa **Fernet** (dalla libreria ``cryptography``):
- AES-128-CBC con padding PKCS7
- HMAC-SHA256 per autenticazione del ciphertext (previene tampering)
- IV casuale incluso in ogni token → encrypt dello stesso valore produce
  token diversi ad ogni chiamata (non deterministico — sicuro)

La chiave viene gestita tramite la classe centralizzata ``settings``.

IMPORTANTE: perdere la chiave significa perdere l'accesso a tutti i dati
cifrati nel database. Fare backup della chiave in un vault sicuro.
"""

from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings

_fernet_instance = None

def _get_fernet() -> Fernet:
    """
    Inizializza l'istanza Fernet on-demand.
    Accede a settings.ENCRYPTION_KEY solo quando viene effettivamente chiamato.
    """
    global _fernet_instance
    if _fernet_instance is None:
        # Recuperiamo la chiave dall'oggetto settings centralizzato
        key = settings.ENCRYPTION_KEY
        _fernet_instance = Fernet(key.encode())
    return _fernet_instance

# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def encrypt(value: str) -> str:
    """
    Cifra una stringa e restituisce il token Fernet come stringa.

    Parameters
    ----------
    value : str
        Valore in chiaro da cifrare.

    Returns
    -------
    str
        Token Fernet base64-urlsafe, includente IV e HMAC.
        Sicuro da salvare in un campo VARCHAR/TEXT del database.

    Raises
    ------
    TypeError
        Se ``value`` non è una stringa.
    """
    if not isinstance(value, str):
        raise TypeError(f"encrypt() richiede una stringa, ricevuto {type(value)}")
    
    fernet = _get_fernet()
    return fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """
    Decifra un token Fernet e restituisce il valore originale.

    Parameters
    ----------
    token : str
        Token Fernet prodotto da ``encrypt()``.

    Returns
    -------
    str
        Valore in chiaro originale.

    Raises
    ------
    ValueError
        Se il token è corrotto, manomesso, o cifrato con una chiave diversa.
    TypeError
        Se ``token`` non è una stringa.
    """
    if not isinstance(token, str):
        raise TypeError(f"decrypt() richiede una stringa, ricevuto {type(token)}")
    
    fernet = _get_fernet()
    try:
        return fernet.decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Impossibile decifrare il valore: token corrotto, manomesso, "
            "o cifrato con una chiave diversa dall'attuale ENCRYPTION_KEY."
        ) from exc
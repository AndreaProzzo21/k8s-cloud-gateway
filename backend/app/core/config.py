import os
import secrets
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger("k8s_gateway")

class Settings:
    def __init__(self):
        # --- SERVER ---
        self.PORT = int(os.getenv("GATEWAY_PORT", 8000))
        self.HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")

        # --- DATABASE ---
        _db_url = os.getenv("DATABASE_URL", "data/gateway.db")
        self.DATABASE_URL = f"sqlite:///{_db_url}" if "://" not in _db_url else _db_url

        # --- SECURITY ---
        self.ADMIN_MASTER_KEY = os.getenv("ADMIN_MASTER_KEY", "").strip()
        
        # JWT
        self.JWT_SECRET_ALGORITHM = os.getenv("JWT_SECRET_ALGORITHM", "HS256")
        self.JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "1"))
        
        _jwt_secret = os.getenv("JWT_SECRET_KEY", "").strip()
        if not _jwt_secret:
            logger.warning("⚠️ JWT_SECRET_KEY non trovata. Generazione chiave volatile...")
            _jwt_secret = secrets.token_hex(32)
        self.JWT_SECRET_KEY = _jwt_secret

        # ENCRYPTION (Inizializzata tramite metodo interno)
        self.ENCRYPTION_KEY = self._load_encryption_key()

    def _load_encryption_key(self) -> str:
        """Carica la chiave da ENV, da file o la genera."""
        env_key = os.getenv("ENCRYPTION_KEY", "").strip()
        if env_key:
            return env_key

        key_path = "data/.encryption_key"
        if os.path.exists(key_path):
            try:
                with open(key_path, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logger.error(f"Errore lettura file chiave: {e}")

        # Generazione automatica
        logger.warning(f"🔐 ENCRYPTION_KEY mancante. Generazione in {key_path}...")
        new_key = Fernet.generate_key().decode()
        try:
            os.makedirs("data", exist_ok=True)
            with open(key_path, "w") as f:
                f.write(new_key)
        except Exception as e:
            logger.error(f"Impossibile salvare la chiave su file: {e}")
        
        return new_key

    def get_allowed_origins(self) -> list[str]:
        origins = ["http://localhost", "http://localhost:80", "http://127.0.0.1"]
        extra = os.getenv("CORS_EXTRA_ORIGINS", "")
        if extra:
            origins.extend(o.strip() for o in extra.split(",") if o.strip())
        return origins

# Inizializzazione globale (QUESTA crea l'oggetto settings con tutti gli attributi)
settings = Settings()

# Fail-fast critico
if not settings.ADMIN_MASTER_KEY:
    raise RuntimeError(
        "\n" + "="*60 +
        "\nCRITICAL ERROR: ADMIN_MASTER_KEY is not set!\n"
        "Please provide it via environment variable.\n" +
        "="*60
    )
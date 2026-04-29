class K8sBaseException(Exception):
    """Eccezione base per il gateway."""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class K8sResourceNotFoundException(K8sBaseException):
    """Lanciata quando un namespace o una risorsa non esiste (404)."""
    pass

class K8sUnauthorisedException(K8sBaseException):
    """Lanciata quando i certificati/token non sono validi (401/403)."""
    pass

class K8sCommunicationException(K8sBaseException):
    """Lanciata per errori generici di rete o timeout."""
    pass
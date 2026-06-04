"""
k8s_factory.py
==============

Factory statica per la creazione di client Kubernetes autenticati e sicuri.

Responsabilità
--------------
- Costruire un ``kubernetes.client.ApiClient`` configurato per un dato cluster,
  completo di autenticazione Bearer Token e verifica TLS via CA Certificate.
- Gestire il ciclo di vita dei file CA Certificate su disco tramite una cache
  per-cluster, eliminando il leak di file temporanei che si accumulavano ad
  ogni request nella versione precedente.
- Applicare timeout e politiche di retry su urllib3 per evitare che richieste
  verso cluster offline blocchino i thread del gateway indefinitamente.

Sicurezza
---------
- **SSL obbligatorio**: se non viene fornito un CA Certificate valido, la
  connessione viene rifiutata con un'eccezione esplicita. Nessun fallback
  silenzioso a ``verify_ssl=False``.
- Il CA Certificate viene scritto su disco una sola volta per cluster e
  riusato da tutte le request successive (cache thread-safe con ``threading.Lock``).
- Il token K8s non viene mai loggato.
- I file cert vengono creati con permessi ``0o600`` (leggibili solo dal processo
  corrente) tramite ``os.open`` con flag espliciti.

Gestione timeout
----------------
Il timeout globale su ``socket.setdefaulttimeout`` è il meccanismo più affidabile
in ambienti Docker dove i pacchetti TCP SYN verso host spenti vengono droppati
silenziosamente (nessun RST -> urllib3 non riceve segnale di errore -> attesa
infinita senza il timeout sul socket sottostante).

I timeout urllib3 (``CONNECT_TIMEOUT``, ``READ_TIMEOUT``) vengono comunque
configurati come doppia difesa per i casi in cui la connessione si apre ma
i dati tardano ad arrivare.

Cache dei certificati
---------------------
Il CA Certificate di un cluster è statico per tutta la vita del cluster.
Scriverlo su disco ad ogni request causava:

1. Accumulo illimitato di file ``.crt`` in ``/tmp``.
2. I/O di scrittura inutile ad ogni richiesta.
3. Nessun cleanup: i file sopravvivevano al lifecycle della request.

La cache risolve tutto: ``cluster_id -> path_su_disco``. Il file viene creato
solo al primo accesso per quel cluster; le request successive trovano il path
in cache e lo riusano direttamente. Se il file viene eliminato dall'esterno
(es. pulizia di ``/tmp``), viene ricreato automaticamente alla request successiva.

Dipendenze esterne
------------------
- ``kubernetes`` >= 28.x
- ``urllib3`` >= 1.26 (inclusa come dipendenza transitiva di ``kubernetes``)
"""

import os
import socket
import threading

import urllib3
from kubernetes import client
from urllib3.util.retry import Retry
from urllib3.util.timeout import Timeout


# ---------------------------------------------------------------------------
# Timeout globale su socket Python
#
# Deve essere superiore a HARD_TIMEOUT nel router (10s) in modo che sia sempre
# asyncio.wait_for a scattare per primo, restituendo un 504 pulito al frontend.
# Il socket timeout è il fallback di ultimo livello per pacchetti droppati.
# ---------------------------------------------------------------------------
socket.setdefaulttimeout(15)


# ---------------------------------------------------------------------------
# Costanti di configurazione rete
# ---------------------------------------------------------------------------

# Secondi per stabilire la connessione TCP.
CONNECT_TIMEOUT: int = 5

# Secondi per ricevere dati dopo che la connessione è aperta.
READ_TIMEOUT: int = 15

# Nessun retry automatico: preferiamo fallire veloce con 504.
# Retry su write (POST/PATCH/DELETE) potrebbe causare operazioni duplicate.
MAX_RETRIES: int = 0

# Rilevante solo se MAX_RETRIES > 0.
RETRY_BACKOFF: float = 0.5

# Connessioni HTTP riusabili verso il cluster per istanza di ApiClient.
CONNECTION_POOL_SIZE: int = 10

# Directory dove vengono scritti i file cert. Sovrascrivibile nei test.
CERT_DIR: str = "/tmp"


class K8sClientFactory:
    """
    Factory statica per client Kubernetes.

    Espone un unico metodo pubblico: :meth:`get_apis`.
    Tutti gli altri metodi sono privati e di supporto interno.

    Thread safety
    -------------
    La cache dei certificati è protetta da ``threading.Lock``.
    ``get_apis`` può essere chiamato concorrentemente da più thread
    (come avviene con ``run_in_executor`` nel router) senza race condition.
    """

    # Cache: cluster_id -> path assoluto del file .crt su disco.
    # Variabile di classe condivisa tra tutte le chiamate statiche.
    _cert_cache: dict[str, str] = {}

    # Lock che protegge lettura + scrittura atomica sulla cache.
    _cert_cache_lock: threading.Lock = threading.Lock()

    @staticmethod
    def get_apis(
        cluster_host: str,
        k8s_token: str,
        ca_cert: str | None = None,
        cluster_id: str | None = None,
    ) -> dict:
        """
        Costruisce e restituisce i client Kubernetes pronti all'uso.

        Configura un singolo ``ApiClient`` condiviso tra tutti i client API
        (CoreV1, AppsV1, RbacV1, NetworkingV1) in modo che timeout,
        autenticazione e pool di connessioni siano uniformi per la request.

        Parameters
        ----------
        cluster_host : str
            URL dell'API Server K8s, es. ``"https://10.0.0.1:6443"``.
        k8s_token : str
            Service Account Token per l'autenticazione Bearer.
            Non viene mai loggato.
        ca_cert : str | None
            Contenuto PEM del CA Certificate del cluster (stringa completa,
            inclusi i delimitatori ``-----BEGIN CERTIFICATE-----``).
            Se ``None`` o non valido, viene sollevato ``ValueError`` —
            non esiste fallback a connessioni non verificate.
        cluster_id : str | None
            Identificativo del cluster. Usato come chiave della cert cache
            e nei messaggi di log.

        Returns
        -------
        dict
            Dizionario con chiavi:
            ``"core_v1"``, ``"apps_v1"``, ``"rbac_v1"``, ``"networking_v1"``
            mappate ai rispettivi client dell'SDK Kubernetes.

        Raises
        ------
        ValueError
            Se ``ca_cert`` è assente o non contiene un certificato PEM valido.
        OSError
            Se la scrittura del file cert su disco fallisce.
        """
        safe_id = K8sClientFactory._sanitize_cluster_id(cluster_id or "unknown")

        # --- Configurazione base ---
        configuration = client.Configuration()
        configuration.host = cluster_host
        configuration.api_key["authorization"] = k8s_token
        configuration.api_key_prefix["authorization"] = "Bearer"
        configuration.connection_pool_maxsize = CONNECTION_POOL_SIZE

        # --- TLS obbligatorio ---
        cert_path = K8sClientFactory._get_or_create_cert_file(
            ca_cert=ca_cert,
            cluster_id=safe_id,
        )
        configuration.verify_ssl = True
        configuration.ssl_ca_cert = cert_path

        # --- ApiClient e timeout ---
        api_client = client.ApiClient(configuration)
        K8sClientFactory._apply_network_policies(api_client)

        return {
            "core_v1":        client.CoreV1Api(api_client),
            "apps_v1":        client.AppsV1Api(api_client),
            "rbac_v1":        client.RbacAuthorizationV1Api(api_client),
            "networking_v1":  client.NetworkingV1Api(api_client),
            "storage_v1":     client.StorageV1Api(api_client),
            "authorization_v1": client.AuthorizationV1Api(api_client),
            "batch_v1": client.BatchV1Api(api_client),
            "autoscaling_v2": client.AutoscalingV2Api(api_client),
        }

    # ---------------------------------------------------------------------------
    # Cache dei certificati
    # ---------------------------------------------------------------------------

    @staticmethod
    def _sanitize_cluster_id(cluster_id: str) -> str:
        """
        Normalizza il cluster_id per uso sicuro come componente di nome file.

        Conserva solo caratteri alfanumerici, trattini e underscore.
        Previene path traversal (es. ``../../etc/passwd``) nel nome del file
        cert costruito da :meth:`_get_or_create_cert_file`.

        Parameters
        ----------
        cluster_id : str
            ID grezzo del cluster proveniente dal JWT.

        Returns
        -------
        str
            ID sanitizzato. Se il risultato sarebbe vuoto, restituisce ``"unknown"``.
        """
        sanitized = "".join(c for c in cluster_id if c.isalnum() or c in "-_")
        return sanitized if sanitized else "unknown"

    @staticmethod
    def _get_or_create_cert_file(ca_cert: str | None, cluster_id: str) -> str:
        """
        Restituisce il path del file CA Certificate per questo cluster.

        Algoritmo:

        1. Valida che ``ca_cert`` sia un PEM valido (solleva ``ValueError`` altrimenti).
        2. Acquisisce il lock sulla cache.
        3. Se ``cluster_id`` è in cache **e** il file esiste su disco → restituisce
           il path cached senza alcuna I/O di scrittura.
        4. Altrimenti scrive il cert su disco con permessi ``0o600`` e aggiorna
           la cache.

        L'intera operazione check + write è atomica rispetto ad altri thread
        grazie al ``_cert_cache_lock``, prevenendo race condition su primo accesso
        concorrente per lo stesso cluster.

        Parameters
        ----------
        ca_cert : str | None
            Contenuto PEM del certificato.
        cluster_id : str
            ID del cluster già sanitizzato, usato come parte del nome file.

        Returns
        -------
        str
            Path assoluto del file ``.crt`` su disco.

        Raises
        ------
        ValueError
            Se ``ca_cert`` è None o non contiene un header PEM valido.
        OSError
            Se la scrittura su disco fallisce.
        """
        if not ca_cert or "-----BEGIN CERTIFICATE-----" not in ca_cert:
            raise ValueError(
                f"CA Certificate mancante o non valido per il cluster '{cluster_id}'. "
                "Connessioni TLS non verificate non sono permesse. "
                "Caricare un CA Certificate PEM valido tramite l'API di registrazione cluster."
            )

        cert_path = os.path.join(CERT_DIR, f"k8s_ca_{cluster_id}.crt")

        with K8sClientFactory._cert_cache_lock:
            cached_path = K8sClientFactory._cert_cache.get(cluster_id)

            # Cache hit: file ancora presente su disco → riusa senza I/O
            if cached_path and os.path.exists(cached_path):
                return cached_path

            # Cache miss o file eliminato dall'esterno → (ri)crea
            K8sClientFactory._write_cert_file(cert_path, ca_cert, cluster_id)
            K8sClientFactory._cert_cache[cluster_id] = cert_path
            return cert_path

    @staticmethod
    def _write_cert_file(path: str, ca_cert: str, cluster_id: str) -> None:
        """
        Scrive il CA Certificate su disco con permessi restrittivi (``0o600``).

        Usa ``os.open`` con flag espliciti invece di ``open()`` per impostare
        i permessi Unix al momento della creazione del file, eliminando la
        finestra di vulnerabilità tra creazione e ``chmod`` che si avrebbe
        con il metodo standard.

        In caso di errore di scrittura, il file parzialmente scritto viene
        rimosso per evitare che un cert corrotto venga messo in cache.

        Parameters
        ----------
        path : str
            Path assoluto dove scrivere il file.
        ca_cert : str
            Contenuto PEM del certificato.
        cluster_id : str
            Usato solo per i messaggi di log e nelle eccezioni.

        Raises
        ------
        OSError
            Se la creazione o scrittura del file fallisce.
        """
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(ca_cert)
            print(f"[K8sClientFactory] CA cert scritto per cluster '{cluster_id}': {path}")
        except OSError as exc:
            # Rimuove il file parziale per non lasciare un cert corrotto su disco.
            try:
                os.remove(path)
            except OSError:
                pass
            raise OSError(
                f"Impossibile scrivere il CA cert per '{cluster_id}' in {path}: {exc}"
            ) from exc

    @staticmethod
    def invalidate_cert_cache(cluster_id: str | None = None) -> None:
        """
        Invalida la cache dei certificati per forzarne la riscrittura.

        Da chiamare quando il CA Certificate di un cluster viene aggiornato
        tramite l'API di gestione del gateway. Senza questa chiamata, il vecchio
        cert rimarrebbe in cache fino al riavvio del container.

        Parameters
        ----------
        cluster_id : str | None
            Se fornito, invalida solo il cluster specificato e rimuove il suo
            file da disco.
            Se ``None``, invalida l'intera cache e rimuove tutti i file cert.

        Examples
        --------
        Invalidazione singola (dopo aggiornamento cert di un cluster)::

            K8sClientFactory.invalidate_cert_cache("K3S-PROD")

        Invalidazione totale (es. in un endpoint di manutenzione)::

            K8sClientFactory.invalidate_cert_cache()
        """
        with K8sClientFactory._cert_cache_lock:
            if cluster_id is not None:
                safe_id = K8sClientFactory._sanitize_cluster_id(cluster_id)
                removed_path = K8sClientFactory._cert_cache.pop(safe_id, None)
                if removed_path:
                    try:
                        os.remove(removed_path)
                    except OSError:
                        pass
                    print(f"[K8sClientFactory] Cache invalidata per cluster '{safe_id}'")
            else:
                for path in K8sClientFactory._cert_cache.values():
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                K8sClientFactory._cert_cache.clear()
                print("[K8sClientFactory] Cache certificati svuotata completamente")

    # ---------------------------------------------------------------------------
    # Configurazione rete
    # ---------------------------------------------------------------------------

    @staticmethod
    def _apply_network_policies(api_client: client.ApiClient) -> None:
        """
        Inietta timeout e retry policy nel pool di connessioni urllib3.

        Lavora in sinergia con ``socket.setdefaulttimeout`` su tre livelli:

        1. ``socket.setdefaulttimeout(15)`` — TCP puro, prima di urllib3.
           Gestisce pacchetti droppati silenziosamente (host spento).
        2. ``Timeout(connect=5, read=15)`` — urllib3, livello HTTP.
           Gestisce connessioni aperte ma dati tardivi.
        3. ``asyncio.wait_for(timeout=10)`` nel router — livello applicativo.
           Scatta per primo (10s < 15s) e restituisce 504 pulito al frontend,
           liberando l'event loop mentre il thread sottostante si chiude da solo.

        ``MAX_RETRIES=0``: retry disabilitati. Su operazioni non-idempotenti
        (POST, PATCH, DELETE) un retry automatico potrebbe creare risorse
        duplicate o eseguire operazioni distruttive due volte.

        Parameters
        ----------
        api_client : kubernetes.client.ApiClient
            ApiClient già istanziato. Il pool urllib3 viene modificato in-place.
        """
        timeout = Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT)
        retry_policy = Retry(total=MAX_RETRIES, backoff_factor=RETRY_BACKOFF)

        api_client.rest_client.pool_manager.connection_pool_kw.update({
            "timeout": timeout,
            "retries": retry_policy,
        })
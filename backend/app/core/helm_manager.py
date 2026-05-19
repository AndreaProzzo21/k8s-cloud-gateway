"""
helm_manager.py
===============

Manager per operazioni Helm su cluster Kubernetes remoti.

Architettura
------------
Tutte le operazioni Helm vengono eseguite tramite il binario ``helm`` CLI
installato nel container del gateway. Ogni metodo pubblico costruisce i
parametri del comando, esegue ``helm`` come sottoprocesso asincrono tramite
``asyncio.create_subprocess_exec``, e restituisce un dizionario strutturato.

Perché subprocess e non una libreria Python
-------------------------------------------
Al momento della scrittura non esiste una libreria Python che wrappa Helm 3
con supporto completo e manutenzione attiva:

- ``pyhelm`` supporta solo Helm 2 (EOL dal novembre 2020).
- ``pyhelm3`` è un wrapper non ufficiale attorno a subprocess, con API
  instabile e nessuna garanzia di compatibilità con le versioni future di Helm.

L'approccio subprocess garantisce:
1. Compatibilità con tutte le versioni di Helm 3.x.
2. Accesso a tutte le funzionalità CLI (incluse quelle non ancora nelle SDK).
3. Lo stesso comportamento che avrebbe un operatore che usa ``helm`` da terminale.

Gestione timeout
----------------
Ogni operazione ha un timeout configurabile. I default riflettono la natura
delle operazioni:

- ``list``, ``status``, ``history``, ``search``: 30s (lettura, veloci)
- ``install/upgrade``, ``uninstall``: 120s (scrittura, attendono ready)
- ``repo add/update``: 60s (dipende dalla rete)
- ``install_from_zip``: 120s (+ tempo di estrazione locale)

Il timeout scatta su ``asyncio.wait_for`` e invia SIGKILL al processo figlio
tramite ``proc.kill()``.

Sicurezza
---------
- Il kubeconfig è un file temporaneo con permessi 0o600 (vedi ``helm_kubeconfig.py``).
- Il token K8s non viene mai loggato.
- Il cluster_id è sanitizzato prima dell'uso come componente di path.
- I file temporanei (valori YAML, chart ZIP estratti) vengono rimossi nel
  blocco ``finally`` di ogni metodo che li crea.
- Non vengono mai eseguiti comandi costruiti con interpolazione di stringhe
  non sanitizzate: tutti gli argomenti vengono passati come lista a
  ``create_subprocess_exec``, che non usa shell e non è vulnerabile a
  command injection.
"""

import asyncio
import io
import json
import os
import shutil
import tempfile
from typing import Any
from app.core.helm_package_utils import detect_and_unpack, find_chart_root



# ---------------------------------------------------------------------------
# Timeout di default per categoria di operazione (secondi)
# ---------------------------------------------------------------------------
TIMEOUT_READ: float = 30.0      # list, status, history, search
TIMEOUT_WRITE: float = 120.0    # install, upgrade, uninstall
TIMEOUT_REPO: float = 60.0      # repo add, repo update
TIMEOUT_WAIT: float = 300.0     # operazioni con --wait (opzionale)


class HelmManager:
    """
    Interfaccia Python per operazioni Helm su un cluster Kubernetes remoto.

    Ogni istanza è associata a un singolo cluster e a un kubeconfig temporaneo
    generato per la request corrente. Non deve essere condivisa tra request.

    Parameters
    ----------
    kubeconfig_path : str
        Path del kubeconfig temporaneo generato da ``temp_kubeconfig``.
        Il file deve esistere per tutta la durata dell'istanza.
    cluster_id : str
        Identificativo del cluster. Usato nei messaggi di log.

    Attributes
    ----------
    helm_available : bool
        True se il binario ``helm`` è presente nel PATH del container.
        Verificato una sola volta al momento dell'istanziazione.
    """

    # In __init__, aggiungi i path per-cluster
    def __init__(self, kubeconfig_path: str, cluster_id: str):
        self._kubeconfig = kubeconfig_path
        self._cluster_id = cluster_id
        self._helm_bin: str | None = shutil.which("helm")
        
        # Directory isolate per questo cluster
        # Ogni cluster ha il suo repositories.yaml e il suo cache indipendente
        base = f"/tmp/helm_repos/{cluster_id}"
        self._repo_config = f"{base}/repositories.yaml"
        self._repo_cache  = f"{base}/cache"
        os.makedirs(self._repo_cache, exist_ok=True)
        # Crea repositories.yaml vuoto se non esiste (helm lo richiede)
        if not os.path.exists(self._repo_config):
            os.makedirs(base, exist_ok=True)
            with open(self._repo_config, "w") as f:
                f.write("apiVersion: \"\"\ngenerated: \"0001-01-01T00:00:00Z\"\nrepositories: []\n")

    @property
    def helm_available(self) -> bool:
        """True se il binario helm è presente nel container."""
        return self._helm_bin is not None

    # ---------------------------------------------------------------------------
    # Metodo interno: esecuzione comandi
    # ---------------------------------------------------------------------------

    async def _run(
        self,
        *args: str,
        timeout: float = TIMEOUT_READ,
        parse_json: bool = False,
    ) -> dict[str, Any]:
        """
        Esegue un comando helm asincrono e restituisce il risultato strutturato.

        Costruisce il comando aggiungendo sempre ``--kubeconfig`` come primo
        argomento dopo ``helm``, in modo che tutte le operazioni puntino al
        cluster corretto. Il flag ``--output json`` viene aggiunto automaticamente
        quando ``parse_json=True``.

        Parameters
        ----------
        *args : str
            Argomenti del comando helm (es. ``"list"``, ``"-n"``, ``"default"``).
            Non devono includere ``--kubeconfig``: viene aggiunto automaticamente.
        timeout : float
            Secondi prima di inviare SIGKILL al processo helm.
        parse_json : bool
            Se True, aggiunge ``--output json`` al comando e tenta il parsing
            di stdout come JSON, aggiungendo il risultato al dizionario
            di ritorno sotto la chiave ``"data"``.

        Returns
        -------
        dict
            Dizionario con le chiavi:
            - ``"success"`` (bool): True se returncode == 0.
            - ``"returncode"`` (int): exit code del processo.
            - ``"stdout"`` (str): output standard (stripped).
            - ``"stderr"`` (str): output di errore (stripped).
            - ``"data"`` (list | dict | None): JSON parsato se ``parse_json=True``
              e il parsing ha avuto successo; None altrimenti.
            - ``"command"`` (str): rappresentazione leggibile del comando eseguito,
              senza il path del kubeconfig (sicurezza).

        Raises
        ------
        RuntimeError
            Se ``helm_available`` è False (controllo difensivo: la dependency
            dovrebbe aver già bloccato la request in questo caso).
        asyncio.TimeoutError
            Rilanciata dopo SIGKILL al processo, per gestione upstream.
        """
        if not self._helm_bin:
            raise RuntimeError("Binario helm non disponibile nel container.")

        cmd_args = list(args)

        if parse_json and "--output" not in cmd_args and "-o" not in cmd_args:
            cmd_args.extend(["--output", "json"])

        full_cmd = [
            self._helm_bin,
            "--kubeconfig",        self._kubeconfig,
            "--repository-config", self._repo_config,   # ← isolamento per cluster
            "--repository-cache",  self._repo_cache,    # ← isolamento per cluster
            *cmd_args,
        ]

        # Per i log: mostriamo il comando senza il path del kubeconfig
        # (che include cluster_id e path /tmp, ma non il token).
        readable_cmd = f"helm {' '.join(cmd_args)}"
        print(f"[HelmManager:{self._cluster_id}] Esecuzione: {readable_cmd}")

        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain pipes dopo kill
            print(f"[HelmManager:{self._cluster_id}] TIMEOUT: {readable_cmd}")
            raise

        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        success = proc.returncode == 0

        result: dict[str, Any] = {
            "success": success,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "data": None,
            "command": readable_cmd,
        }

        if parse_json and success and stdout:
            try:
                result["data"] = json.loads(stdout)
            except json.JSONDecodeError as exc:
                print(
                    f"[HelmManager:{self._cluster_id}] "
                    f"Parsing JSON fallito per '{readable_cmd}': {exc}"
                )

        if not success:
            print(
                f"[HelmManager:{self._cluster_id}] "
                f"Errore (rc={proc.returncode}): {stderr[:200]}"
            )

        return result

    # ---------------------------------------------------------------------------
    # Release: operazioni CRUD
    # ---------------------------------------------------------------------------

    async def list_releases(self, namespace: str | None = None) -> dict:
        """
        Elenca le release Helm in un namespace o in tutti i namespace.

        Parameters
        ----------
        namespace : str | None
            Se fornito, elenca solo le release nel namespace specificato.
            Se None, elenca le release in tutti i namespace (``--all-namespaces``).

        Returns
        -------
        dict
            Dizionario con ``"data"`` contenente la lista delle release,
            ognuna con: name, namespace, revision, updated, status, chart, app_version.
        """
        args = ["list"]
        if namespace:
            args.extend(["-n", namespace])
        else:
            args.append("--all-namespaces")
        result = await self._run(*args, parse_json=True, timeout=TIMEOUT_READ)
        # helm list --output json restituisce "null" invece di "[]" su namespace
        # vuoto in alcune versioni. Normalizziamo sempre a lista.
        if result["success"] and result["data"] is None:
            result["data"] = []
        return result

    async def install_or_upgrade(
        self,
        release_name: str,
        chart_ref: str,
        namespace: str = "default",
        values: dict | None = None,
        version: str | None = None,
        create_namespace: bool = False,
        atomic: bool = False,
        wait: bool = False,
        timeout_seconds: int = 300,
    ) -> dict:
        """
        Esegue ``helm upgrade --install`` (crea se non esiste, aggiorna se esiste).

        Parameters
        ----------
        release_name : str
            Nome della release Helm (es. ``"my-nginx"``).
        chart_ref : str
            Riferimento al chart: ``"repo/chart"`` (es. ``"bitnami/nginx"``),
            path locale, o URL OCI (``"oci://registry/chart"``).
        namespace : str
            Namespace di destinazione. Default: ``"default"``.
        values : dict | None
            Valori di override per il chart (equivalente a ``-f values.yaml``).
            Vengono scritti in un file temporaneo e passati con ``-f``.
        version : str | None
            Versione specifica del chart (es. ``"1.2.3"``). Se None usa la latest.
        create_namespace : bool
            Se True aggiunge ``--create-namespace``. Default: True.
        atomic : bool
            Se True aggiunge ``--atomic``: rollback automatico in caso di errore.
        wait : bool
            Se True aggiunge ``--wait``: attende che tutte le risorse siano Ready.
        timeout_seconds : int
            Timeout passato a ``--timeout`` (secondi). Usato solo se ``wait=True``.

        Returns
        -------
        dict
            Risultato del comando con stdout/stderr. In caso di successo,
            stdout contiene il summary della release in JSON.
        """
        args = ["upgrade", "--install", release_name, chart_ref, "-n", namespace]

        if create_namespace:
            args.append("--create-namespace")
        if version:
            args.extend(["--version", version])
        if atomic:
            args.append("--atomic")
        if wait:
            args.extend(["--wait", "--timeout", f"{timeout_seconds}s"])

        # I valori di override vengono scritti su un file temporaneo con 0o600.
        values_file: str | None = None
        if values:
            fd, values_file = tempfile.mkstemp(suffix=".yaml", prefix="helm_values_")
            try:
                import yaml
                with os.fdopen(fd, "w") as f:
                    yaml.dump(values, f, default_flow_style=False)
                os.chmod(values_file, 0o600)
            except OSError:
                try:
                    os.remove(values_file)
                except OSError:
                    pass
                raise
            args.extend(["-f", values_file])

        op_timeout = TIMEOUT_WAIT if (wait or atomic) else TIMEOUT_WRITE
        try:
            return await self._run(*args, timeout=op_timeout, parse_json=True)
        finally:
            if values_file:
                try:
                    os.remove(values_file)
                except OSError:
                    pass

    async def uninstall(
        self,
        release_name: str,
        namespace: str = "default",
        keep_history: bool = False,
    ) -> dict:
        """
        Rimuove una release Helm dal cluster.

        Parameters
        ----------
        release_name : str
            Nome della release da rimuovere.
        namespace : str
            Namespace della release.
        keep_history : bool
            Se True aggiunge ``--keep-history``: preserva la storia della
            release nel cluster per permettere ``rollback`` futuro.

        Returns
        -------
        dict
            Risultato con stdout del messaggio di conferma Helm.
        """
        args = ["uninstall", release_name, "-n", namespace]
        if keep_history:
            args.append("--keep-history")
        return await self._run(*args, timeout=TIMEOUT_WRITE)

    async def get_release_status(
        self,
        release_name: str,
        namespace: str = "default",
    ) -> dict:
        """
        Restituisce lo stato dettagliato di una release.

        Equivalente a ``helm status <release> -n <namespace> --output json``.
        Include: info, chart, config (valori applicati), manifest (YAML delle risorse).

        Returns
        -------
        dict
            Con ``"data"`` contenente il JSON completo dello status Helm.
        """
        return await self._run(
            "status", release_name, "-n", namespace,
            parse_json=True,
            timeout=TIMEOUT_READ,
        )

    async def get_release_history(
        self,
        release_name: str,
        namespace: str = "default",
        max_revisions: int = 10,
    ) -> dict:
        """
        Restituisce la storia delle revisioni di una release.

        Parameters
        ----------
        max_revisions : int
            Numero massimo di revisioni da restituire (``--max``). Default: 10.

        Returns
        -------
        dict
            Con ``"data"`` contenente la lista delle revisioni: revision,
            updated, status, chart, app_version, description.
        """
        return await self._run(
            "history", release_name,
            "-n", namespace,
            "--max", str(max_revisions),
            parse_json=True,
            timeout=TIMEOUT_READ,
        )

    async def rollback(
        self,
        release_name: str,
        revision: int,
        namespace: str = "default",
        wait: bool = False,
    ) -> dict:
        """
        Esegue il rollback di una release a una revisione precedente.

        Parameters
        ----------
        revision : int
            Numero di revisione target. Passare 0 per tornare alla revisione
            precedente (comportamento nativo di Helm).
        wait : bool
            Se True aggiunge ``--wait``.

        Returns
        -------
        dict
            Risultato con stdout del messaggio di conferma Helm.
        """
        args = ["rollback", release_name, str(revision), "-n", namespace]
        if wait:
            args.append("--wait")
        op_timeout = TIMEOUT_WAIT if wait else TIMEOUT_WRITE
        return await self._run(*args, timeout=op_timeout)

    async def get_release_values(
        self,
        release_name: str,
        namespace: str = "default",
        all_values: bool = False,
    ) -> dict:
        """
        Restituisce i valori applicati a una release.

        Parameters
        ----------
        all_values : bool
            Se True aggiunge ``--all``: restituisce tutti i valori inclusi
            quelli di default del chart, non solo gli override.

        Returns
        -------
        dict
            Con ``"data"`` contenente il dizionario dei valori in JSON.
        """
        args = ["get", "values", release_name, "-n", namespace]
        if all_values:
            args.append("--all")
        return await self._run(*args, parse_json=True, timeout=TIMEOUT_READ)

    # ---------------------------------------------------------------------------
    # Repository
    # ---------------------------------------------------------------------------

    async def repo_add(self, name: str, url: str, username: str = None, password: str = None) -> dict:
        """
        Aggiunge un repository Helm con supporto opzionale all'autenticazione.
        """
        args = ["repo", "add", name, url, "--force-update"]
        
        if username and password:
            # Aggiungiamo le credenziali al comando binario
            args.extend(["--username", username, "--password", password])
            # Nota: --pass-credentials permette di salvare la configurazione 
            # in modo che helm repo update possa riutilizzarle
            args.append("--pass-credentials")

        return await self._run(*args, timeout=TIMEOUT_REPO)

    async def repo_update(self, name: str = None) -> dict:
        """
        Aggiorna l'indice dei repository configurati.
        Se 'name' è fornito, aggiorna solo quel repository specifico.
        """
        args = ["repo", "update"]
        if name:
            args.append(name)
            
        return await self._run(*args, timeout=TIMEOUT_REPO)

    async def repo_list(self) -> dict:
        """
        Elenca i repository Helm configurati nel kubeconfig corrente.

        Returns
        -------
        dict
            Con ``"data"`` contenente la lista dei repo: name, url.
            Lista vuota se nessun repository è configurato.
        """
        result = await self._run("repo", "list", parse_json=True, timeout=TIMEOUT_READ)
        # `helm repo list` esce con rc=1 e stderr "no repositories configured"
        # quando non c'è nessun repo. Non è un errore applicativo: normalizziamo.
        if not result["success"] and "no repositories" in result.get("stderr", "").lower():
            result["success"] = True
            result["data"] = []
        return result

    async def search_repo(self, query: str, versions: bool = False) -> dict:
        """
        Cerca chart nei repository configurati.

        Parameters
        ----------
        query : str
            Termine di ricerca (es. ``"nginx"``, ``"bitnami/redis"``).
        versions : bool
            Se True aggiunge ``--versions``: mostra tutte le versioni disponibili.

        Returns
        -------
        dict
            Con ``"data"`` contenente la lista dei chart trovati:
            name, chart_version, app_version, description.
        """
        args = ["search", "repo", query]
        if versions:
            args.append("--versions")
        return await self._run(*args, parse_json=True, timeout=TIMEOUT_READ)

    async def repo_remove(self, name: str) -> dict:
        """
        Rimuove un repository Helm per nome.
    
        Equivalente a ``helm repo remove <name>``.
        Helm restituisce rc=1 se il repository non esiste — normalizzato
        in HTTP 404 dal router tramite _require_success.
    
        Parameters
        ----------
        name : str
            Nome locale del repository da rimuovere (es. ``"mosquitto"``).
    
        Returns
        -------
        dict
            Risultato standard con success/stdout/stderr.
        """
        return await self._run("repo", "remove", name, timeout=TIMEOUT_REPO)

    async def show_chart_values(self, chart_ref: str, version: str | None = None) -> dict:
        """
        Mostra i valori di default di un chart (equivale a ``helm show values``).

        Utile per il frontend: permette di mostrare i parametri configurabili
        prima di eseguire un install.

        Parameters
        ----------
        chart_ref : str
            Riferimento al chart (``"bitnami/nginx"``, path locale, OCI URL).
        version : str | None
            Versione specifica. Se None usa la latest.

        Returns
        -------
        dict
            Con ``"stdout"`` contenente il YAML dei valori di default.
            Non usa ``--output json`` perché ``helm show values`` restituisce YAML.
        """
        args = ["show", "values", chart_ref]
        if version:
            args.extend(["--version", version])
        return await self._run(*args, timeout=TIMEOUT_READ)

    # ---------------------------------------------------------------------------
    # Install from Package
    # ---------------------------------------------------------------------------
    async def install_from_package(
        self,
        archive_path: str,
        release_name: str,
        namespace: str = "default",
        values: dict | None = None,
        create_namespace: bool = False,
        atomic: bool = False,
        wait: bool = False,
    ) -> dict:
        """
        Installs a Helm chart from a local archive file (ZIP, TGZ, TAR.GZ, …).
    
        Accepts a path to an already-saved archive rather than raw bytes.
        The route handler is responsible for streaming the upload to disk
        and for cleaning up the temp file after this method returns.
    
        Parameters
        ----------
        archive_path : str
            Absolute path to the archive file on disk.
        release_name : str
            Helm release name.
        namespace : str
            Target Kubernetes namespace.
        values : dict | None
            Optional override values.
        create_namespace : bool
            Pass --create-namespace to helm if True.
        atomic : bool
            Pass --atomic (auto-rollback on failure) if True.
        wait : bool
            Pass --wait (block until resources are Ready) if True.
    
        Returns
        -------
        dict
            Result dict from ``install_or_upgrade``.
        """
        tmpdir = tempfile.mkdtemp(prefix=f"helm_pkg_{self._cluster_id}_")
    
        try:
            # Step 1 — unpack
            try:
                detect_and_unpack(archive_path, tmpdir)
            except ValueError as exc:
                return {
                    "success":    False,
                    "stdout":     "",
                    "stderr":     str(exc),
                    "command":    "install_from_package / unpack",
                    "returncode": 1,
                }
    
            # Step 2 — locate chart root
            chart_path = find_chart_root(tmpdir)
            if chart_path is None:
                return {
                    "success":    False,
                    "stdout":     "",
                    "stderr":     (
                        "Chart.yaml not found in the archive. "
                        "Make sure the archive contains a valid Helm chart."
                    ),
                    "command":    "install_from_package / find_chart",
                    "returncode": 1,
                }
    
            # Step 3 — install or upgrade
            return await self.install_or_upgrade(
                release_name=release_name,
                chart_ref=chart_path,
                namespace=namespace,
                values=values,
                create_namespace=create_namespace,
                atomic=atomic,
                wait=wait,
            )
    
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    
    async def lint(
        self,
        chart_ref: str | None = None,
        version: str | None = None,
        archive_path: str | None = None,
        strict: bool = False,
    ) -> dict:
        """
        Lints a Helm chart from a local archive file or a remote reference.
    
        Parameters
        ----------
        chart_ref : str | None
            Remote chart reference (e.g. "bitnami/nginx").
            Mutually exclusive with archive_path.
        version : str | None
            Chart version to pull. Only used when chart_ref is set.
        archive_path : str | None
            Path to a local archive file (ZIP, TGZ, …).
            The route handler streams the upload here before calling this method.
        strict : bool
            Pass --strict to helm lint (treats warnings as errors).
    
        Returns
        -------
        dict
            Standard _run result dict plus:
            - ``has_errors``   (bool)
            - ``has_warnings`` (bool)
        """
        tmpdir = tempfile.mkdtemp(prefix="helm_lint_")
    
        try:
            target_path: str | None = None
    
            if archive_path:
                # Local upload: unpack into sandbox, find chart root
                try:
                    detect_and_unpack(archive_path, tmpdir)
                except ValueError as exc:
                    return {
                        "success":      False,
                        "stderr":       str(exc),
                        "has_errors":   True,
                        "has_warnings": False,
                    }
                target_path = find_chart_root(tmpdir)
    
            elif chart_ref:
                # Remote chart: pull first, then lint the extracted directory
                pull_cmd = ["pull", chart_ref, "--untar", "--untardir", tmpdir]
                if version:
                    pull_cmd.extend(["--version", version])
    
                pull_result = await self._run(*pull_cmd, timeout=30)
                if not pull_result.get("success"):
                    pull_result.setdefault("has_errors",   True)
                    pull_result.setdefault("has_warnings", False)
                    return pull_result
    
                target_path = find_chart_root(tmpdir)
    
            if target_path is None:
                return {
                    "success":      False,
                    "stderr":       "Chart.yaml not found. Ensure the archive contains a valid Helm chart.",
                    "has_errors":   True,
                    "has_warnings": False,
                }
    
            # Run helm lint
            args = ["lint", target_path]
            if strict:
                args.append("--strict")
    
            result = await self._run(*args, timeout=20, parse_json=False)
    
            stdout = result.get("stdout", "")
            result["has_errors"]   = "[ERROR]"   in stdout or not result.get("success")
            result["has_warnings"] = "[WARNING]" in stdout
            return result
    
        except Exception as exc:
            return {
                "success":      False,
                "stderr":       f"Lint internal error: {exc}",
                "has_errors":   True,
                "has_warnings": False,
            }
    
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
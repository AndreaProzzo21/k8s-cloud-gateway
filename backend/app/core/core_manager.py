from app.core.exceptions import (
    K8sResourceNotFoundException, 
    K8sUnauthorisedException, 
    K8sCommunicationException,
    K8sBaseException
)
from kubernetes.client.rest import ApiException
from kubernetes import utils
from kubernetes import client
from kubernetes import dynamic
from kubernetes.dynamic.exceptions import ResourceNotFoundError
from kubernetes.client import V1Namespace, V1ObjectMeta
import yaml
import tempfile
from datetime import datetime
import urllib3

class CoreManager:
    def __init__(self, k8s_apis: dict):
        """
        Riceve le API dalla Factory e inizializza l'api_client per le utility.
        """
        self.core_v1 = k8s_apis["core_v1"]
        self.apps_v1 = k8s_apis["apps_v1"]
        self.rbac_v1 = k8s_apis["rbac_v1"]
        self.networking_v1 = k8s_apis["networking_v1"]
        self.storage_v1 = k8s_apis["storage_v1"]
        self.auth_v1 = k8s_apis["authorization_v1"]
        self.batch_v1 = k8s_apis["batch_v1"]
        self.autoscaling_v2 = k8s_apis["autoscaling_v2"]
        self.api_client = self.core_v1.api_client


    def check_connectivity(self, **kwargs) -> dict:
        """
        Verifica la connettività al cluster con una chiamata che non richiede
        permessi RBAC specifici: /version è accessibile a qualsiasi SA autenticato.
        Restituisce il dettaglio della versione se raggiungibile.
        """
        try:
            # VersionApi non richiede nessun permesso RBAC — risponde a tutti
            # i token validi indipendentemente dal profilo o namespace.
            version_info = client.VersionApi(self.api_client).get_code(**kwargs)
            return {
                "status": "reachable",
                "server_version": f"{version_info.major}.{version_info.minor}"
            }
        except Exception as e:
            self._handle_exception(e, "Health Check")
    
    def get_permissions_summary(self, **kwargs) -> dict:
        try:
            # 1. Verifica se è Cluster Admin (Accesso ai Nodi)
            can_list_nodes = self.auth_v1.create_self_subject_access_review(
                body=client.V1SelfSubjectAccessReview(
                    spec=client.V1SelfSubjectAccessReviewSpec(
                        resource_attributes=client.V1ResourceAttributes(verb="list", resource="nodes")
                    )
                ), **kwargs
            ).status.allowed

            if can_list_nodes:
                return {
                    "profile": "admin",
                    "can_list_namespaces": True,
                    "allowed_namespaces": ["*"]
                }

            # 2. Se non è admin, verifichiamo se può almeno ELENCARE i namespace
            can_list_ns = self.auth_v1.create_self_subject_access_review(
                body=client.V1SelfSubjectAccessReview(
                    spec=client.V1SelfSubjectAccessReviewSpec(
                        resource_attributes=client.V1ResourceAttributes(verb="list", resource="namespaces")
                    )
                ), **kwargs
            ).status.allowed

            if can_list_ns:
                return {
                    "profile": "global_viewer",
                    "can_list_namespaces": True,
                    "allowed_namespaces": ["*"] # Può vederli tutti anche se non è admin
                }

            # 3. Se è restricted, proviamo a vedere se ha accesso al namespace 'default'
            # (O potremmo ritornare una lista vuota e forzare il manual input nel frontend)
            return {
                "profile": "restricted",
                "can_list_namespaces": False,
                "allowed_namespaces": [] 
            }

        except Exception as e:
            self._handle_exception(e, "Permission Summary")

# --- DELETE OPERATIONS ---

    def delete_pod(self, name: str, namespace: str):
        """Elimina un Pod specifico."""
        try:
            self.core_v1.delete_namespaced_pod(name=name, namespace=namespace)
            return {"status": "success", "message": f"Pod '{name}' eliminato correttamente."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Pod '{name}'")

    def delete_service(self, name: str, namespace: str):
        """Elimina un Service specifico."""
        try:
            self.core_v1.delete_namespaced_service(name=name, namespace=namespace)
            return {"status": "success", "message": f"Service '{name}' eliminato correttamente."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Service '{name}'")

    def delete_configmap(self, name: str, namespace: str):
        """Elimina una ConfigMap specifica."""
        try:
            self.core_v1.delete_namespaced_config_map(name=name, namespace=namespace)
            return {"status": "success", "message": f"ConfigMap '{name}' eliminata correttamente."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione ConfigMap '{name}'")

    def delete_secret(self, name: str, namespace: str):
        """Elimina un Secret specifico."""
        try:
            self.core_v1.delete_namespaced_secret(name=name, namespace=namespace)
            return {"status": "success", "message": f"Secret '{name}' eliminato correttamente."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Secret '{name}'")

    # --- NAMESPACES ---

    def create_namespace(self, name: str):
        """Crea un nuovo namespace nel cluster."""
        try:
            body = V1Namespace(metadata=V1ObjectMeta(name=name))
            # Eseguiamo la creazione
            self.core_v1.create_namespace(body=body)
            
            # RESTITUIAMO un dizionario semplice per evitare il RecursionError
            return {
                "status": "success",
                "message": f"Namespace '{name}' creato correttamente."
            }
        except Exception as e:
            self._handle_exception(e, f"Creazione Namespace '{name}'")

    def list_namespaces(self, **kwargs):
        try:
            ns_list = self.core_v1.list_namespace(**kwargs)
            return {
                "can_list": True,
                "items": [{"name": ns.metadata.name, "status": ns.status.phase, "creation_timestamp": ns.metadata.creation_timestamp.isoformat() if ns.metadata.creation_timestamp else None} for ns in ns_list.items]
            }
        except Exception as e:
            # Re-raise se è un problema di rete/timeout: non vogliamo mascherarlo
            if isinstance(e, (urllib3.exceptions.MaxRetryError,
                            urllib3.exceptions.ConnectTimeoutError,
                            urllib3.exceptions.ReadTimeoutError,
                            urllib3.exceptions.NewConnectionError)):
                self._handle_exception(e, "List Namespaces")
            # Solo per 403/401 restituiamo il fallback silenzioso
            return {"can_list": False, "items": []}
            
    def delete_namespace(self, name: str):
        """Elimina un namespace dal cluster."""
        try:
            # L'eliminazione in K8s è asincrona per default
            self.core_v1.delete_namespace(name=name)
            
            return {
                "status": "success",
                "message": f"Eliminazione del namespace '{name}' avviata."
            }
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Namespace '{name}'")

    # --- CONFIGMAPS, SECRETS, EVENTS ---
    def list_configmaps(self, namespace, label_selector=None):
        try:
            # Passiamo label_selector alla chiamata ufficiale K8s
            cms = self.core_v1.list_namespaced_config_map(namespace, label_selector=label_selector)
            return [{"name": cm.metadata.name, "keys": list(cm.data.keys()) if cm.data else [], "labels": cm.metadata.labels or {}} for cm in cms.items]
        except Exception as e:
            self._handle_exception(e, f"List ConfigMaps in {namespace}")

    def list_secrets(self, namespace, label_selector=None):
        try:
            secrets = self.core_v1.list_namespaced_secret(namespace, label_selector=label_selector)
            return [{"name": s.metadata.name, "type": s.type, "keys": list(s.data.keys()) if s.data else [], "labels": s.metadata.labels or {}} for s in secrets.items]
        except Exception as e:
            self._handle_exception(e, f"List Secrets in {namespace}")

    def list_events(self, namespace):
        try:
            events = self.core_v1.list_namespaced_event(namespace)
            min_date = datetime.min.replace(tzinfo=None)
            sorted_events = sorted(
                events.items, 
                key=lambda x: (x.last_timestamp.replace(tzinfo=None) if x.last_timestamp else min_date), 
                reverse=True
            )
            return [{
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "time": e.last_timestamp.strftime("%H:%M:%S") if e.last_timestamp else "Now"
            } for e in sorted_events]
        except Exception as e:
            self._handle_exception(e, f"List Events in {namespace}")

    # --- POD OPERATIONS ---

    def list_pods(self, namespace: str = None, label_selector: str = None, **kwargs):
        """
        Elenca i pod. Se namespace è None, elenca i pod di tutto il cluster (Cluster-wide).
        Supporta parametri extra come _request_timeout.
        """
        try:
            if namespace:
                # Caso standard: namespace specifico (User Console)
                pods = self.core_v1.list_namespaced_pod(
                    namespace=namespace, 
                    label_selector=label_selector,
                    **kwargs
                )
            else:
                # Caso Admin: Tutti i namespace del cluster (Admin Console)
                pods = self.core_v1.list_pod_for_all_namespaces(
                    label_selector=label_selector,
                    **kwargs
                )
                
            return [
                {
                    "name": p.metadata.name,
                    "namespace": p.metadata.namespace, # Aggiunto per chiarezza admin
                    "status": p.status.phase,
                    "pod_ip": p.status.pod_ip,
                    "node_name": p.spec.node_name,
                    "labels": p.metadata.labels
                } for p in pods.items
            ]
        except Exception as e:
            context = f"List Pods in '{namespace or 'All Namespaces'}'"
            self._handle_exception(e, context)


    def get_pod_by_name(self, name: str, namespace: str):
        try:
            pod = self.core_v1.read_namespaced_pod(name=name, namespace=namespace)
            
            # Estraiamo informazioni sui container
            containers = [{
                "name": c.name,
                "image": c.image,
                "ready": next((s.ready for s in (pod.status.container_statuses or []) if s.name == c.name), False),
                "restart_count": next((s.restart_count for s in (pod.status.container_statuses or []) if s.name == c.name), 0)
            } for c in pod.spec.containers]

            return {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "pod_ip": pod.status.pod_ip,
                "host_ip": pod.status.host_ip,
                "node_name": pod.spec.node_name,
                "start_time": pod.status.start_time,
                "labels": pod.metadata.labels or {},
                "annotations": pod.metadata.annotations or {},
                "containers": containers,
                "resource_version": pod.metadata.resource_version
            }
        except Exception as e:
            self._handle_exception(e, f"Dettaglio Pod '{name}'")

    def get_pod_logs(self, name: str, namespace: str, tail_lines: int = None):
        try:
            return self.core_v1.read_namespaced_pod_log(name=name, namespace=namespace, tail_lines=tail_lines)
        except Exception as e:
            self._handle_exception(e, f"Logs Pod '{name}'")

    # --- DEPLOYMENT OPERATIONS ---

    def list_deployments(self, namespace: str, label_selector: str = None):
        """Elenca i deployment con filtro opzionale per label."""
        try:
            deps = self.apps_v1.list_namespaced_deployment(
                namespace=namespace, 
                label_selector=label_selector
            )
            return [
                {
                    "name": d.metadata.name,
                    "replicas_desired": d.spec.replicas,
                    "replicas_ready": d.status.ready_replicas or 0,
                    "status": "Ready" if d.status.ready_replicas == d.spec.replicas else "Scaling",
                    "labels": d.metadata.labels
                } for d in deps.items
            ]
        except Exception as e:
            self._handle_exception(e, f"List Deployments in '{namespace}'")

    def get_deployment_by_name(self, name: str, namespace: str):
        try:
            dep = self.apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            
            # Estraiamo tutti i container definiti nel template
            containers = [{
                "name": c.name,
                "image": c.image,
                "ports": [p.container_port for p in c.ports] if c.ports else []
            } for c in dep.spec.template.spec.containers]

            return {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas_spec": dep.spec.replicas,
                "replicas_status": {
                    "total": dep.status.replicas or 0,
                    "available": dep.status.available_replicas or 0,
                    "ready": dep.status.ready_replicas or 0,
                    "updated": dep.status.updated_replicas or 0
                },
                "strategy": dep.spec.strategy.type,
                "containers": containers,
                "labels": dep.metadata.labels or {},
                "annotations": dep.metadata.annotations or {},
                "creation_timestamp": dep.metadata.creation_timestamp,
                "resource_version": dep.metadata.resource_version
            }
        except Exception as e:
            self._handle_exception(e, f"Deployment detail '{name}'")

    def scale_deployment(self, name: str, namespace: str, replicas: int):
        try:
            # Eseguiamo l'operazione sulla SDK
            self.apps_v1.patch_namespaced_deployment_scale(
                name=name, 
                namespace=namespace, 
                body={"spec": {"replicas": replicas}}
            )
            
            # RESTITUISCI UN DIZIONARIO SEMPLICE
            # Non restituire mai il risultato della chiamata SDK sopra
            return {
                "status": "success",
                "message": f"Deployment '{name}' scaled to {replicas} replicas",
                "name": name,
                "replicas": replicas
            }
        except Exception as e:
            self._handle_exception(e, f"Scaling Deployment '{name}'")

    def restart_deployment(self, namespace: str, name: str):
        try:
            import datetime
            # Prepariamo il patch per forzare il restart aggiungendo un'annotazione col timestamp
            now = datetime.datetime.utcnow().isoformat()
            body = {
                'spec': {
                    'template': {
                        'metadata': {
                            'annotations': {
                                'kubectl.kubernetes.io/restartedAt': now
                            }
                        }
                    }
                }
            }
            
            # Eseguiamo la patch
            self.apps_v1.patch_namespaced_deployment(name, namespace, body)
            
            # IMPORTANTE: Restituisci un dizionario semplice, NON l'oggetto 'res'
            return {"status": "success", "message": f"Deployment {name} restarted", "timestamp": now}
            
        except Exception as e:
            # Gestisci l'eccezione
            self._handle_exception(e, f"Restart Deployment '{name}'")

    def delete_deployment(self, name: str, namespace: str):
        """Elimina un deployment specifico."""
        try:
            # Eseguiamo la cancellazione
            self.apps_v1.delete_namespaced_deployment(
                name=name,
                namespace=namespace
            )
            # NON restituire la risposta della SDK di K8s.
            # Restituisci un dizionario semplice per evitare il RecursionError
            return {
                "status": "success",
                "message": f"Deployment '{name}' eliminato correttamente dal namespace '{namespace}'"
            }
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Deployment '{name}'")

    # --- SERVICE OPERATIONS ---


    def list_services_in_namespace(self, namespace: str, label_selector=None):
        try:
            svcs = self.core_v1.list_namespaced_service(namespace, label_selector=label_selector)
            return [{
                "name": s.metadata.name,
                "type": s.spec.type,
                "cluster_ip": s.spec.cluster_ip,
                "creation_timestamp": s.metadata.creation_timestamp,
                "labels": s.metadata.labels or {}
            } for s in svcs.items]
        except Exception as e:
            self._handle_exception(e, f"List Services in '{namespace}'")

    def get_service_by_name(self, name: str, namespace: str):
        try:
            svc = self.core_v1.read_namespaced_service(name=name, namespace=namespace)
            return {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "session_affinity": svc.spec.session_affinity,
                "selector": svc.spec.selector or {},
                "ports": [{"port": p.port, "target_port": p.target_port, "protocol": p.protocol, "name": p.name} for p in svc.spec.ports] if svc.spec.ports else [],
                "labels": svc.metadata.labels or {},
                "annotations": svc.metadata.annotations or {},
                "creation_timestamp": svc.metadata.creation_timestamp,
                "resource_version": svc.metadata.resource_version
            }
        except Exception as e:
            self._handle_exception(e, f"Dettaglio Service '{name}'")

    # --- RESOURCE QUOTA OPERATIONS ---

    def list_resource_quotas(self, namespace: str = None, **kwargs):
        """
        Elenca le ResourceQuotas. Se namespace è None, le elenca per tutto il cluster.
        Necessario per l'audit engine (regola namespace-quota-presence).
        """
        try:
            if namespace:
                quotas = self.core_v1.list_namespaced_resource_quota(namespace=namespace, **kwargs)
            else:
                quotas = self.core_v1.list_resource_quota_for_all_namespaces(**kwargs)
            
            return [
                {
                    "name": q.metadata.name,
                    "namespace": q.metadata.namespace,
                    "spec": q.spec.hard,
                    "status": q.status.used
                } for q in quotas.items
            ]
        except Exception as e:
            context = f"List Quotas in '{namespace or 'All Namespaces'}'"
            self._handle_exception(e, context)

    # --- AGGIORNAMENTO SERVICE OPERATIONS (Cluster-wide) ---

    def list_services(self, namespace: str = None, **kwargs):
        """
        Elenca i servizi. Se namespace è None, opera Cluster-wide.
        Necessario per l'audit engine (regola loadbalancer-limit).
        """
        try:
            if namespace:
                svcs = self.core_v1.list_namespaced_service(namespace=namespace, **kwargs)
            else:
                svcs = self.core_v1.list_service_for_all_namespaces(**kwargs)
            
            return [
                {
                    "name": s.metadata.name,
                    "namespace": s.metadata.namespace,
                    "type": s.spec.type,
                    "cluster_ip": s.spec.cluster_ip,
                    "external_ip": s.status.load_balancer.ingress[0].ip if s.status.load_balancer.ingress else None
                } for s in svcs.items
            ]
        except Exception as e:
            context = f"List Services in '{namespace or 'All Namespaces'}'"
            self._handle_exception(e, context)

    # --- AGGIORNAMENTO DEPLOYMENT OPERATIONS (Cluster-wide) ---

    def list_deployments_fleet(self, namespace: str = None, **kwargs):
        """
        Versione estesa di list_deployments che supporta la scansione cluster-wide.
        Necessario per l'audit engine (regola ha-workload-policy).
        """
        try:
            if namespace:
                deps = self.apps_v1.list_namespaced_deployment(namespace=namespace, **kwargs)
            else:
                deps = self.apps_v1.list_deployment_for_all_namespaces(**kwargs)
            
            return [
                {
                    "name": d.metadata.name,
                    "namespace": d.metadata.namespace,
                    "replicas": d.spec.replicas,
                    "ready_replicas": d.status.ready_replicas or 0,
                    "labels": d.metadata.labels
                } for d in deps.items
            ]
        except Exception as e:
            context = f"List Deployments in '{namespace or 'All Namespaces'}'"
            self._handle_exception(e, context)

    def list_ingresses_fleet(self, namespace: str = None, **kwargs):
        """
        Versione estesa di list_ingress che supporta la scansione cluster-wide.
        Necessario per l'audit engine (es. regola certificate-expiry o ingress-security).
        """
        try:
            if namespace:
                # Recupera ingress in un namespace specifico
                ingresses = self.networking_v1.list_namespaced_ingress(namespace=namespace, **kwargs)
            else:
                # Recupera ingress in tutto il cluster (cluster-wide)
                ingresses = self.networking_v1.list_ingress_for_all_namespaces(**kwargs)
            
            return [
                {
                    "name": i.metadata.name,
                    "namespace": i.metadata.namespace,
                    "class_name": i.spec.ingress_class_name,
                    # Estraiamo gli host configurati nelle regole
                    "hosts": [rule.host for rule in i.spec.rules if rule.host] if i.spec.rules else [],
                    # Estraiamo i segreti TLS per l'expiry observer
                    "tls_secrets": [t.secret_name for t in i.spec.tls if t.secret_name] if i.spec.tls else [],
                    "labels": i.metadata.labels,
                    "resource_version": i.metadata.resource_version
                } for i in ingresses.items
            ]
        except Exception as e:
            context = f"List Ingress in '{namespace or 'All Namespaces'}'"
            self._handle_exception(e, context)

    # --- UNIVERSAL APPLY ---

    def apply_universal_yaml(self, yaml_content):
        """
        Applica un manifesto YAML multi-risorsa in modo agnostico rispetto al namespace.
        """
        import yaml
        from kubernetes.utils import create_from_dict, FailToCreateError
        from app.core.exceptions import K8sBaseException # Assicurati che l'import sia corretto

        try:
            # Carichiamo tutti i documenti presenti nel file
            docs = list(yaml.safe_load_all(yaml_content))
            results = []
            
            for doc in docs:
                if not doc: continue
                
                # Rimosso il blocco che forzava doc["metadata"]["namespace"] = namespace
                # Ora leggiamo semplicemente cosa ha scritto l'utente (se presente)
                kind = doc.get("kind")
                metadata = doc.get("metadata", {})
                name = metadata.get("name", "unnamed")
                ns_in_doc = metadata.get("namespace") 

                try:
                    # TENTATIVO 1: Creazione
                    # Non passiamo 'namespace' come argomento alla funzione per evitare override.
                    # create_from_dict leggerà autonomamente metadata.namespace dal dizionario 'doc'.
                    create_from_dict(self.api_client, doc)
                    results.append(f"{kind} '{name}' creato correttamente (ns: {ns_in_doc or 'default/cluster-wide'}).")
                
                except FailToCreateError as f:
                    # FailToCreateError contiene una lista di eccezioni API
                    inner_exception = f.api_exceptions[0]
                    
                    # Verifichiamo se l'errore interno è un 409 (Conflict/Already Exists)
                    if hasattr(inner_exception, 'status') and inner_exception.status == 409:
                        try:
                            # TENTATIVO 2: Server-Side Apply (Aggiornamento)
                            self._apply_patch_fallback(doc)
                            results.append(f"{kind} '{name}' aggiornato (Server-Side Apply).")
                        except Exception as patch_err:
                            results.append(f"ERRORE su {kind} '{name}': {str(patch_err)}")
                    else:
                        # Se l'errore è un 403 (Forbidden), verrà riportato qui correttamente
                        results.append(f"ERRORE su {kind} '{name}': {str(inner_exception)}")

                except Exception as e:
                    results.append(f"ERRORE inaspettato su {kind} '{name}': {str(e)}")

            return {
                "status": "success",
                "message": "Processo completato",
                "details": results
            }

        except Exception as e:
            if not hasattr(e, 'status'):
                raise K8sBaseException(f"Errore formato YAML: {str(e)}", status_code=400)
            self._handle_exception(e, "Universal Apply")

    def _apply_patch_fallback(self, doc):
        """Helper per eseguire il Server-Side Apply leggendo il namespace dal documento."""
        from kubernetes import dynamic
        
        # Inizializziamo il client dinamico
        dynamic_client = dynamic.DynamicClient(self.api_client)
        
        # Identifichiamo la risorsa (es. v1 Pod, apps/v1 Deployment)
        resource = dynamic_client.resources.get(
            api_version=doc['apiVersion'], 
            kind=doc['kind']
        )
        
        # Estraiamo il namespace dal documento. 
        # Se la risorsa è Cluster-scoped (es. un Nodo), ns sarà None e il client lo gestirà correttamente.
        ns = doc.get('metadata', {}).get('namespace')
        
        # Eseguiamo il patch con il content_type corretto per Server-Side Apply
        return resource.patch(
            body=doc,
            name=doc['metadata']['name'],
            namespace=ns,  # <--- Dinamico: usa quello del file o None
            content_type='application/apply-patch+yaml',
            field_manager='k8s-cloud-gateway',
            force=True
        )

    # --- NODE OPERATIONS (CLUSTER ADMIN) ---

    def list_nodes(self, **kwargs):
        """
        Elenca i nodi del cluster con dettagli su risorse e versioni.
        Richiede permessi di Cluster Admin.
        """
        try:
            nodes = self.core_v1.list_node(**kwargs)
            node_list = []
            for node in nodes.items:
                # Estraiamo le info sulle risorse (Capacity vs Allocatable)
                capacity = node.status.capacity
                allocatable = node.status.allocatable
                
                node_list.append({
                    "name": node.metadata.name,
                    "status": node.status.conditions[-1].type if node.status.conditions else "Unknown",
                    "status_state": node.status.conditions[-1].status if node.status.conditions else "False",
                    "role": "Control Plane" if "node-role.kubernetes.io/control-plane" in node.metadata.labels else "Worker",
                    "version": node.status.node_info.kubelet_version,
                    "os": node.status.node_info.os_image,
                    "cpu": capacity.get("cpu"),
                    "memory": capacity.get("memory"),
                    "cpu_allocatable": allocatable.get("cpu"),
                    "mem_allocatable": allocatable.get("memory"),
                    "creation_timestamp": node.metadata.creation_timestamp
                })
            return node_list
        except Exception as e:
            self._handle_exception(e, "List Nodes")

    def list_service_accounts(self, namespace: str):
        try:
            res = self.core_v1.list_namespaced_service_account(namespace)
            return [{"name": sa.metadata.name, "secrets": len(sa.secrets or [])} for sa in res.items]
        except Exception as e:
            self._handle_exception(e, f"List ServiceAccounts in {namespace}")

    def delete_service_account(self, namespace: str, name: str):
        try:
            self.core_v1.delete_namespaced_service_account(name, namespace)
            return {"status": "success", "message": f"ServiceAccount {name} deleted"}
        except Exception as e:
            self._handle_exception(e, f"Delete ServiceAccount {name}")

    # --- ROLES ---
    def list_roles(self, namespace: str):
        try:
            res = self.rbac_v1.list_namespaced_role(namespace)
            return [{"name": r.metadata.name, "rules": len(r.rules or [])} for r in res.items]
        except Exception as e:
            self._handle_exception(e, f"List Roles in {namespace}")

    def delete_role(self, namespace: str, name: str):
        try:
            self.rbac_v1.delete_namespaced_role(name, namespace)
            return {"status": "success", "message": f"Role {name} deleted"}
        except Exception as e:
            self._handle_exception(e, f"Delete Role {name}")

    # --- ROLE BINDINGS ---
    def list_role_bindings(self, namespace: str):
        try:
            res = self.rbac_v1.list_namespaced_role_binding(namespace)
            return [
                {
                    "name": rb.metadata.name, 
                    "role_ref": rb.role_ref.name,
                    "subjects": [{"kind": s.kind, "name": s.name} for s in rb.subjects or []]
                } for rb in res.items
            ]
        except Exception as e:
            self._handle_exception(e, f"List RoleBindings in {namespace}")

    def delete_role_binding(self, namespace: str, name: str):
        try:
            self.rbac_v1.delete_namespaced_role_binding(name, namespace)
            return {"status": "success", "message": f"RoleBinding {name} deleted"}
        except Exception as e:
            self._handle_exception(e, f"Delete RoleBinding {name}")
        
        
    # --- INGRESS OPERATIONS ---

    def list_ingress(self, namespace: str, label_selector: str = None):
        try:
            # In Kubernetes networking_v1 gestisce gli Ingress
            ings = self.networking_v1.list_namespaced_ingress(namespace, label_selector=label_selector)
            return [{
                "name": i.metadata.name,
                "hosts": [rule.host for rule in i.spec.rules if rule.host] if i.spec.rules else [],
                "address": [lb.ip or lb.hostname for lb in i.status.load_balancer.ingress] if i.status.load_balancer.ingress else [],
                "labels": i.metadata.labels or {}, # Fondamentale per renderLabels()
                "creation_timestamp": i.metadata.creation_timestamp
            } for i in ings.items]
        except Exception as e:
            self._handle_exception(e, f"List Ingress in {namespace}")

    def delete_ingress(self, name: str, namespace: str):
        """Elimina un Ingress specifico."""
        try:
            self.networking_v1.delete_namespaced_ingress(name=name, namespace=namespace)
            return {
                "status": "success", 
                "message": f"Ingress '{name}' eliminato correttamente dal namespace '{namespace}'."
            }
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Ingress '{name}'")

# --- STORAGE ---

    def list_persistent_volumes(self):
        """Elenca i Persistent Volumes (PV) a livello di cluster."""
        try:
            pv_list = self.core_v1.list_persistent_volume()
            return [
                {
                    "name": pv.metadata.name,
                    "capacity": pv.spec.capacity.get("storage", "N/A"),
                    "access_modes": pv.spec.access_modes,
                    "reclaim_policy": pv.spec.persistent_volume_reclaim_policy,
                    "status": pv.status.phase,
                    "claim": f"{pv.spec.claim_ref.namespace}/{pv.spec.claim_ref.name}" if pv.spec.claim_ref else "None",
                    "storage_class": pv.spec.storage_class_name,
                    "creation_timestamp": pv.metadata.creation_timestamp.isoformat()
                } for pv in pv_list.items
            ]
        except Exception as e:
            self._handle_exception(e, "List Persistent Volumes")

    def list_namespaced_pvc(self, namespace: str):
        """Elenca i Persistent Volume Claims (PVC) in un namespace."""
        try:
            pvc_list = self.core_v1.list_namespaced_persistent_volume_claim(namespace=namespace)
            return [
                {
                    "name": pvc.metadata.name,
                    "status": pvc.status.phase,
                    "volume": pvc.spec.volume_name,
                    "capacity": pvc.status.capacity.get("storage", "N/A") if pvc.status.capacity else "N/A",
                    "storage_class": pvc.spec.storage_class_name,
                    "creation_timestamp": pvc.metadata.creation_timestamp.isoformat()
                } for pvc in pvc_list.items
            ]
        except Exception as e:
            self._handle_exception(e, f"List PVC in {namespace}")

    def delete_namespaced_pvc(self, name: str, namespace: str):
            """Elimina un Persistent Volume Claim (PVC) in un namespace specifico."""
            try:
                self.core_v1.delete_namespaced_persistent_volume_claim(
                    name=name,
                    namespace=namespace
                )
                return {
                    "status": "success",
                    "message": f"PVC '{name}' nel namespace '{namespace}' eliminato."
                }
            except Exception as e:
                self._handle_exception(e, f"Eliminazione PVC '{name}' in {namespace}")


# --- STORAGE CLASS (Cluster-wide) ---

    def list_storage_classes(self):
        try:
            sc_list = self.storage_v1.list_storage_class()
            return [{
                "name": sc.metadata.name,
                "provisioner": sc.provisioner,
                "reclaim_policy": sc.reclaim_policy,
                "volume_binding_mode": sc.volume_binding_mode,
                "age": sc.metadata.creation_timestamp.isoformat()
            } for sc in sc_list.items]
        except Exception as e:
            self._handle_exception(e, "List Storage Classes")

    # --- STATEFUL SETS (Namespaced) ---
    def list_namespaced_stateful_sets(self, namespace: str, label_selector: str = None):
        try:
            # Passa il label_selector alla chiamata ufficiale di K8s
            sts_list = self.apps_v1.list_namespaced_stateful_set(
                namespace, 
                label_selector=label_selector
            )
            return [{
                "name": sts.metadata.name,
                "replicas_desired": sts.spec.replicas,
                "replicas_ready": sts.status.ready_replicas or 0,
                "service_name": sts.spec.service_name,
                "creation_timestamp": sts.metadata.creation_timestamp.isoformat()
            } for sts in sts_list.items]
        except Exception as e:
            self._handle_exception(e, f"List StatefulSets in {namespace}")
    
    # --- DELETE METHODS ---

    def delete_namespaced_stateful_set(self, name: str, namespace: str):
        """Elimina uno StatefulSet dal namespace."""
        try:
            # propagation_policy='Foreground' assicura che i Pod vengano eliminati insieme allo StatefulSet
            self.apps_v1.delete_namespaced_stateful_set(
                name=name, 
                namespace=namespace,
                propagation_policy='Foreground'
            )
            return {"status": "success", "message": f"StatefulSet '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione StatefulSet '{name}'")

    def delete_storage_class(self, name: str):
        """Elimina una StorageClass dal cluster (globale)."""
        try:
            self.storage_v1.delete_storage_class(name=name)
            return {"status": "success", "message": f"StorageClass '{name}' eliminata."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione StorageClass '{name}'")

    # --- DAEMONSETS ---

    def list_daemonsets(self, namespace: str, label_selector: str = None):
        try:
            ds_list = self.apps_v1.list_namespaced_daemon_set(
                namespace,
                label_selector=label_selector
            )
            return [{
                "name": ds.metadata.name,
                "desired": ds.status.desired_number_scheduled,
                "ready": ds.status.number_ready,
                "available": ds.status.number_available or 0,
                "node_selector": ds.spec.template.spec.node_selector or {},
                "labels": ds.metadata.labels or {},
                "creation_timestamp": ds.metadata.creation_timestamp.isoformat()
            } for ds in ds_list.items]
        except Exception as e:
            self._handle_exception(e, f"List DaemonSets in {namespace}")

    def delete_daemonset(self, name: str, namespace: str):
        try:
            self.apps_v1.delete_namespaced_daemon_set(name=name, namespace=namespace)
            return {"status": "success", "message": f"DaemonSet '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione DaemonSet '{name}'")


    # --- CRONJOBS ---

    def list_cronjobs(self, namespace: str, label_selector: str = None):
        try:
            cj_list = self.batch_v1.list_namespaced_cron_job(
                namespace,
                label_selector=label_selector
            )
            return [{
                "name": cj.metadata.name,
                "schedule": cj.spec.schedule,
                "suspend": cj.spec.suspend or False,
                "active": len(cj.status.active or []),
                "last_schedule": cj.status.last_schedule_time.isoformat() if cj.status.last_schedule_time else None,
                "labels": cj.metadata.labels or {},
                "creation_timestamp": cj.metadata.creation_timestamp.isoformat()
            } for cj in cj_list.items]
        except Exception as e:
            self._handle_exception(e, f"List CronJobs in {namespace}")

    def delete_cronjob(self, name: str, namespace: str):
        try:
            self.batch_v1.delete_namespaced_cron_job(name=name, namespace=namespace)
            return {"status": "success", "message": f"CronJob '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione CronJob '{name}'")


    # --- JOBS ---

    def list_jobs(self, namespace: str, label_selector: str = None):
        try:
            job_list = self.batch_v1.list_namespaced_job(
                namespace,
                label_selector=label_selector
            )
            return [{
                "name": job.metadata.name,
                "completions": job.spec.completions,
                "succeeded": job.status.succeeded or 0,
                "failed": job.status.failed or 0,
                "active": job.status.active or 0,
                "start_time": job.status.start_time.isoformat() if job.status.start_time else None,
                "completion_time": job.status.completion_time.isoformat() if job.status.completion_time else None,
                "labels": job.metadata.labels or {},
                "creation_timestamp": job.metadata.creation_timestamp.isoformat()
            } for job in job_list.items]
        except Exception as e:
            self._handle_exception(e, f"List Jobs in {namespace}")

    def delete_job(self, name: str, namespace: str):
        try:
            # propagation_policy Foreground elimina anche i Pod figli
            self.batch_v1.delete_namespaced_job(
                name=name,
                namespace=namespace,
                propagation_policy="Foreground"
            )
            return {"status": "success", "message": f"Job '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione Job '{name}'")


    # --- HORIZONTAL POD AUTOSCALERS ---

    def list_hpas(self, namespace: str, label_selector: str = None):
        try:
            hpa_list = self.autoscaling_v2.list_namespaced_horizontal_pod_autoscaler(
                namespace,
                label_selector=label_selector
            )
            return [{
                "name": hpa.metadata.name,
                "target": hpa.spec.scale_target_ref.name,
                "target_kind": hpa.spec.scale_target_ref.kind,
                "min_replicas": hpa.spec.min_replicas,
                "max_replicas": hpa.spec.max_replicas,
                "current_replicas": hpa.status.current_replicas,
                "desired_replicas": hpa.status.desired_replicas,
                "labels": hpa.metadata.labels or {},
                "creation_timestamp": hpa.metadata.creation_timestamp.isoformat()
            } for hpa in hpa_list.items]
        except Exception as e:
            self._handle_exception(e, f"List HPAs in {namespace}")

    def delete_hpa(self, name: str, namespace: str):
        try:
            self.autoscaling_v2.delete_namespaced_horizontal_pod_autoscaler(
                name=name,
                namespace=namespace
            )
            return {"status": "success", "message": f"HPA '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione HPA '{name}'")


    # --- NETWORK POLICIES ---

    def list_network_policies(self, namespace: str, label_selector: str = None):
        try:
            np_list = self.networking_v1.list_namespaced_network_policy(
                namespace,
                label_selector=label_selector
            )
            return [{
                "name": np.metadata.name,
                "pod_selector": np.spec.pod_selector.match_labels or {},
                "policy_types": np.spec.policy_types or [],
                "ingress_rules": len(np.spec.ingress or []),
                "egress_rules": len(np.spec.egress or []),
                "labels": np.metadata.labels or {},
                "creation_timestamp": np.metadata.creation_timestamp.isoformat()
            } for np in np_list.items]
        except Exception as e:
            self._handle_exception(e, f"List NetworkPolicies in {namespace}")

    def delete_network_policy(self, name: str, namespace: str):
        try:
            self.networking_v1.delete_namespaced_network_policy(name=name, namespace=namespace)
            return {"status": "success", "message": f"NetworkPolicy '{name}' eliminata."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione NetworkPolicy '{name}'")


    # --- CLUSTER ROLES (cluster-wide) ---

    def list_cluster_roles(self):
        try:
            res = self.rbac_v1.list_cluster_role()
            return [{
                "name": cr.metadata.name,
                "rules": len(cr.rules or []),
                "labels": cr.metadata.labels or {},
                "creation_timestamp": cr.metadata.creation_timestamp.isoformat()
            } for cr in res.items]
        except Exception as e:
            self._handle_exception(e, "List ClusterRoles")

    def delete_cluster_role(self, name: str):
        try:
            self.rbac_v1.delete_cluster_role(name=name)
            return {"status": "success", "message": f"ClusterRole '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione ClusterRole '{name}'")


    # --- CLUSTER ROLE BINDINGS (cluster-wide) ---

    def list_cluster_role_bindings(self):
        try:
            res = self.rbac_v1.list_cluster_role_binding()
            return [{
                "name": crb.metadata.name,
                "role_ref": crb.role_ref.name,
                "subjects": [{"kind": s.kind, "name": s.name, "namespace": s.namespace} for s in crb.subjects or []],
                "labels": crb.metadata.labels or {},
                "creation_timestamp": crb.metadata.creation_timestamp.isoformat()
            } for crb in res.items]
        except Exception as e:
            self._handle_exception(e, "List ClusterRoleBindings")

    def delete_cluster_role_binding(self, name: str):
        try:
            self.rbac_v1.delete_cluster_role_binding(name=name)
            return {"status": "success", "message": f"ClusterRoleBinding '{name}' eliminato."}
        except Exception as e:
            self._handle_exception(e, f"Eliminazione ClusterRoleBinding '{name}'")

    def get_daemonset_by_name(self, name: str, namespace: str):
        try:
            ds = self.apps_v1.read_namespaced_daemon_set(name=name, namespace=namespace)
            return {
                "name": ds.metadata.name,
                "namespace": ds.metadata.namespace,
                "desired": ds.status.desired_number_scheduled,
                "ready": ds.status.number_ready,
                "available": ds.status.number_available or 0,
                "node_selector": ds.spec.template.spec.node_selector or {},
                "labels": ds.metadata.labels or {},
                "annotations": ds.metadata.annotations or {},
                "creation_timestamp": ds.metadata.creation_timestamp.isoformat(),
                "resource_version": ds.metadata.resource_version
            }
        except Exception as e:
            self._handle_exception(e, f"Detail DaemonSet '{name}'")

    def get_job_by_name(self, name: str, namespace: str):
        try:
            job = self.batch_v1.read_namespaced_job(name=name, namespace=namespace)
            return {
                "name": job.metadata.name,
                "namespace": job.metadata.namespace,
                "completions": job.spec.completions,
                "succeeded": job.status.succeeded or 0,
                "failed": job.status.failed or 0,
                "active": job.status.active or 0,
                "start_time": job.status.start_time.isoformat() if job.status.start_time else None,
                "completion_time": job.status.completion_time.isoformat() if job.status.completion_time else None,
                "labels": job.metadata.labels or {},
                "annotations": job.metadata.annotations or {},
                "creation_timestamp": job.metadata.creation_timestamp.isoformat(),
                "resource_version": job.metadata.resource_version
            }
        except Exception as e:
            self._handle_exception(e, f"Detail Job '{name}'")

    def get_cronjob_by_name(self, name: str, namespace: str):
        try:
            cj = self.batch_v1.read_namespaced_cron_job(name=name, namespace=namespace)
            return {
                "name": cj.metadata.name,
                "namespace": cj.metadata.namespace,
                "schedule": cj.spec.schedule,
                "suspend": cj.spec.suspend or False,
                "active": len(cj.status.active or []),
                "last_schedule": cj.status.last_schedule_time.isoformat() if cj.status.last_schedule_time else None,
                "labels": cj.metadata.labels or {},
                "annotations": cj.metadata.annotations or {},
                "creation_timestamp": cj.metadata.creation_timestamp.isoformat(),
                "resource_version": cj.metadata.resource_version
            }
        except Exception as e:
            self._handle_exception(e, f"Detail CronJob '{name}'")

    def _handle_exception(self, e: Exception, context: str):
        # 1. Gestione specifica per i TIMEOUT (evita traceback lunghi nei log)
        if isinstance(e, (
            urllib3.exceptions.MaxRetryError,
            urllib3.exceptions.ConnectTimeoutError,
            urllib3.exceptions.ReadTimeoutError,
            urllib3.exceptions.NewConnectionError,
            ConnectionRefusedError
        )):
            # Facciamo un log sintetico a livello backend
            # import logging -> logger = logging.getLogger("k8s_gateway")
            # logger.warning(f"Timeout cluster: {context}")
            
            raise K8sCommunicationException(
                f"Cluster offline ({context}): connection timeout.",
                status_code=504
            )

        # 2. Gestione errori senza status (errori logici o di rete generici)
        if not hasattr(e, 'status'):
             raise K8sBaseException(f"Errore interno ({context}): {str(e)}", status_code=500)

        # 3. Mappatura codici HTTP standard Kubernetes
        if e.status == 404: 
            raise K8sResourceNotFoundException(f"{context} non trovato", status_code=404)
        
        if e.status in [401, 403]: 
            raise K8sUnauthorisedException(f"Accesso negato: {context}", status_code=e.status)
        
        if e.status == 409: 
            raise K8sBaseException(f"Conflitto: {context} esiste già", status_code=409)

        # 4. Fallback per altri errori API
        raise K8sCommunicationException(
            f"Errore K8s ({context}): {getattr(e, 'reason', 'Unknown')}", 
            status_code=e.status
        )
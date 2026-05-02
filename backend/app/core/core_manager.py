from app.core.exceptions import (
    K8sResourceNotFoundException, 
    K8sUnauthorisedException, 
    K8sCommunicationException,
    K8sBaseException
)
from kubernetes.client.rest import ApiException
from kubernetes import utils
from kubernetes import dynamic
from kubernetes.dynamic.exceptions import ResourceNotFoundError
from kubernetes.client import V1Namespace, V1ObjectMeta
import yaml
import tempfile
from datetime import datetime

class CoreManager:
    def __init__(self, k8s_apis: dict):
        """
        Riceve le API dalla Factory e inizializza l'api_client per le utility.
        """
        self.core_v1 = k8s_apis["core_v1"]
        self.apps_v1 = k8s_apis["apps_v1"]
        self.rbac_v1 = k8s_apis["rbac_v1"] 
        self.api_client = self.core_v1.api_client

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

    def list_namespaces(self):
        try:
            ns_list = self.core_v1.list_namespace()
            return {
                "can_list": True,
                "items": [{"name": ns.metadata.name, "status": ns.status.phase} for ns in ns_list.items]
            }
        except Exception as e:
            # Se l'utente non può listare, non lanciamo un errore 403 bloccante,
            # ma informiamo il frontend che la lista è privata.
            return {
                "can_list": false,
                "items": []
            }

    # --- CONFIGMAPS, SECRETS, EVENTS ---

    def list_configmaps(self, namespace):
        try:
            cms = self.core_v1.list_namespaced_config_map(namespace)
            return [{"name": cm.metadata.name, "keys": list(cm.data.keys()) if cm.data else []} for cm in cms.items]
        except Exception as e:
            self._handle_exception(e, f"List ConfigMaps in {namespace}")

    def list_secrets(self, namespace):
        try:
            secrets = self.core_v1.list_namespaced_secret(namespace)
            return [{"name": s.metadata.name, "type": s.type, "keys": list(s.data.keys()) if s.data else []} for s in secrets.items]
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

    def list_pods(self, namespace: str, label_selector: str = None):
        """Elenca i pod con filtro opzionale per label."""
        try:
            # Passiamo label_selector alla chiamata SDK
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace, 
                label_selector=label_selector
            )
            return [
                {
                    "name": p.metadata.name,
                    "status": p.status.phase,
                    "pod_ip": p.status.pod_ip,
                    "node_name": p.spec.node_name,
                    "labels": p.metadata.labels # Utile restituirle per vederle nella UI
                } for p in pods.items
            ]
        except Exception as e:
            self._handle_exception(e, f"List Pods in '{namespace}'")


    def get_pod_by_name(self, name: str, namespace: str):
        try:
            pod = self.core_v1.read_namespaced_pod(name=name, namespace=namespace)
            return {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "pod_ip": pod.status.pod_ip,
                "host_ip": pod.status.host_ip,
                "start_time": pod.status.start_time,
                "labels": pod.metadata.labels
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
            return {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas_spec": dep.spec.replicas,
                "replicas_status": {
                    "total": dep.status.replicas or 0,
                    "available": dep.status.available_replicas or 0,
                    "ready": dep.status.ready_replicas or 0
                },
                "image": dep.spec.template.spec.containers[0].image,
                "strategy": dep.spec.strategy.type,
                "labels": dep.metadata.labels
            }
        except Exception as e:
            self._handle_exception(e, f"Dettaglio Deployment '{name}'")

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
            raise Exception(f"Errore durante il restart: {str(e)}")

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

    def list_services_in_namespace(self, namespace: str):
        try:
            svcs = self.core_v1.list_namespaced_service(namespace)
            return [{
                "name": s.metadata.name,
                "type": s.spec.type,
                "cluster_ip": s.spec.cluster_ip,
                "creation_timestamp": s.metadata.creation_timestamp
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
                "selector": svc.spec.selector,
                "ports": [{"port": p.port, "target_port": p.target_port, "protocol": p.protocol} for p in svc.spec.ports]
            }
        except Exception as e:
            self._handle_exception(e, f"Dettaglio Service '{name}'")

    # --- UNIVERSAL APPLY ---

    def apply_universal_yaml(self, yaml_content, namespace):
        """
        Applica un manifesto YAML multi-risorsa.
        Logica: Prova a creare, se FailToCreateError analizza se è un 409 (già esistente).
        """
        import yaml
        from kubernetes.utils import create_from_dict, FailToCreateError
        from kubernetes.client.rest import ApiException
        import json

        try:
            docs = yaml.safe_load_all(yaml_content)
            results = []
            
            for doc in docs:
                if not doc: continue
                
                if "metadata" not in doc: doc["metadata"] = {}
                doc["metadata"]["namespace"] = namespace
                
                kind = doc.get("kind")
                name = doc["metadata"].get("name")

                try:
                    # TENTATIVO 1: Creazione
                    create_from_dict(self.api_client, doc, namespace=namespace)
                    results.append(f"{kind} '{name}' creato correttamente.")
                
                except FailToCreateError as f:
                    # FailToCreateError contiene una lista di eccezioni API
                    inner_exception = f.api_exceptions[0]
                    
                    # Verifichiamo se l'errore interno è un 409
                    if hasattr(inner_exception, 'status') and inner_exception.status == 409:
                        try:
                            # TENTATIVO 2: Server-Side Apply (Aggiornamento)
                            self._apply_patch_fallback(doc, namespace)
                            results.append(f"{kind} '{name}' aggiornato (Server-Side Apply).")
                        except Exception as patch_err:
                            results.append(f"ERRORE su {kind} '{name}': {str(patch_err)}")
                    else:
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

    def _apply_patch_fallback(self, doc, namespace):
        """Helper per eseguire il Server-Side Apply su risorse esistenti."""
        from kubernetes import dynamic
        
        # Inizializziamo il client dinamico
        dynamic_client = dynamic.DynamicClient(self.api_client)
        
        # Identifichiamo la risorsa
        resource = dynamic_client.resources.get(
            api_version=doc['apiVersion'], 
            kind=doc['kind']
        )
        
        # Eseguiamo il patch con il content_type corretto per SSA
        # force=True permette di sovrascrivere conflitti di field management
        return resource.patch(
            body=doc,
            name=doc['metadata']['name'],
            namespace=namespace,
            content_type='application/apply-patch+yaml',
            field_manager='k8s-cloud-gateway',
            force=True
        )

    # --- NODE OPERATIONS (CLUSTER ADMIN) ---

    def list_nodes(self):
        """
        Elenca i nodi del cluster con dettagli su risorse e versioni.
        Richiede permessi di Cluster Admin.
        """
        try:
            nodes = self.core_v1.list_node()
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

    def _handle_exception(self, e: Exception, context: str):
        if not hasattr(e, 'status'):
             raise K8sBaseException(f"Errore interno ({context}): {str(e)}", status_code=500)
        if e.status == 404: raise K8sResourceNotFoundException(f"{context} non trovato", status_code=404)
        if e.status in [401, 403]: raise K8sUnauthorisedException(f"Accesso negato: {context}", status_code=e.status)
        if e.status == 409: raise K8sBaseException(f"Conflitto: {context} esiste già", status_code=409)
        raise K8sCommunicationException(f"Errore K8s ({context}): {getattr(e, 'reason', 'Unknown')}", status_code=e.status)
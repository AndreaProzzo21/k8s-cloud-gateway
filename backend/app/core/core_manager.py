from app.core.exceptions import (
    K8sResourceNotFoundException, 
    K8sUnauthorisedException, 
    K8sCommunicationException,
    K8sBaseException
)
from kubernetes.client.rest import ApiException
import yaml
from datetime import datetime
from kubernetes.client import V1Namespace, V1ObjectMeta
import tempfile
from kubernetes import utils


class CoreManager:
    def __init__(self, k8s_apis: dict):
        """
        Il costruttore riceve il dizionario di API generato dalla Factory.
        """
        self.core_v1 = k8s_apis["core_v1"]
        self.apps_v1 = k8s_apis["apps_v1"]
        # FONDAMENTALE: Recuperiamo l'api_client sottostante per le funzioni utils
        self.api_client = self.core_v1.api_client

    # --- NAMESPACES ---

    def create_namespace(self, name: str):
        """Crea un nuovo namespace nel cluster."""
        try:
            body = V1Namespace(metadata=V1ObjectMeta(name=name))
            return self.core_v1.create_namespace(body=body)
        except Exception as e:
            self._handle_exception(e, f"Creazione Namespace '{name}'")

    def list_namespaces(self):
        """Elenca tutti i namespace nel cluster."""
        try:
            ns_list = self.core_v1.list_namespace()
            return [{"name": ns.metadata.name, "status": ns.status.phase} for ns in ns_list.items]
        except Exception as e:
            self._handle_exception(e, "List Namespaces")

    # --- CONFIGMAPS ---
    def list_configmaps(self, namespace):
        """Elenca le ConfigMap in un determinato namespace."""
        try:
            cms = self.core_v1.list_namespaced_config_map(namespace)
            return [{
                "name": cm.metadata.name,
                "keys": list(cm.data.keys()) if cm.data else []
            } for cm in cms.items]
        except Exception as e:
            self._handle_exception(e, f"List ConfigMaps in {namespace}")

    # --- SECRETS ---
    def list_secrets(self, namespace):
        """Elenca i Secret (solo nomi e chiavi) per sicurezza."""
        try:
            secrets = self.core_v1.list_namespaced_secret(namespace)
            return [{
                "name": s.metadata.name,
                "type": s.type,
                "keys": list(s.data.keys()) if s.data else []
            } for s in secrets.items]
        except Exception as e:
            self._handle_exception(e, f"List Secrets in {namespace}")

    # --- EVENTS ---
    def list_events(self, namespace):
        """Recupera gli eventi del namespace per il debug."""
        try:
            events = self.core_v1.list_namespaced_event(namespace)
            sorted_events = sorted(events.items, key=lambda x: x.last_timestamp if x.last_timestamp else 0, reverse=True)
            return [{
                "type": e.type,
                "reason": e.reason,
                "message": e.message,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "time": e.last_timestamp.strftime("%H:%M:%S") if e.last_timestamp else "N/A"
            } for e in sorted_events]
        except Exception as e:
            self._handle_exception(e, f"List Events in {namespace}")

    # --- POD OPERATIONS ---

    def get_pods_in_namespace(self, namespace: str):
        try:
            pods_data = self.core_v1.list_namespaced_pod(namespace)
            return [
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "creation_timestamp": pod.metadata.creation_timestamp
                }
                for pod in pods_data.items
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
            self._handle_exception(e, f"Pod '{name}' in '{namespace}'")

    def get_pod_logs(self, name: str, namespace: str, tail_lines: int = None):
        try:
            params = {"name": name, "namespace": namespace}
            if tail_lines:
                params["tail_lines"] = tail_lines
            return self.core_v1.read_namespaced_pod_log(**params)
        except Exception as e:
            self._handle_exception(e, f"Logs for Pod '{name}'")

    # --- DEPLOYMENT OPERATIONS ---

    def list_deployments_in_namespace(self, namespace: str):
        try:
            deployments = self.apps_v1.list_namespaced_deployment(namespace)
            return [
                {
                    "name": dep.metadata.name,
                    "replicas_desired": dep.spec.replicas,
                    "replicas_ready": dep.status.ready_replicas or 0,
                    "status": "Ready" if dep.spec.replicas == dep.status.ready_replicas else "Updating",
                    "creation_timestamp": dep.metadata.creation_timestamp
                }
                for dep in deployments.items
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
                    "updated": dep.status.updated_replicas or 0,
                    "available": dep.status.available_replicas or 0,
                    "ready": dep.status.ready_replicas or 0
                },
                "strategy": dep.spec.strategy.type,
                "image": dep.spec.template.spec.containers[0].image,
                "labels": dep.metadata.labels
            }
        except Exception as e:
            self._handle_exception(e, f"Deployment '{name}' in '{namespace}'")

    def scale_deployment(self, name: str, namespace: str, replicas: int):
        try:
            body = {"spec": {"replicas": replicas}}
            return self.apps_v1.patch_namespaced_deployment_scale(
                name=name, namespace=namespace, body=body
            )
        except Exception as e:
            self._handle_exception(e, f"Scaling Deployment '{name}'")

    def restart_deployment(self, name: str, namespace: str):
        try:
            now = datetime.utcnow().isoformat() + "Z"
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": now
                            }
                        }
                    }
                }
            }
            return self.apps_v1.patch_namespaced_deployment(
                name=name, namespace=namespace, body=body
            )
        except Exception as e:
            self._handle_exception(e, f"Restart Deployment '{name}'")

    def delete_deployment(self, name: str, namespace: str):
        try:
            return self.apps_v1.delete_namespaced_deployment(
                name=name, namespace=namespace
            )
        except Exception as e:
            self._handle_exception(e, f"Delete Deployment '{name}'")

    # --- SERVICE OPERATIONS (AGGIUNTI DI NUOVO) ---

    def list_services_in_namespace(self, namespace: str):
        """Recupera la lista dei Service nel namespace."""
        try:
            services = self.core_v1.list_namespaced_service(namespace)
            return [
                {
                    "name": svc.metadata.name,
                    "type": svc.spec.type,
                    "cluster_ip": svc.spec.cluster_ip,
                    "ports": [
                        {"port": p.port, "protocol": p.protocol, "target_port": p.target_port} 
                        for p in svc.spec.ports
                    ] if svc.spec.ports else [],
                    "creation_timestamp": svc.metadata.creation_timestamp
                }
                for svc in services.items
            ]
        except Exception as e:
            self._handle_exception(e, f"List Services in '{namespace}'")

    def get_service_by_name(self, name: str, namespace: str):
        """Recupera i dettagli di un singolo Service."""
        try:
            svc = self.core_v1.read_namespaced_service(name=name, namespace=namespace)
            return {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "external_ip": svc.status.load_balancer.ingress[0].ip if svc.status.load_balancer.ingress else None,
                "selector": svc.spec.selector,
                "ports": [
                    {"name": p.name, "port": p.port, "protocol": p.protocol, "target_port": p.target_port} 
                    for p in svc.spec.ports
                ] if svc.spec.ports else []
            }
        except Exception as e:
            self._handle_exception(e, f"Service '{name}' in '{namespace}'")

    # --- WRITE OPERATIONS ---

    def create_deployment(self, namespace: str, yaml_content: str):
        try:
            dep_dict = yaml.safe_load(yaml_content)
            if dep_dict.get("kind") != "Deployment":
                raise K8sBaseException("Il file caricato non è un Deployment", status_code=400)

            response = self.apps_v1.create_namespaced_deployment(
                namespace=namespace,
                body=dep_dict
            )
            return {
                "status": "success",
                "name": response.metadata.name,
                "message": f"Risorsa {response.metadata.name} deployata con successo"
            }
        except yaml.YAMLError:
            raise K8sBaseException("Sintassi YAML non valida", status_code=400)
        except Exception as e:
            if hasattr(e, 'status') and e.status == 409:
                raise K8sBaseException("La risorsa esiste già", status_code=409)
            self._handle_exception(e, "Create Deployment")

    def apply_universal_yaml(self, yaml_content, namespace):
        """
        Applica un manifesto YAML multi-risorsa utilizzando le utility di K8s.
        """
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml') as temp_file:
            temp_file.write(yaml_content)
            temp_file.flush()
            
            try:
                utils.create_from_yaml(
                    self.api_client, 
                    temp_file.name, 
                    namespace=namespace
                )
                return {"status": "success", "message": "Risorse create correttamente nel cluster"}
            except Exception as e:
                # Se l'errore non è di tipo K8s API (non ha .status), lo incapsuliamo
                if not hasattr(e, 'status'):
                    raise K8sBaseException(f"Errore durante l'apply universale: {str(e)}", status_code=500)
                self._handle_exception(e, "Universal Apply")

    # --- HELPER PER ECCEZIONI ---

    def _handle_exception(self, e: Exception, context: str):
        """Centralizza la gestione degli errori, verificando la presenza di attributi K8s."""
        # Se non è una ApiException (quindi non ha .status), la trasformiamo in eccezione base
        if not hasattr(e, 'status'):
             raise K8sBaseException(f"Errore inaspettato ({context}): {str(e)}", status_code=500)

        if e.status == 404:
            raise K8sResourceNotFoundException(f"{context} non trovato", status_code=404)
        elif e.status in [401, 403]:
            raise K8sUnauthorisedException(f"Permessi insufficienti per {context}", status_code=e.status)
        elif e.status == 409:
            raise K8sBaseException(f"Conflitto: la risorsa ({context}) esiste già", status_code=409)
        else:
            raise K8sCommunicationException(f"Errore API Kubernetes ({context}): {getattr(e, 'reason', str(e))}", status_code=e.status)
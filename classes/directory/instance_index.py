import threading
from typing import Dict, List, Optional

INSTANCE_KIND_NTDS = "NTDS"
INSTANCE_KIND_GC = "GC"
INSTANCE_KIND_ADAM = "ADAM"


class InstanceIndex:

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._instances: Dict[str, Dict[str, object]] = {}
        self.register("primary", host="localhost", port=389, kind=INSTANCE_KIND_NTDS)
        self.register("gc", host="localhost", port=3268, kind=INSTANCE_KIND_GC)

    def register(self, name: str, host: str, port: int, kind: str = INSTANCE_KIND_NTDS) -> None:
        with self._lock:
            self._instances[name] = {
                "name": name, "host": host, "port": int(port), "kind": kind,
            }

    def resolve(self, name: str) -> Optional[Dict[str, object]]:
        with self._lock:
            entry = self._instances.get(name)
            return dict(entry) if entry is not None else None

    def list_instances(self) -> List[Dict[str, object]]:
        with self._lock:
            return [dict(v) for v in self._instances.values()]

    def kinds(self) -> List[str]:
        with self._lock:
            return sorted({str(v["kind"]) for v in self._instances.values()})

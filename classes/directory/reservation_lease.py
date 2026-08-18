import uuid
from datetime import datetime
from typing import Any


class ReservationLease:

    def __init__(self, owner_sid: str, instance_name: str, session: Any) -> None:
        self.id = str(uuid.uuid4())
        self.owner_sid = owner_sid
        self.instance_name = instance_name
        self.session = session
        self.created_at = datetime.utcnow()
        self.last_used_at = self.created_at
        self.released = False

    def touch(self) -> None:
        self.last_used_at = datetime.utcnow()

    def release(self) -> None:
        self.released = True

    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.last_used_at).total_seconds()

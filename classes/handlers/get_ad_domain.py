from typing import Any, cast

from classes.parsing.context import RequestContext
from classes.directory.domain_loader import DomainLoader
from classes.serialization.domain_serializer import DomainSerializer
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler


class GetADDomainHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/GetADDomainResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            domain: Any = DomainLoader(self.db.db).load_domain()
            if not domain:
                return cast(str, self.faults.custom_action_fault(
                    context.message_id, "GetADDomainFault", "Domain not found"
                ))
            body = DomainSerializer.domain_response(domain)
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[GetADDomain] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "GetADDomainFault", str(e)
            ))

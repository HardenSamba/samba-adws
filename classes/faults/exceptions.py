"""
ADWS Exception classes
Hierarchical exception structure for proper error handling
"""

class ADWSException(Exception):
    """Base exception for all ADWS errors"""
    def __init__(self, message: str, code: int = 0) -> None:
        self.message = message
        self.code = code
        super().__init__(message)

class ADWSProtocolException(ADWSException):
    """Protocol-level errors"""
    pass

class ADWSDataException(ADWSException):
    """Data handling errors"""
    pass

class ADWSAuthenticationException(ADWSException):
    """Authentication failures"""
    pass

class ADWSTransformException(ADWSException):
    """XML/WCF transformation errors"""
    pass

class ADWSObjectNotFoundException(ADWSException):
    """Object not found in AD"""
    pass

class ADWSAccessDeniedException(ADWSException):
    """Access denied error"""
    pass

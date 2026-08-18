from typing import Dict

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
WSA = "http://www.w3.org/2005/08/addressing"
WSEN = "http://schemas.xmlsoap.org/ws/2004/09/enumeration"
WST = "http://schemas.xmlsoap.org/ws/2004/09/transfer"
WSEV = "http://schemas.xmlsoap.org/ws/2004/08/eventing"
AD = "http://schemas.microsoft.com/2008/1/ActiveDirectory"
ADDATA = "http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
DA = "http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
ADLQ = "http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery"
CUSTOM_ACTIONS = "http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
FAULT_NS = "http://schemas.microsoft.com/2008/1/ActiveDirectory/Data/fault"
WSMAN_FAULT = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSD = "http://www.w3.org/2001/XMLSchema"

ENV_NS_MAP: Dict[str, str] = {
    "s": SOAP_ENV,
    "a": WSA,
    "wsen": WSEN,
    "wst": WST,
    "ad": AD,
    "addata": ADDATA,
    "da": DA,
    "adlq": ADLQ,
    "ca": CUSTOM_ACTIONS,
    "xsi": XSI,
    "xsd": XSD,
}

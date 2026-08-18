from typing import Dict, Tuple

SYNTAX_DIRECTORY_STRING: str = "2.5.4.3"
SYNTAX_OCTET_STRING: str = "1.3.6.1.4.1.1466.115.121.1.40"
SYNTAX_INTEGER: str = "1.3.6.1.4.1.1466.115.121.1.27"
SYNTAX_LARGE_INTEGER: str = "1.2.840.113556.1.4.906"
SYNTAX_BOOLEAN: str = "1.3.6.1.4.1.1466.115.121.1.7"
SYNTAX_GENERALIZED_TIME: str = "1.3.6.1.4.1.1466.115.121.1.24"
SYNTAX_OID_STRING: str = "1.3.6.1.4.1.1466.115.121.1.38"
SYNTAX_DN: str = "1.3.6.1.4.1.1466.115.121.1.12"
SYNTAX_SID: str = "1.2.840.113556.1.4.907"
SYNTAX_GUID: str = "1.3.6.1.4.1.1466.115.121.1.40"

XSD_STRING: str = "xsd:string"
XSD_INTEGER: str = "xsd:integer"
XSD_LONG: str = "xsd:long"
XSD_BOOLEAN: str = "xsd:boolean"
XSD_DATETIME: str = "xsd:dateTime"
XSD_BASE64: str = "xsd:base64Binary"

INTEGER_ATTRIBUTES: Tuple[str, ...] = (
    "samaccounttype", "useraccountcontrol", "badpwdcount", "logoncount",
    "primarygroupid", "instancetype", "systemflags", "grouptype", "admincount",
    "countrycode", "codepage", "lockoutthreshold", "minpwdlength",
    "msds-user-account-control-computed", "primarygrouptoken",
    "searchflags", "rangelower", "rangeupper", "linkid", "omsyntax",
    "domainreplica", "msds-behavior-version",
    # RootDSE operational attributes and their syntaxes ([MS-ADDM])
    "supportedldapversion", "domainfunctionality", "forestfunctionality",
    "domaincontrollerfunctionality", "msds-portldap", "msds-portssl",
)

BOOLEAN_ATTRIBUTES: Tuple[str, ...] = (
    "issinglevalued", "systemonly", "showinadvancedviewonly",
    "isdeleted", "isrecycled", "ismemberofpartialattributeset",
    "isdefunct", "objectclasscategory",
    "issynchronized", "isglobalcatalogready",
)

DN_ATTRIBUTES: Tuple[str, ...] = (
    "member", "memberof", "manager", "directreports", "managedby",
    "managedobjects", "fsmoroleowner", "ncname", "subrefs",
    "msds-replvaluemetadata", "objectcategory", "subschemasubentry",
    "msds-keyversionnumber", "wellknownobjects", "otherwellknownobjects",
    # RootDSE naming contexts / service DNs (DSDNString)
    "configurationnamingcontext", "defaultnamingcontext",
    "rootdomainnamingcontext", "schemanamingcontext", "namingcontexts",
    "dsservicename", "servername", "validfsmos",
)

LARGE_INTEGER_ATTRIBUTES: Tuple[str, ...] = (
    "pwdlastset", "lockouttime", "lastlogon", "lastlogoff", "accountexpires",
    "badpasswordtime", "lastlogontimestamp", "creationtime", "ridavailablepool",
    "usnchanged", "usncreated", "msds-keyversionnumber",
    "msds-userpasswordexpirytimecomputed", "highestcommittedusn",
)

BINARY_ATTRIBUTES: Tuple[str, ...] = (
    "objectsid", "objectguid", "schemaidguid", "attributesecurityguid",
    "ntsecuritydescriptor", "thumbnailphoto", "userpassword",
    "msds-allowedtoactonbehalfofotheridentity", "tokengroups", "sidhistory",
    "unicodepwd", "dnsrecord", "logonhours", "parentguid",
    "tokengroupsglobalanduniversal", "tokengroupsnogcacceptable",
    "ms-ds-consistencyguid", "ms-ds-creatorsid",
)

GENERALIZED_TIME_ATTRIBUTES: Tuple[str, ...] = (
    "whencreated", "whenchanged", "dscorepropagationdata",
    "createtimestamp", "modifytimestamp", "currenttime",
)

# The ADWS wire permits only two xsi:type tokens on <ad:value>: xsd:string and
# xsd:base64Binary (reference le codec de valeurs du client rejects any other).
# The semantic LDAP type travels in LdapSyntax, so integers, booleans and times
# ship as xsd:string; only octet/SID/GUID byte values ship as base64Binary.
XSI_TYPE_BY_OID: Dict[str, str] = {
    SYNTAX_INTEGER: XSD_STRING,
    SYNTAX_LARGE_INTEGER: XSD_STRING,
    SYNTAX_BOOLEAN: XSD_STRING,
    SYNTAX_GENERALIZED_TIME: XSD_STRING,
    SYNTAX_OCTET_STRING: XSD_BASE64,
    SYNTAX_SID: XSD_BASE64,
    SYNTAX_GUID: XSD_BASE64,
    SYNTAX_DN: XSD_STRING,
    SYNTAX_OID_STRING: XSD_STRING,
    SYNTAX_DIRECTORY_STRING: XSD_STRING,
}

# DirectorySyntaxType enum member names ([MS-ADDM] / ObjectProjector): the
# LdapSyntax attribute carries this token, NEVER an OID. Windows does
# la conversion en énumération on it, so an OID would make the real PowerShell client reject
# the response.
SYNTAX_NAME_UNICODE: str = "UnicodeString"
SYNTAX_NAME_OCTET: str = "OctetString"
SYNTAX_NAME_INTEGER: str = "Integer"
SYNTAX_NAME_LARGE_INTEGER: str = "LargeInteger"
SYNTAX_NAME_BOOLEAN: str = "Boolean"
SYNTAX_NAME_TIME: str = "GeneralizedTimeString"
SYNTAX_NAME_OID: str = "ObjectIdentifier"
SYNTAX_NAME_DN: str = "DSDNString"
SYNTAX_NAME_SID: str = "SidString"
SYNTAX_NAME_NTSD: str = "NTSecurityDescriptor"

SYNTAX_NAME_BY_OID: Dict[str, str] = {
    SYNTAX_INTEGER: SYNTAX_NAME_INTEGER,
    SYNTAX_LARGE_INTEGER: SYNTAX_NAME_LARGE_INTEGER,
    SYNTAX_BOOLEAN: SYNTAX_NAME_BOOLEAN,
    SYNTAX_GENERALIZED_TIME: SYNTAX_NAME_TIME,
    SYNTAX_OCTET_STRING: SYNTAX_NAME_OCTET,
    SYNTAX_SID: SYNTAX_NAME_SID,
    SYNTAX_DN: SYNTAX_NAME_DN,
    SYNTAX_OID_STRING: SYNTAX_NAME_OID,
    SYNTAX_DIRECTORY_STRING: SYNTAX_NAME_UNICODE,
}

# Attributes whose DirectorySyntaxType cannot be derived from the coarse OID
# buckets (objectSid/sidHistory are bucketed OctetString but are really
# SidString; objectClass defaults UnicodeString but is ObjectIdentifier).
NAME_OVERRIDES: Dict[str, str] = {
    "objectsid": SYNTAX_NAME_SID,
    "sidhistory": SYNTAX_NAME_SID,
    "tokengroups": SYNTAX_NAME_SID,
    "tokengroupsglobalanduniversal": SYNTAX_NAME_SID,
    "tokengroupsnogcacceptable": SYNTAX_NAME_SID,
    "ms-ds-creatorsid": SYNTAX_NAME_SID,
    "ntsecuritydescriptor": SYNTAX_NAME_NTSD,
    "msds-allowedtoactonbehalfofotheridentity": SYNTAX_NAME_NTSD,
    "objectclass": SYNTAX_NAME_OID,
    "supportedcontrol": SYNTAX_NAME_OID,
    "supportedcapabilities": SYNTAX_NAME_OID,
    "supportedextension": SYNTAX_NAME_OID,
}

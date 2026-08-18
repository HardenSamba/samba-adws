"""Catalogue des diagrammes SVG de la documentation ADWS et rasterisation PNG."""

from __future__ import annotations

import os
import subprocess

from svgkit import Flow, Sequence, stack

SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

CLIENT = ("client", "CLIENT Windows", "WCF NetTcpBinding")
SERVER = ("server", "SERVEUR ADWS", "port 9389/tcp")


# -- Empilement protocolaire -------------------------------------------------

def stack_protocols() -> str:
    return stack([
        ("Application ADWS / WS-*", "MS-ADDM, MS-WSTIM, MS-WSDS, MS-WSPELD"),
        ("SOAP 1.2 + WS-Addressing", "W3C SOAP 1.2, WS-Addressing 1.0"),
        ("XML binaire (dictionnaire)", "MS-NBFX, MS-NBFS"),
        ("GSS-API - Kerberos AES256", "RFC 2743, RFC 4121, RFC 4120"),
        ("NegotiateStream (SPNEGO)", "MS-NNS, RFC 4178"),
        (".NET Message Framing", "MS-NMF"),
        ("TCP - port 9389", "RFC 9293"),
    ], width=1560)


def stack_layers() -> str:
    return stack([
        ("Application ADWS / WS-*", "MS-ADDM, MS-WSTIM, MS-WSDS, MS-WSPELD"),
        ("SOAP 1.2 + WS-Addressing", "classes/soap/, classes/parsing/"),
        ("XML binaire WCF (dictionnaire)", "MS-NBFX, MS-NBFS -> src/wcf/"),
        ("GSSAPI - Kerberos AES256 (scelle)", "RFC 4121 -> stream/gssapi.py"),
        ("NegotiateStream (handshake NNS)", "MS-NNS -> stream/negotiate.py"),
        (".NET Message Framing", "MS-NMF -> src/nettcp/nmf.py"),
        ("TCP - port 9389", "socketserver.ForkingTCPServer"),
    ], width=1560)


# -- Cinq phases d'une session ----------------------------------------------

def session_phases(tech: bool = True) -> str:
    seq = Sequence([CLIENT, SERVER], gutter=tech, width=1720, show_anchors=tech)
    seq.divider("Phase 1 - Etablissement TCP")
    seq.msg("client", "server", "connect() net.tcp://dc:9389", anchor="server.py")
    seq.divider("Phase 2 - Preambule NMF (en clair)")
    seq.msg("client", "server", "0x00 Version | 0x01 Mode | 0x02 Via\n0x03 KnownEncoding",
            anchor="protocol.py:41")
    seq.msg("client", "server", "0x09 UpgradeRequestRecord", anchor="protocol.py:49")
    seq.divider("Phase 3 - Upgrade securite (GSSAPI/Kerberos)")
    seq.msg("server", "client", "0x0A UpgradeResponseRecord", kind="resp",
            anchor="protocol.py:92")
    seq.msg("client", "server", "tokens SPNEGO/Kerberos (NNS)", anchor="gssapi.py:104")
    seq.msg("server", "client", "AP-REP -> HandshakeDone 0x14", kind="resp",
            anchor="negotiate.py:82")
    seq.divider("Phase 4 - Messages applicatifs (scelles GSS)")
    seq.msg("client", "server", "0x06 Sized( wrap( SOAP/WCF ) )", anchor="protocol.py:140")
    seq.msg("server", "client", "0x06 Sized( wrap( reponse ) )", kind="resp",
            anchor="protocol.py:153")
    seq.divider("Phase 5 - Terminaison")
    seq.msg("client", "server", "0x07 EndRecord", anchor="protocol.py:170")
    return seq.to_svg()


# -- Preambule NMF detaille --------------------------------------------------

def nmf_preamble(tech: bool = True) -> str:
    seq = Sequence([CLIENT, SERVER], gutter=tech, width=1720, show_anchors=tech)
    seq.note("client", "Sequence fixe, aucune negociation ;\nle serveur accumule sans repondre")
    seq.msg("client", "server", "0x00 0x01 0x00 0x01  VersionRecord\nmajor=1  minor=0",
            anchor="nmf.py:298")
    seq.msg("client", "server", "0x01 0x01  ModeRecord\nmode = Duplex", anchor="nmf.py:306")
    seq.msg("client", "server", "0x02  ViaRecord\nnet.tcp://dc:9389/.../Windows/Resource",
            anchor="nmf.py:313")
    seq.msg("client", "server", "0x03 0x03  KnownEncodingRecord\nbinary + dictionnaire",
            anchor="nmf.py:321")
    seq.msg("client", "server", "0x09  UpgradeRequestRecord\n« application/negotiate »",
            anchor="nmf.py:328")
    seq.selfmsg("server", "fin du preambule : bascule\nen phase securite", anchor="protocol.py:52")
    seq.msg("server", "client", "0x0A  UpgradeResponseRecord", kind="resp",
            anchor="protocol.py:92")
    return seq.to_svg()


# -- Handshake GSSAPI / NegotiateStream -------------------------------------

def gssapi_handshake(tech: bool = True) -> str:
    seq = Sequence([CLIENT, SERVER], gutter=tech, width=1720, show_anchors=tech)
    seq.msg("client", "server", "0x09 UpgradeRequestRecord\n« application/negotiate »  (en clair)",
            anchor="protocol.py:49")
    seq.msg("server", "client", "0x0A UpgradeResponseRecord  (en clair)", kind="resp",
            anchor="protocol.py:92")
    seq.selfmsg("server", "bascule en cadrage MS-NNS" if not tech
                else "GENSECStream installe MS-NNS", anchor="protocol.py:96")
    seq.msg("client", "server", "16 01 00 HH LL || AuthPayload\nHandshakeInProgress "
            "-> InitialContextToken(SPNEGO)\nNegTokenInit{ mechTypes, mechToken=AP-REQ }",
            anchor="gssapi.py:105")
    seq.selfmsg("server",
                ("dechiffre le ticket avec la cle du service\n"
                 "extrait la cle de session\n"
                 "verifie l'authenticator (horodatage)") if not tech else
                ("start_server() ; Credentials.guess()\n"
                 "set_machine_account() -> secrets.tdb\n"
                 "start_mech_by_name(\"spnego\") ; update()"),
                anchor="gssapi.py:107")
    seq.msg("server", "client", "16 01 00 HH LL || NegTokenResp\n"
            "accept-incomplete, supportedMech", kind="resp", anchor="gssapi.py:131")
    seq.msg("client", "server", "16 01 00 HH LL || NegTokenResp{ mechListMIC }",
            anchor="gssapi.py:132")
    seq.selfmsg("server", "contexte de securite etabli" if not tech
                else "update() -> server_finished = True", anchor="gssapi.py:125")
    seq.msg("server", "client", "14 01 00 HH LL || NegTokenResp\n"
            "accept-completed, responseToken = AP-REP", kind="resp", anchor="negotiate.py:82")
    seq.divider("A partir d'ici : prefixe uint32 LE + GSS wrap sur chaque trame")
    seq.msg("client", "server", "<len LE> || wrap( 0x0C PreambleEndRecord )",
            anchor="protocol.py:133")
    seq.msg("server", "client", "<len LE> || wrap( 0x0B PreambleAckRecord )", kind="resp",
            anchor="protocol.py:137")
    return seq.to_svg()


# -- Chaine d'encodage/decodage WCF -----------------------------------------

def wcf_protocol() -> str:
    return Flow([
        ("Document SOAP", "infoset XML"),
        ("Records MS-NBFX", "elements, attributs, textes"),
        ("Dictionnaire MS-NBFS", "chaines connues -> index"),
        ("Jeton GSS-API", "chiffre et signe"),
        ("Trame MS-NMF", "type + longueur"),
    ], width=1720, accent_last=True).to_svg()


def wcf_pipeline() -> str:
    top = Flow([
        ("XML SOAP texte", "reponse handler"),
        ("html_parser.py", "SAX -> events"),
        ("xml2records.py", "records binaires"),
        ("dictionnaire", "chaines -> index"),
        ("octets WCF", "wrap GSS"),
    ], width=1720, accent_last=True).to_svg()
    return top


def wcf_decode() -> str:
    return Flow([
        ("octets WCF recus", "unwrap GSS"),
        ("records/*.py", "elements, attrs, text"),
        ("datatypes.py", "types primitifs"),
        ("XML SOAP texte", "vers dispatcher"),
    ], width=1720, accent_last=True).to_svg()


# -- Dispatcher --------------------------------------------------------------

def dispatcher_flow() -> str:
    return Flow([
        ("Record 0x06", "payload descelle"),
        ("RequestContext", "parse : Action, MessageID, DN"),
        ("HandlerRegistry", "resolve(action)"),
        ("Handler.handle()", "acces SamDB (LDB)"),
        ("XML -> records WCF", "reponse scellee"),
    ], width=1720, vertical=True, accent_last=True).to_svg()


# -- WS-Enumeration ----------------------------------------------------------

def ws_enumeration(tech: bool = True) -> str:
    seq = Sequence([CLIENT, SERVER], gutter=tech, width=1720, show_anchors=tech)
    seq.msg("client", "server", "Enumerate { Filter, BaseObject, Scope }",
            anchor="enumerate.py")
    seq.selfmsg("server", "search() LDB unique ;\nstocke le contexte par UUID", anchor="enumeration.py")
    seq.msg("server", "client", "EnumerateResponse\nEnumerationContext = UUID, Expires",
            kind="resp")
    seq.gap(10)
    seq.msg("client", "server", "Pull { EnumerationContext, MaxElements }", anchor="pull.py")
    seq.msg("server", "client", "PullResponse { Items[...],\nEnumerationContext }", kind="resp")
    seq.note("client", "Repeter Pull tant que le\ncontexte est renvoye")
    seq.msg("client", "server", "Pull { EnumerationContext, MaxElements }", anchor="pull.py")
    seq.msg("server", "client", "PullResponse { Items[...],\nEndOfSequence }", kind="resp")
    seq.gap(10)
    seq.msg("client", "server", "Release { EnumerationContext }", anchor="release.py")
    seq.msg("server", "client", "ReleaseResponse", kind="resp")
    return seq.to_svg()


# -- Cartographie du code ----------------------------------------------------

def code_map() -> str:
    return Flow([
        ("socket TCP", "server.py"),
        ("cadrage NMF", "nettcp/nmf.py"),
        ("descellement GSS", "stream/gssapi.py"),
        ("decode WCF", "src/wcf/"),
        ("dispatcher", "handlers/dispatcher.py"),
        ("SamDB / LDB", "directory/samba_db.py"),
    ], width=1720, vertical=True, accent_last=True).to_svg()


REGISTRY = {
    "stack-protocols": stack_protocols,
    "session-phases-protocols": lambda: session_phases(tech=False),
    "nmf-preamble-protocols": lambda: nmf_preamble(tech=False),
    "gssapi-handshake-protocols": lambda: gssapi_handshake(tech=False),
    "ws-enumeration-protocols": lambda: ws_enumeration(tech=False),
    "wcf-encode-protocols": wcf_protocol,
    "stack": stack_layers,
    "session-phases": session_phases,
    "nmf-preamble": nmf_preamble,
    "gssapi-handshake": gssapi_handshake,
    "wcf-encode": wcf_pipeline,
    "wcf-decode": wcf_decode,
    "dispatcher": dispatcher_flow,
    "ws-enumeration": ws_enumeration,
    "code-map": code_map,
}


def render(name: str, out_dir: str) -> str:
    """Ecrit le SVG du diagramme nomme puis le convertit en PNG haute resolution."""
    if name not in REGISTRY:
        raise KeyError(f"diagramme inconnu : {name}")
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, name + ".svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(REGISTRY[name]())
    subprocess.run([SOFFICE, "--headless", "--norestore", "--convert-to", "png",
                    "--outdir", out_dir, svg_path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    png = os.path.join(out_dir, name + ".png")
    if not os.path.exists(png):
        raise RuntimeError("rastrisation PNG echouee : " + png)
    return png


def render_all(out_dir: str) -> dict[str, str]:
    return {name: render(name, out_dir) for name in REGISTRY}


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else None
    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "diagrams")
    names = [target] if target else list(REGISTRY)
    for nm in names:
        print(render(nm, dest))

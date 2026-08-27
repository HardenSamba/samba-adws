"""The caller's identity, taken from the context that authenticated it."""

import logging
from typing import Any, Optional


# The Samba session for the principal that authenticated on this stream.
#
# `gensec.Security.session_info()` is the only place the caller's identity
# exists once the handshake is over: the stream carries bytes from then on, and
# no request repeats who sent it.
def session_for(stream: Any) -> Optional[Any]:
    context = getattr(stream, "client_ctx", None)
    reader = getattr(context, "session_info", None)
    if not callable(reader):
        return None
    return reader() or None


# How the authenticated principal is named in a log line.
#
# Best effort, because the log is the only record of who a request ran as and a
# session of an unexpected shape is still worth recording as having connected.
def described(session_info: Any) -> str:
    info = getattr(session_info, "info", None)
    account = getattr(info, "account_name", "") or "?"
    domain = getattr(info, "domain_name", "") or "?"
    return f"{domain}\\{account}"


# The authenticated session for one connection, or nothing and a reason.
#
# The refusal is the point of this file. Falling back to SYSTEM here is how a
# connection that authenticated as nobody in particular came to run with every
# right in the directory, while the log line above it said the negotiation had
# succeeded - which it had. Authentication and authorization are two answers,
# and only one of them was being asked for.
def required(stream: Any, logger: logging.Logger, peer: str) -> Optional[Any]:
    try:
        session_info = session_for(stream)
    except Exception as error:
        logger.error(f"[SECURITY] {peer} negotiated and its session could not be read: {error}")
        return None
    if session_info is None:
        logger.error(f"[SECURITY] {peer} negotiated and produced no session; "
                     "refusing rather than running as SYSTEM")
        return None
    logger.info(f"[SECURITY] {peer} authenticated as {described(session_info)}")
    return session_info

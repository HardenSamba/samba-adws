"""Makes `import samba_adws` work from anywhere, by pointing at the payload.

The module is installed as a payload under /usr/share/samba-adws rather than
into this directory, because its own imports are of two top-level packages
called src and classes, and neither name may be taken on a shared path. This
file is what dist-packages holds under the module's name: it puts the payload
on sys.path so the client's imports of src and classes resolve, adds the
payload's own package directory to this package's search path so every
submodule is found there, and then runs the payload's real __init__ in this
namespace.

That last step is the point, and it is done with exec on purpose. A shim that
re-declared the public names by hand -- the first version of this file did --
drifts from the real __init__ the moment that file exports something new:
`python3 -m samba_adws` failed with "cannot import name __version__" because
cli_status reads it from the package and the copy did not have it. Running
the real file means there is one list of exports, kept where the module keeps
it, and this file never has to know what is on it.

The server is not importable this way, and is not meant to be: src and
classes are reachable only once samba_adws has put the payload on the path.
"""

import sys

PAYLOAD = "/usr/share/samba-adws"

if PAYLOAD not in sys.path:
    sys.path.append(PAYLOAD)

__path__.append(PAYLOAD + "/samba_adws")

_real = PAYLOAD + "/samba_adws/__init__.py"
with open(_real, encoding="utf-8") as _source:
    exec(compile(_source.read(), _real, "exec"))
del _source, _real

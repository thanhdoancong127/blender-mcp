"""Path helpers: agents running in WSL pass /mnt/<drive>/... but a Windows-side server and Blender need D:\\..."""
import re
import sys

IS_WINDOWS = sys.platform == "win32"
_MNT = re.compile(r"^/mnt/([a-zA-Z])(/.*)?$")


def to_native(p: str) -> str:
    """Convert a WSL /mnt/<d>/... path to a Windows path when running on Windows; else unchanged."""
    if not IS_WINDOWS:
        return p
    m = _MNT.match(p)
    if not m:
        return p
    return f"{m.group(1).upper()}:" + (m.group(2) or "/").replace("/", "\\")

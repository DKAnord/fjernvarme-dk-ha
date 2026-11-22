"""
MitID BrowserClient - Unofficial Python implementation of the MitID JavaScript browser client.

Vendored from https://github.com/Hundter/MitID-BrowserClient (MIT License).
See LICENSE in this directory and NOTICE in the repository root.

Only the runtime client (BrowserClient + CustomSRP) is shipped; CLI helpers and
example login flows (including Aula) are not included.
"""

from .BrowserClient import BrowserClient
from .CustomSRP import CustomSRP

__version__ = "1.0.0"
__author__ = "Hundter"
__license__ = "MIT"

__all__ = [
    "BrowserClient",
    "CustomSRP",
]

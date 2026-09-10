"""Give a mock upstream client the real key-agnostic HAL reader.

BACK-3084: the AI model listings read their embedded collection through
`ReveniumClient._extract_embedded_data` instead of indexing
`_embedded["aIModelResourceList"]` literally. A bare `MagicMock` client answers
that call with another mock, which iterates as empty and reports `len() == 0` —
so a renderer test would pass while rendering nothing. Wire the real reader onto
the mock so the tests exercise the production extraction.
"""

from types import MethodType
from typing import Any

from src.revenium_mcp_server.client import ReveniumClient


def wire_embedded_reader(client: Any) -> Any:
    """Bind the real `_extract_embedded_data` to `client` and return it."""
    client._extract_embedded_data = MethodType(
        ReveniumClient._extract_embedded_data, client
    )
    return client

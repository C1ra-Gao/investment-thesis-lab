"""Single fixed-host HTTPS request; env credential exists only in request scope.

This is the sole intentional network-import exception in the source audit.
No redirects, proxies, SDK retries, keychain access or response/error-body logs.
"""

from dataclasses import dataclass, field
import http.client
from .deepseek_keychain import KeychainAccessFailure

HOST = "api.deepseek.com"
PATH = "/chat/completions"
MAX_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class TransportResponse:
    status: int | None
    body: bytes = field(default=b"", repr=False)
    complete: bool = False
    received_bytes: int = 0
    error_type: str | None = None


class HTTPSDeepSeekTransport:
    def __init__(self, credential_loader=None):
        self.credential_loader = credential_loader

    def send(self, body: bytes, *, timeout: int) -> TransportResponse:
        # Only invoked after provider budget+authorization gates. Do not retain
        # credentials on self, response objects, exceptions, files or records.
        if self.credential_loader is None:
            return TransportResponse(None, error_type="credential_source_not_configured")
        try:credential = self.credential_loader()
        except KeychainAccessFailure as exc:
            return TransportResponse(None, error_type=str(exc))
        if not credential or not credential.strip():
            return TransportResponse(None, error_type="credential_missing")
        if any(c in credential for c in ("\r", "\n")):
            return TransportResponse(None, error_type="credential_invalid_header")
        connection = None
        status = None
        received = 0
        try:
            connection = http.client.HTTPSConnection(HOST, timeout=timeout)
            connection.request("POST", PATH, body=body, headers={
                "Authorization": "Bearer " + credential,
                "Content-Type": "application/json", "Accept": "application/json",
                "Accept-Encoding": "identity"})
            response = connection.getresponse()
            status = response.status
            data = response.read(MAX_RESPONSE_BYTES + 1)
            received = len(data)
            if credential.encode() in data:
                return TransportResponse(status, received_bytes=received, error_type="response_contains_credential")
            if received > MAX_RESPONSE_BYTES:
                return TransportResponse(status, received_bytes=received, error_type="response_too_large")
            length = response.getheader("Content-Length")
            if length is not None and int(length) != received:
                return TransportResponse(status, received_bytes=received, error_type="response_length_mismatch")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                return TransportResponse(status, received_bytes=received, error_type="unexpected_compression")
            # Error body might echo credentials or service details: never return it.
            return TransportResponse(status, body=data if status == 200 else b"",
                                     complete=True, received_bytes=received)
        except http.client.IncompleteRead as exc:
            return TransportResponse(status, received_bytes=len(exc.partial), error_type="IncompleteRead")
        except (OSError, http.client.HTTPException, ValueError) as exc:
            return TransportResponse(status, received_bytes=received, error_type=type(exc).__name__)
        finally:
            if connection is not None:connection.close()
            credential = None

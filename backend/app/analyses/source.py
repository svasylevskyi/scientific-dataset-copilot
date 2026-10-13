"""Bounded live-worker transport, separate from the frozen reference method."""

from time import monotonic

import httpx

from app.sst.erddap import BASE_URL, DATASET_ID, METADATA_URL, SourceError


class TransientSourceError(SourceError):
    """A bounded worker retry may recover from this source failure."""


def fetch_bytes(client: httpx.Client, url: str, limit: int) -> bytes:
    # Defense in depth: callers cannot turn the connector into a generic URL fetcher.
    if url != METADATA_URL and not url.startswith(f"{BASE_URL}/griddap/{DATASET_ID}.nc?"):
        raise SourceError("Only the registered NOAA source is allowed.")
    started = monotonic()
    content = bytearray()
    try:
        with client.stream(
            "GET", url, follow_redirects=False, headers={"Accept-Encoding": "identity"}
        ) as response:
            response.raise_for_status()
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise SourceError("Compressed source responses are not supported.")
            for piece in response.iter_bytes(chunk_size=65_536):
                if len(content) + len(piece) > limit:
                    raise SourceError("The source response exceeded the download limit.")
                if monotonic() - started > 90:
                    raise SourceError("The source response exceeded the 90-second time limit.")
                content.extend(piece)
    except httpx.HTTPError as exc:
        transient = not isinstance(exc, httpx.HTTPStatusError) or (
            exc.response.status_code == 429 or exc.response.status_code >= 500
        )
        error = TransientSourceError if transient else SourceError
        raise error(f"NOAA request failed ({type(exc).__name__}); retry explicitly.") from exc
    return bytes(content)

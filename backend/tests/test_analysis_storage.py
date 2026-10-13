from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.analyses import storage
from app.analyses.source import fetch_bytes
from app.sst.erddap import METADATA_URL, SourceError, sha256


def test_private_storage_rejects_traversal_and_modified_exports(tmp_path, monkeypatch):
    monkeypatch.setenv("SDC_ARTIFACT_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        storage.safe_path("../secret")
    name = f"{uuid4()}/{uuid4()}/monthly.csv"
    path = storage.safe_path(name)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"abc")
    artifact = SimpleNamespace(relative_path=name, bytes=3, sha256=sha256(b"abc"))
    assert storage.read_artifact(artifact) == b"abc"
    path.write_bytes(b"def")
    with pytest.raises(HTTPException) as error:
        storage.read_artifact(artifact)
    assert error.value.status_code == 503


def test_compressed_source_response_is_rejected_before_decoding():
    import gzip

    content = gzip.compress(b"a" * 100000)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=content)
        )
    ) as client:
        with pytest.raises(SourceError, match="Compressed"):
            fetch_bytes(client, METADATA_URL, 1000)

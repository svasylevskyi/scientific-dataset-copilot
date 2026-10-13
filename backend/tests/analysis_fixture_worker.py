"""CI-only NOAA transport fixture. Never installed as an application capability.

Exercise the real worker/subprocess/pipeline using the checked-in NOAA source
bytes. There is no production fixture mode, public test endpoint, or live CI call.
"""

import sys
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import httpx

from app.analyses import pipeline, worker
from app.sst.erddap import METADATA_URL


def transport(request):
    if str(request.url) == METADATA_URL:
        return httpx.Response(200, content=files("app").joinpath("data/metadata.json").read_bytes())
    query = unquote(str(request.url))
    if "2020-01-01" in query and "[(27.125)" in query:
        return httpx.Response(200, content=files("app").joinpath("data/subset-05.nc").read_bytes())
    return httpx.Response(404)


if __name__ == "__main__":
    if "--request" in sys.argv:
        client = httpx.Client(transport=httpx.MockTransport(transport))
        try:
            with patch("app.sst.cli.httpx.Client", return_value=client):
                pipeline.main()
        finally:
            client.close()
    else:
        execute = worker.execute
        with patch.object(
            worker,
            "execute",
            lambda job: execute(
                job, pipeline_command=[sys.executable, str(Path(__file__).resolve())]
            ),
        ):
            worker.main()

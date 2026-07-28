"""Shared Claude API client setup, used by ask.py and run_baseline.py."""

import os
import tempfile

import certifi
import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

MODEL = "claude-sonnet-5"

# Some local antivirus setups (e.g. Avast) intercept HTTPS with their own root
# cert, which certifi's bundle doesn't trust. If that cert is present, merge it
# into a combined bundle instead of touching system/OpenSSL trust config.
_AVAST_CERT = r"C:\ProgramData\Avast Software\Avast\wscert.pem"


def _cert_bundle() -> str:
    if not os.path.exists(_AVAST_CERT):
        return certifi.where()

    combined_path = os.path.join(tempfile.gettempdir(), "taylan_semantic_ai_lab_cacert.pem")
    needs_rebuild = (
        not os.path.exists(combined_path)
        or os.path.getmtime(_AVAST_CERT) > os.path.getmtime(combined_path)
    )
    if needs_rebuild:
        with open(combined_path, "w") as out:
            out.write(open(certifi.where()).read())
            out.write("\n")
            out.write(open(_AVAST_CERT).read())
    return combined_path


def get_client() -> Anthropic:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your-key-here":
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env.")
    return Anthropic(api_key=api_key, http_client=httpx.Client(verify=_cert_bundle()))

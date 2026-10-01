"""Official source URLs used by the SOP corpus and its public metadata."""

DEFAULT_SOURCE_URL = (
    "https://www.sba.gov/document/sop-50-10-lender-development-company-loan-programs"
)

SOURCE_URL_ALIASES = {
    "https://www.sba.gov/document/sop-50-10-8-1": DEFAULT_SOURCE_URL,
}


def canonicalize_source_url(source_url: str) -> str:
    """Replace retired official SBA URLs while preserving other source URLs."""
    return SOURCE_URL_ALIASES.get(source_url.rstrip("/"), source_url)
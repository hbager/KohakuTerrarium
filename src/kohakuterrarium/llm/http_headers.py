"""Default HTTP headers applied to outbound LLM API requests."""

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
)


def with_browser_user_agent(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Return ``headers`` carrying a browser User-Agent unless one is set explicitly."""
    merged: dict[str, str] = {}
    explicit = ""
    for key, value in (headers or {}).items():
        if key.lower() == "user-agent":
            explicit = value
        else:
            merged[key] = value
    merged["User-Agent"] = explicit or BROWSER_USER_AGENT
    return merged

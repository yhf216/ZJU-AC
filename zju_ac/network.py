"""Direct HTTP sessions without environment or operating-system proxy discovery."""

import requests


def configure_direct_session(session: requests.Session) -> requests.Session:
    # trust_env also prevents Requests from consulting system proxies via urllib.
    # Keep the cookie jar, TLS verification, adapters, and headers unchanged.
    session.trust_env = False
    session.proxies.clear()
    return session


def create_direct_session() -> requests.Session:
    return configure_direct_session(requests.Session())

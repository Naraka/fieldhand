"""Sign in with GitHub (OAuth web flow), using only the standard library.

No scope is requested: the server only reads the public profile.
"""

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from . import config


def authorize_url(state):
    query = urllib.parse.urlencode({"client_id": config.GITHUB_CLIENT_ID, "state": state})
    return f"https://github.com/login/oauth/authorize?{query}"


def _call(url, data=None, token=None):
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_user(code):
    """Exchange the code from the callback for the user's public profile."""
    data = urllib.parse.urlencode(
        {
            "client_id": config.GITHUB_CLIENT_ID,
            "client_secret": config.GITHUB_CLIENT_SECRET,
            "code": code,
        }
    ).encode()
    token = _call("https://github.com/login/oauth/access_token", data).get("access_token")
    if not token:
        raise ValueError("GitHub did not accept the sign-in code")
    return _call("https://api.github.com/user", token=token)


def account_age_days(user):
    created = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
    return (datetime.now(UTC) - created).days

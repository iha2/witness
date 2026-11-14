"""Bitbucket Cloud connector (T4).

The token is read from WITNESS_BITBUCKET_TOKEN and only ever sent in an
Authorization header or handed to git through GIT_CONFIG_* env variables.
It is never placed in argv, URLs, logs or exception messages.
"""

import json
import os
import re
import urllib.error
import urllib.request

from witness.shared import EnvError, PRInfo, UsageError

TOKEN_ENV = "WITNESS_BITBUCKET_TOKEN"
API = "https://api.bitbucket.org/2.0/repositories"
_URL_RE = re.compile(r"^https://bitbucket\.org/([\w.-]+)/([\w.-]+)/pull-requests/(\d+)/?$")
_SHORT_RE = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")


def git_auth_env(token: str) -> dict[str, str]:
    """Env for git subprocesses so the token stays out of argv and .git/config."""
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}",
    }


def _parse_ref(ref: str) -> tuple[str, str, str]:
    m = _URL_RE.match(ref) or _SHORT_RE.match(ref)
    if not m:
        raise UsageError(f"not a Bitbucket pull request reference: {ref!r}")
    return m.group(1), m.group(2), m.group(3)


class BitbucketHost:
    def fetch(self, ref: str) -> PRInfo:
        ws, repo, num = _parse_ref(ref)
        token = os.environ.get(TOKEN_ENV)
        if not token:
            raise EnvError(f"{TOKEN_ENV} is not set")
        req = urllib.request.Request(
            f"{API}/{ws}/{repo}/pullrequests/{num}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise EnvError(
                    f"Bitbucket rejected the token (HTTP {e.code}); check {TOKEN_ENV}"
                ) from None
            raise EnvError(f"Bitbucket request failed (HTTP {e.code})") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise EnvError("Bitbucket request failed (network or bad reply)") from None
        try:
            return PRInfo(
                host="bitbucket",
                base_sha=data["destination"]["commit"]["hash"],
                head_sha=data["source"]["commit"]["hash"],
                title=data.get("title") or "",
                body=data.get("description") or "",
            )
        except (KeyError, TypeError, AttributeError):
            raise EnvError("unexpected Bitbucket reply shape") from None

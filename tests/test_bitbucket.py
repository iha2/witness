import io
import json
import logging
import urllib.error

import pytest

from witness import bitbucket
from witness.shared import EnvError, PRInfo, UsageError

URL = "https://bitbucket.org/acme/shop/pull-requests/482"
REPLY = {
    "title": "Simplify discount rules",
    "description": "body text",
    "source": {"commit": {"hash": "9b7e044"}},
    "destination": {"commit": {"hash": "3f2a1c9"}},
}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def patch_urlopen(monkeypatch, reply=None, err=None, seen=None):
    def fake(req, timeout=None):
        if seen is not None:
            seen.append(req)
        if err is not None:
            raise err
        return FakeResp(json.dumps(reply).encode())

    monkeypatch.setattr(bitbucket.urllib.request, "urlopen", fake)


def test_git_auth_env():
    assert bitbucket.git_auth_env("t0k") == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": "Authorization: Bearer t0k",
    }


def test_fetch(monkeypatch):
    monkeypatch.setenv("WITNESS_BITBUCKET_TOKEN", "t0k")
    seen = []
    patch_urlopen(monkeypatch, REPLY, seen=seen)
    info = bitbucket.BitbucketHost().fetch(URL)
    assert info == PRInfo("bitbucket", "3f2a1c9", "9b7e044", "Simplify discount rules", "body text")
    assert seen[0].full_url == "https://api.bitbucket.org/2.0/repositories/acme/shop/pullrequests/482"


def test_fetch_short_ref(monkeypatch):
    monkeypatch.setenv("WITNESS_BITBUCKET_TOKEN", "t0k")
    patch_urlopen(monkeypatch, REPLY)
    assert bitbucket.BitbucketHost().fetch("acme/shop#482").head_sha == "9b7e044"


def test_token_never_in_argv_or_logs(monkeypatch, caplog):
    monkeypatch.setenv("WITNESS_BITBUCKET_TOKEN", "t0k")
    caplog.set_level(logging.DEBUG)
    seen = []
    patch_urlopen(monkeypatch, REPLY, seen=seen)
    bitbucket.BitbucketHost().fetch(URL)
    assert "t0k" not in caplog.text
    assert all("t0k" not in r.full_url for r in seen)


def test_missing_token_env_error(monkeypatch):
    monkeypatch.delenv("WITNESS_BITBUCKET_TOKEN", raising=False)
    with pytest.raises(EnvError):
        bitbucket.BitbucketHost().fetch(URL)


def test_401_message(monkeypatch):
    monkeypatch.setenv("WITNESS_BITBUCKET_TOKEN", "t0k")
    err = urllib.error.HTTPError(URL, 401, "Unauthorized t0k", {}, None)
    patch_urlopen(monkeypatch, err=err)
    with pytest.raises(EnvError) as ei:
        bitbucket.BitbucketHost().fetch(URL)
    assert "t0k" not in str(ei.value)
    assert "401" in str(ei.value)


def test_other_http_error(monkeypatch):
    monkeypatch.setenv("WITNESS_BITBUCKET_TOKEN", "t0k")
    err = urllib.error.HTTPError(URL, 404, "nf", {}, None)
    patch_urlopen(monkeypatch, err=err)
    with pytest.raises(EnvError):
        bitbucket.BitbucketHost().fetch(URL)


def test_bad_ref_usage(monkeypatch):
    monkeypatch.setenv("WITNESS_BITBUCKET_TOKEN", "t0k")
    with pytest.raises(UsageError):
        bitbucket.BitbucketHost().fetch("acme#x")

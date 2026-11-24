"""Vérification de mise à jour (app/updater.py), GitHub simulé."""

import io
import urllib.error

from app.database import init_database
from app import updater

init_database()


def test_comparaison_des_versions():
    assert updater.is_newer("0.11.1", "0.11.0")
    assert updater.is_newer("v1.0", "0.11.3")
    assert not updater.is_newer("0.10.3", "0.11.0")
    assert not updater.is_newer("0.11.0", "0.11.0")


def test_release_publiee(monkeypatch):
    monkeypatch.setattr(updater, "_json", lambda url: {
        "tag_name": "v9.9.0", "body": "Nouveautés", "tarball_url": "https://api.github.com/x/tarball/v9.9.0"})
    result = updater.check()
    assert result["ok"] and result["version"] == "9.9.0" and result["newer"]
    assert result["archive_url"].endswith("v9.9.0")


def test_sans_release_lit_la_branche(monkeypatch):
    def fake_json(url):
        if url.endswith("/releases/latest"):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return {"default_branch": "main"}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(updater, "_json", fake_json)
    monkeypatch.setattr(updater, "_request", lambda url, **kw: FakeResponse(b"0.0.1\n"))
    result = updater.check()
    assert result["ok"] and result["version"] == "0.0.1" and not result["newer"]
    assert result["archive_url"].endswith("/tarball/main")


def test_depot_prive_sans_jeton(monkeypatch):
    def fake_json(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    def fake_request(url, **kw):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(updater, "_json", fake_json)
    monkeypatch.setattr(updater, "_request", fake_request)
    result = updater.check()
    assert not result["ok"] and "privé" in result["error"]

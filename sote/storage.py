from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import requests


class StorageError(RuntimeError):
    pass


def empty_state() -> dict:
    return {"version": 1, "listings": {}, "sources": {}, "reddit": {}, "heartbeat_at": 0}


def validate_state(state: object) -> dict:
    if not isinstance(state, dict) or state.get("version") != 1:
        raise StorageError("Unsupported/corrupt state. Refusing to silently reset alert history.")
    for key in ("listings", "sources", "reddit"):
        if not isinstance(state.get(key), dict):
            raise StorageError("Invalid state structure; inspect tracker-state/state.json")
    return state


class LocalStore:
    def __init__(self, path: str = "state.json"):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return empty_state()
        try:
            return validate_state(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            raise StorageError("Cannot read local state; it was not reset") from None

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)


class GitHubStore:
    """A separate branch holds observations and deduplication state, never secrets."""
    def __init__(self):
        self.repo = os.getenv("GITHUB_REPOSITORY", "")
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.branch = "tracker-state"
        self.file_sha = None
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo) or not self.token:
            raise StorageError("GitHub repository/token environment is missing")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}",
                                     "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        self.base = "https://api.github.com/repos/" + self.repo

    def request(self, method: str, endpoint: str, **kwargs):
        try:
            return self.session.request(method, self.base + endpoint, timeout=25,
                                        allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise StorageError("GitHub state request failed; credentials were not logged") from None

    def load(self) -> dict:
        r = self.request("GET", "/git/ref/heads/" + self.branch)
        if r.status_code == 404:
            sha = os.getenv("GITHUB_SHA", "")
            if not re.fullmatch(r"[a-f0-9]{40}", sha):
                raise StorageError("Cannot initialize state branch: GITHUB_SHA missing")
            made = self.request("POST", "/git/refs", json={"ref": "refs/heads/" + self.branch, "sha": sha})
            if made.status_code != 201:
                raise StorageError(f"Cannot create tracker-state (HTTP {made.status_code}). Check workflow contents: write permission.")
        elif r.status_code != 200:
            raise StorageError(f"Cannot read state branch (HTTP {r.status_code})")
        r = self.request("GET", "/contents/state.json", params={"ref": self.branch})
        if r.status_code == 404:
            return empty_state()
        if r.status_code != 200:
            raise StorageError(f"Cannot read state file (HTTP {r.status_code})")
        try:
            obj = r.json()
            self.file_sha = obj["sha"]
            return validate_state(json.loads(base64.b64decode(obj["content"]).decode("utf-8")))
        except (ValueError, KeyError, TypeError):
            raise StorageError("State file is unreadable; alert history was not reset") from None

    def save(self, state: dict) -> None:
        data = json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8")
        if len(data) > 900_000:
            raise StorageError("State exceeded safe size; prune history before continuing")
        body = {"message": "Record SOTE availability observations", "branch": self.branch,
                "content": base64.b64encode(data).decode("ascii")}
        if self.file_sha:
            body["sha"] = self.file_sha
        r = self.request("PUT", "/contents/state.json", json=body)
        if r.status_code not in {200, 201}:
            raise StorageError(f"State not saved (HTTP {r.status_code}); some alerts could repeat next run")
        try:
            self.file_sha = r.json()["content"]["sha"]
        except (ValueError, KeyError, TypeError):
            raise StorageError("GitHub did not confirm state commit") from None

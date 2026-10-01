"""API tests for API keys and who may write what, against real PostgreSQL.

What is worth pinning down: every write needs a key and every read needs
none; a project key writes to its own project and nowhere else, including
through routes addressed by run id; only the admin key makes projects and
keys; the database never holds a key, only its hash; a revoked key stops at
once; and an unauthenticated caller learns nothing, not even what a valid
body would look like.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from tests.test_comparisons_api import _report

STARTED = "2026-09-18T10:00:00+00:00"
COMPLETED = "2026-09-18T10:00:04+00:00"


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def _project(api_client: AsyncClient, name: str = "Support") -> str:
    response = await api_client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _issue(api_client: AsyncClient, project_id: str, name: str | None = None) -> dict:
    response = await api_client.post(f"/api/v1/projects/{project_id}/keys", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _run(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "agent_name": "support-agent",
        "input": {},
        "started_at": STARTED,
        "completed_at": COMPLETED,
    }
    body.update(overrides)
    return body


async def _ingest(client: AsyncClient, project_id: str, key: str, **overrides: Any) -> Any:
    return await client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=_run(**overrides), headers=_bearer(key)
    )


def _writes(project_id: str, run_id: str, key_id: str) -> list[tuple[str, str, dict | None]]:
    """Every route that needs a key, with a body that would otherwise be valid."""
    return [
        ("POST", "/api/v1/projects", {"name": "x"}),
        ("POST", f"/api/v1/projects/{project_id}/runs", {"agent_name": "a", "input": {}}),
        ("POST", f"/api/v1/projects/{project_id}/runs/ingest", _run()),
        ("POST", f"/api/v1/runs/{run_id}/complete", {"output": {}, "status": "completed"}),
        ("POST", f"/api/v1/runs/{run_id}/events", {"sequence": 1, "event_type": "agent_start"}),
        ("POST", f"/api/v1/runs/{run_id}/comparison", _report(run_id, run_id)),
        ("POST", f"/api/v1/projects/{project_id}/keys", {}),
        ("GET", f"/api/v1/projects/{project_id}/keys", None),
        ("DELETE", f"/api/v1/keys/{key_id}", None),
    ]


# --- No key, wrong key ------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, _bearer("at_not-a-real-key"), {"Authorization": "Basic eDp5"}],
    ids=["no-key", "unknown-key", "not-bearer"],
)
async def test_every_keyed_route_answers_401_without_a_valid_key(
    api_client: AsyncClient, anon_client: AsyncClient, headers: dict[str, str]
) -> None:
    project_id = await _project(api_client)
    key = await _issue(api_client, project_id)
    run_id = str(uuid.uuid4())
    assert (await api_client.post(
        f"/api/v1/projects/{project_id}/runs", json={"agent_name": "a", "input": {}}
    )).status_code == 201

    for method, path, body in _writes(project_id, run_id, key["id"]):
        response = await anon_client.request(method, path, json=body, headers=headers)

        assert response.status_code == 401, (method, path, response.text)
        assert response.headers["www-authenticate"] == "Bearer"
        assert "valid API key" in response.json()["detail"]


async def test_401_comes_before_validating_the_body(anon_client: AsyncClient) -> None:
    """Without a key, a caller is not told what a valid body looks like."""
    response = await anon_client.post("/api/v1/projects", json={"name": ""})

    assert response.status_code == 401


async def test_reads_need_no_key(api_client: AsyncClient, anon_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    key = await _issue(api_client, project_id)
    recording = (await _ingest(api_client, project_id, key["key"])).json()["id"]
    replay = (await _ingest(api_client, project_id, key["key"], replay_of_run_id=recording)).json()
    stored = await api_client.post(
        f"/api/v1/runs/{replay['id']}/comparison", json=_report(recording, replay["id"])
    )
    assert stored.status_code == 201, stored.text

    for path in (
        "/api/v1/projects",
        f"/api/v1/projects/{project_id}",
        f"/api/v1/projects/{project_id}/runs",
        f"/api/v1/projects/{project_id}/comparisons",
        f"/api/v1/runs/{recording}",
        f"/api/v1/runs/{recording}/events",
        f"/api/v1/runs/{replay['id']}/comparison",
    ):
        assert (await anon_client.get(path)).status_code == 200, path


# --- Project keys -----------------------------------------------------------


async def test_a_project_key_writes_to_its_own_project(
    api_client: AsyncClient, anon_client: AsyncClient
) -> None:
    project_id = await _project(api_client)
    key = (await _issue(api_client, project_id))["key"]

    recording = await _ingest(anon_client, project_id, key)
    assert recording.status_code == 201, recording.text
    replay = await _ingest(anon_client, project_id, key, replay_of_run_id=recording.json()["id"])
    assert replay.status_code == 201, replay.text
    report = await anon_client.post(
        f"/api/v1/runs/{replay.json()['id']}/comparison",
        json=_report(recording.json()["id"], replay.json()["id"]),
        headers=_bearer(key),
    )
    assert report.status_code == 201, report.text

    started = await anon_client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"agent_name": "a", "input": {}},
        headers=_bearer(key),
    )
    run_id = started.json()["id"]
    event = await anon_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"sequence": 1, "event_type": "agent_start"},
        headers=_bearer(key),
    )
    assert event.status_code == 201, event.text
    done = await anon_client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"output": {}, "status": "completed"},
        headers=_bearer(key),
    )
    assert done.status_code == 200, done.text


async def test_a_project_key_cannot_write_to_another_project(
    api_client: AsyncClient, anon_client: AsyncClient
) -> None:
    """Including through routes addressed by run id, where the URL names no project."""
    mine = await _project(api_client, "mine")
    theirs = await _project(api_client, "theirs")
    my_key = (await _issue(api_client, mine))["key"]
    their_key = (await _issue(api_client, theirs))["key"]
    started = await api_client.post(
        f"/api/v1/projects/{theirs}/runs", json={"agent_name": "a", "input": {}}
    )
    their_run = started.json()["id"]
    their_recording = (await _ingest(anon_client, theirs, their_key)).json()["id"]
    their_replay = (
        await _ingest(anon_client, theirs, their_key, replay_of_run_id=their_recording)
    ).json()["id"]

    attempts = [
        ("POST", f"/api/v1/projects/{theirs}/runs", {"agent_name": "a", "input": {}}),
        ("POST", f"/api/v1/projects/{theirs}/runs/ingest", _run()),
        ("POST", f"/api/v1/runs/{their_run}/events", {"sequence": 1, "event_type": "agent_start"}),
        ("POST", f"/api/v1/runs/{their_run}/complete", {"output": {}, "status": "completed"}),
        ("POST", f"/api/v1/runs/{their_replay}/comparison", _report(their_recording, their_replay)),
    ]
    for method, path, body in attempts:
        response = await anon_client.request(method, path, json=body, headers=_bearer(my_key))

        assert response.status_code == 403, (path, response.text)
        assert "another project" in response.json()["detail"]

    # Nothing was written: the run is still running with no events, and has no report.
    assert (await anon_client.get(f"/api/v1/runs/{their_run}")).json()["status"] == "running"
    assert (await anon_client.get(f"/api/v1/runs/{their_run}/events")).json() == []
    assert (await anon_client.get(f"/api/v1/runs/{their_replay}/comparison")).status_code == 404


async def test_a_project_key_cannot_make_projects_or_manage_keys(
    api_client: AsyncClient, anon_client: AsyncClient
) -> None:
    project_id = await _project(api_client)
    key = await _issue(api_client, project_id)
    headers = _bearer(key["key"])

    for method, path, body in [
        ("POST", "/api/v1/projects", {"name": "x"}),
        ("POST", f"/api/v1/projects/{project_id}/keys", {}),
        ("GET", f"/api/v1/projects/{project_id}/keys", None),
        ("DELETE", f"/api/v1/keys/{key['id']}", None),
    ]:
        response = await anon_client.request(method, path, json=body, headers=headers)

        assert response.status_code == 403, (path, response.text)
        assert "admin key" in response.json()["detail"]


async def test_an_unknown_project_is_404_for_the_admin_and_403_for_a_project_key(
    api_client: AsyncClient, anon_client: AsyncClient
) -> None:
    """The key's scope is checked first; a project key cannot probe which projects exist."""
    project_id = await _project(api_client)
    key = (await _issue(api_client, project_id))["key"]
    missing = str(uuid.uuid4())

    assert (await _ingest(api_client, missing, "at_test-admin-key")).status_code == 404
    assert (await _ingest(anon_client, missing, key)).status_code == 403


# --- Issuing, storing, listing, revoking ------------------------------------


async def test_issuing_a_key_returns_it_once_and_stores_only_its_hash(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    project_id = await _project(api_client)

    issued = await _issue(api_client, project_id, name="ci")

    key = issued["key"]
    assert key.startswith("at_")
    assert len(key) == 46  # the marker and 32 random bytes, base64url
    assert issued["prefix"] == key[:11]
    assert issued["name"] == "ci"
    assert issued["project_id"] == project_id
    assert issued["revoked_at"] is None

    row = await db_session.scalar(select(ApiKey).where(ApiKey.id == uuid.UUID(issued["id"])))
    assert row is not None
    assert row.key_hash == hashlib.sha256(key.encode()).hexdigest()
    stored = [str(getattr(row, column.key)) for column in ApiKey.__table__.columns]
    assert not any(key in value for value in stored)
    assert key not in repr(row) and row.key_hash not in repr(row)


async def test_every_key_is_different(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)

    keys = {(await _issue(api_client, project_id))["key"] for _ in range(5)}

    assert len(keys) == 5


async def test_listing_keys_never_shows_a_key_or_hash(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    first = await _issue(api_client, project_id, name="first")
    second = await _issue(api_client, project_id, name="second")
    other = await _project(api_client, "other")
    await _issue(api_client, other)

    response = await api_client.get(f"/api/v1/projects/{project_id}/keys")

    assert response.status_code == 200
    listed = response.json()
    # A set: inside the test's one transaction now() is constant, so both keys
    # share a created_at and their order falls to the id tiebreak.
    assert {item["id"] for item in listed} == {first["id"], second["id"]}
    for item in listed:
        assert set(item) == {"id", "project_id", "name", "prefix", "created_at", "revoked_at"}
    assert first["key"] not in response.text and second["key"] not in response.text


async def test_a_revoked_key_stops_working_and_revoking_again_changes_nothing(
    api_client: AsyncClient, anon_client: AsyncClient
) -> None:
    project_id = await _project(api_client)
    issued = await _issue(api_client, project_id)
    assert (await _ingest(anon_client, project_id, issued["key"])).status_code == 201

    revoked = await api_client.delete(f"/api/v1/keys/{issued['id']}")

    assert revoked.status_code == 204
    assert (await _ingest(anon_client, project_id, issued["key"])).status_code == 401
    listed = (await api_client.get(f"/api/v1/projects/{project_id}/keys")).json()
    first_revoked_at = listed[0]["revoked_at"]
    assert first_revoked_at is not None

    again = await api_client.delete(f"/api/v1/keys/{issued['id']}")

    assert again.status_code == 204
    listed = (await api_client.get(f"/api/v1/projects/{project_id}/keys")).json()
    assert listed[0]["revoked_at"] == first_revoked_at


async def test_key_management_on_something_missing_is_404(api_client: AsyncClient) -> None:
    missing = uuid.uuid4()

    assert (await api_client.post(f"/api/v1/projects/{missing}/keys", json={})).status_code == 404
    assert (await api_client.get(f"/api/v1/projects/{missing}/keys")).status_code == 404
    assert (await api_client.delete(f"/api/v1/keys/{missing}")).status_code == 404


async def test_deleting_a_project_deletes_its_keys(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.project import Project

    project_id = await _project(api_client)
    issued = await _issue(api_client, project_id)

    project = await db_session.get(Project, uuid.UUID(project_id))
    await db_session.delete(project)
    await db_session.flush()

    db_session.expunge_all()
    assert await db_session.get(ApiKey, uuid.UUID(issued["id"])) is None


# --- The admin key ----------------------------------------------------------


async def test_without_an_admin_key_configured_nobody_is_admin(
    api_client: AsyncClient, anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    project_id = await _project(api_client)
    key = (await _issue(api_client, project_id))["key"]
    monkeypatch.delenv("ADMIN_KEY_SHA256")
    get_settings.cache_clear()

    assert (await api_client.post("/api/v1/projects", json={"name": "x"})).status_code == 401
    # Project keys keep working: an unset admin key closes administration, not ingest.
    assert (await _ingest(anon_client, project_id, key)).status_code == 201


async def test_the_admin_hash_itself_is_not_a_key(anon_client: AsyncClient) -> None:
    """Whoever reads ADMIN_KEY_SHA256 from the environment still cannot call the API."""
    digest = hashlib.sha256(b"at_test-admin-key").hexdigest()

    response = await anon_client.post(
        "/api/v1/projects", json={"name": "x"}, headers=_bearer(digest)
    )

    assert response.status_code == 401

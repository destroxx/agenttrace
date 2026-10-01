"""Business logic for API keys: who is calling, and what they may write.

Two kinds of key. The admin key is configured, not stored: its SHA-256 sits in
the environment, and it creates projects and issues project keys. A project
key is issued by the admin, stored only as a hash, and may write to its own
project and nowhere else -- so a key leaked from one agent's environment
cannot touch another project's recordings.

Reads need no key at all. The dashboard is a public, read-only view; keys
guard the writes, because a recording is a test fixture and the value of a
fixture is that nobody can quietly change it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.project import Project
from app.schemas.api_key import ApiKeyCreate
from app.services.exceptions import AuthenticationError, NotFoundError, PermissionDeniedError

# Recognisable in a leaked log or a secret scanner, like GitHub's `ghp_`.
KEY_PREFIX = "at_"
# What a list shows: the marker plus eight random characters, enough to tell
# keys apart and far too few to guess the remaining 35.
DISPLAY_PREFIX_LENGTH = 11


def hash_key(key: str) -> str:
    """The hex SHA-256 every key is stored and looked up by."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    """A new key: the marker and 256 random bits, URL-safe."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class Caller:
    """Who an authenticated request is from.

    `project_id` is the one project a project key may write to; None means the
    admin key, which may write anywhere. Services take a Caller and check it
    themselves, because only they know which project a run-addressed request
    really touches.
    """

    project_id: uuid.UUID | None

    @classmethod
    def admin(cls) -> Caller:
        return cls(project_id=None)

    @property
    def is_admin(self) -> bool:
        return self.project_id is None

    def require_admin(self) -> None:
        if not self.is_admin:
            raise PermissionDeniedError("This needs the admin key; a project key cannot do it.")

    def require_project(self, project_id: uuid.UUID) -> None:
        """Allow the write only if this key may write to `project_id`."""
        if not self.is_admin and self.project_id != project_id:
            raise PermissionDeniedError(
                f"This API key belongs to another project and cannot write to {project_id}."
            )


class ApiKeyService:
    """Authenticates requests and issues, lists and revokes project keys."""

    def __init__(self, session: AsyncSession, admin_key_sha256: SecretStr | None) -> None:
        self._session = session
        self._admin_key_sha256 = admin_key_sha256

    async def authenticate(self, key: str | None) -> Caller:
        """Turn a presented key into a Caller, or raise `AuthenticationError`.

        The admin hash is compared in constant time, so response timing does
        not reveal how much of a guess was right. A project key is found by
        its hash through a unique index: the lookup only ever sees the hash
        of the guess, which tells a timing attacker nothing about any real key.
        """
        if not key:
            raise AuthenticationError
        digest = hash_key(key)
        if self._admin_key_sha256 is not None and hmac.compare_digest(
            digest, self._admin_key_sha256.get_secret_value()
        ):
            return Caller.admin()
        api_key = await self._session.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
        if api_key is None or api_key.is_revoked:
            raise AuthenticationError
        return Caller(project_id=api_key.project_id)

    async def create(
        self, project_id: uuid.UUID, data: ApiKeyCreate, caller: Caller
    ) -> tuple[ApiKey, str]:
        """Issue a key for a project. Returns the row and the key itself.

        This is the only time the key exists outside the caller's hands: the
        database keeps its hash, so a lost key is replaced, never recovered.
        """
        caller.require_admin()
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)
        key = generate_key()
        api_key = ApiKey(
            project_id=project_id,
            name=data.name,
            prefix=key[:DISPLAY_PREFIX_LENGTH],
            key_hash=hash_key(key),
        )
        self._session.add(api_key)
        await self._session.flush()
        await self._session.refresh(api_key)
        await self._session.commit()
        return api_key, key

    async def list_for_project(self, project_id: uuid.UUID, caller: Caller) -> Sequence[ApiKey]:
        """Every key a project has had, newest first, revoked ones included.

        Not paginated: a project holds a handful of keys, and a list that hid
        some would hide exactly the forgotten one worth revoking.
        """
        caller.require_admin()
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)
        result = await self._session.scalars(
            select(ApiKey)
            .where(ApiKey.project_id == project_id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        )
        return result.all()

    async def revoke(self, key_id: uuid.UUID, caller: Caller) -> ApiKey:
        """Stop a key working, from the next request on.

        Idempotent: revoking a revoked key keeps the first `revoked_at`, so the
        record of when it stopped working does not move.
        """
        caller.require_admin()
        api_key = await self._session.get(ApiKey, key_id, with_for_update=True)
        if api_key is None:
            raise NotFoundError("API key", key_id)
        if api_key.revoked_at is None:
            api_key.revoked_at = datetime.now(UTC)
            await self._session.flush()
            await self._session.refresh(api_key)
        await self._session.commit()
        return api_key

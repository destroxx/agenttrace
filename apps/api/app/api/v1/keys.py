"""API key endpoints. Every one needs the admin key.

Listing keys is admin-only too, although reads are otherwise public: which
keys exist and when they were used is not demo data, and a prefix list is
exactly what someone hunting for a leaked key would want.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.dependencies import ADMIN_RESPONSES, ApiKeyServiceDep, CallerDep
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse

router = APIRouter(tags=["keys"])


@router.post(
    "/projects/{project_id}/keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Issue an API key for a project",
    responses={
        **ADMIN_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "No such project."},
    },
)
async def create_key(
    project_id: uuid.UUID, payload: ApiKeyCreate, service: ApiKeyServiceDep, caller: CallerDep
) -> ApiKeyCreated:
    """Issue a key that can write to this project only.

    The response is the only place the key ever appears; store it then.
    """
    api_key, key = await service.create(project_id, payload, caller)
    return ApiKeyCreated(**ApiKeyResponse.model_validate(api_key).model_dump(), key=key)


@router.get(
    "/projects/{project_id}/keys",
    response_model=list[ApiKeyResponse],
    summary="List a project's API keys",
    responses={
        **ADMIN_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "No such project."},
    },
)
async def list_keys(
    project_id: uuid.UUID, service: ApiKeyServiceDep, caller: CallerDep
) -> list[ApiKeyResponse]:
    """Every key the project has had, newest first, by prefix; never the keys themselves."""
    keys = await service.list_for_project(project_id, caller)
    return [ApiKeyResponse.model_validate(api_key) for api_key in keys]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    responses={
        **ADMIN_RESPONSES,
        status.HTTP_404_NOT_FOUND: {"description": "No such key."},
    },
)
async def revoke_key(key_id: uuid.UUID, service: ApiKeyServiceDep, caller: CallerDep) -> Response:
    """Revoke a key. It fails with 401 from the next request on.

    The row is kept, marked revoked, so the list still shows it. Revoking a
    revoked key succeeds and changes nothing.
    """
    await service.revoke(key_id, caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

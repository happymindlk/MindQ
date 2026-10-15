"""Master Assessment Library endpoints (ops-authenticated)."""
from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.schemas.client_package import CustomQuestionIn
from app.schemas.library import (
    TemplateCreate,
    TemplateDetail,
    TemplateQuestionCreate,
    TemplateQuestionOut,
    TemplateQuestionUpdate,
    TemplateSummary,
    TemplateUpdate,
)
from app.services.library import (
    LibraryConflictError,
    LibraryError,
    LibraryService,
    ModuleLockedError,
)

router = APIRouter()


def _raise_http(exc: Exception) -> NoReturn:
    """Map library domain errors onto the standard API error shapes.

    ``MODULE_LOCKED`` carries a structured detail so the builder can offer
    "Clone as New Version" instead of a generic failure toast.

    Args:
        exc: Domain exception raised by ``LibraryService``.

    Raises:
        HTTPException: Always.
    """
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ModuleLockedError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": ModuleLockedError.code,
                "message": str(exc),
                "module_id": str(exc.module_id),
                "version": exc.version,
            },
        ) from exc
    if isinstance(exc, LibraryConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, LibraryError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("/templates", response_model=list[TemplateSummary])
async def list_templates(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """List Master Library templates (global_modules) with lifecycle metadata."""
    return await LibraryService.list_templates(db, include_inactive=include_archived)


@router.post("/templates", response_model=TemplateDetail, status_code=201)
async def create_template(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Create a new draft Master Library template."""
    try:
        return await LibraryService.create_template(db, body)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.get("/templates/{template_id}", response_model=TemplateDetail)
async def get_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Return a template with its active questions."""
    try:
        return await LibraryService.get_template(db, template_id)
    except LookupError as exc:
        _raise_http(exc)


@router.put("/templates/{template_id}", response_model=TemplateDetail)
async def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Update template metadata. Timing/shuffle edits return 409 MODULE_LOCKED when frozen."""
    try:
        return await LibraryService.update_template(db, template_id, body)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.post("/templates/{template_id}/publish", response_model=TemplateDetail)
async def publish_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Publish a draft module, making it immutable and available to packages."""
    try:
        return await LibraryService.publish_template(db, template_id)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.post(
    "/templates/{template_id}/clone-version",
    response_model=TemplateDetail,
    status_code=201,
)
async def clone_template_version(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Clone a (published) module into the next draft version on its lineage."""
    try:
        return await LibraryService.clone_version(db, template_id)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.post("/templates/{template_id}/archive", response_model=TemplateDetail)
async def archive_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Hide a module from new packages. Historical responses and scores are untouched."""
    try:
        return await LibraryService.archive_template(db, template_id)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.delete(
    "/templates/{template_id}",
    response_model=TemplateDetail,
    deprecated=True,
)
async def archive_template_legacy(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Deprecated alias of ``POST /templates/{id}/archive`` (soft archive, never a hard delete)."""
    try:
        return await LibraryService.archive_template(db, template_id)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.post(
    "/templates/{template_id}/questions",
    response_model=TemplateQuestionOut,
    status_code=201,
)
async def create_template_question(
    template_id: UUID,
    body: TemplateQuestionCreate,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Add a question to a draft Master Library template."""
    try:
        return await LibraryService.create_question(db, template_id, body)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.put(
    "/templates/{template_id}/questions/{question_id}",
    response_model=TemplateQuestionOut,
)
async def update_template_question(
    template_id: UUID,
    question_id: UUID,
    body: TemplateQuestionUpdate,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Update a question on a draft Master Library template."""
    try:
        return await LibraryService.update_question(db, template_id, question_id, body)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.delete(
    "/templates/{template_id}/questions/{question_id}",
    response_model=TemplateQuestionOut,
)
async def deactivate_template_question(
    template_id: UUID,
    question_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Soft-deactivate a question on a draft Master Library template."""
    try:
        return await LibraryService.deactivate_question(db, template_id, question_id)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)


@router.post(
    "/templates/{template_id}/sync-question",
    response_model=TemplateQuestionOut,
    status_code=201,
)
async def sync_question_to_master(
    template_id: UUID,
    body: CustomQuestionIn,
    db: AsyncSession = Depends(get_db),
    _: HRUserContext = Depends(get_current_ops_user),
):
    """Cherry-pick a package custom question into a draft Master Library template.

    Inserts into template_questions and rebuilds global_modules.questions.
    Does not mutate existing package snapshots.
    """
    try:
        return await LibraryService.sync_question(db, template_id, body)
    except (LookupError, LibraryError) as exc:
        _raise_http(exc)

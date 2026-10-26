"""Authenticated, server-rendered staff dashboard routes."""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from hmac import compare_digest
from typing import cast
from urllib.parse import parse_qs, urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import Environment
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.counselling_requests import (
    CounsellingRequestRepository,
)
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.counselling import CounsellingRequestStatus
from coaching_inquiry_engine.domain.exam_menu import ExamMenuFile
from coaching_inquiry_engine.domain.models import ContactChannel
from coaching_inquiry_engine.logging import mask_contact_text
from coaching_inquiry_engine.services.admin_auth import (
    AdminAuthRateLimiter,
    verify_admin_password,
)

router = APIRouter(prefix="/admin", tags=["admin"])
_BASIC = HTTPBasic(auto_error=False)
_HTML = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)

_LIST_TEMPLATE = _HTML.from_string(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Counselling requests</title>
<style>body{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17202a}table{border-collapse:collapse;width:100%;margin-top:1rem}th,td{text-align:left;padding:.65rem;border-bottom:1px solid #ccd1d1}label{margin-right:.75rem}input,select,button{font:inherit;padding:.35rem}nav{display:flex;gap:1rem;margin:1rem 0}</style></head>
<body><h1>Counselling requests</h1>
<form method="get" action="/admin/requests">
<label>Exam <select name="exam"><option value="">All exams</option>{% for exam in exams %}<option value="{{ exam.id }}" {% if exam.id == exam_filter %}selected{% endif %}>{{ exam.label }}</option>{% endfor %}</select></label>
<label>Status <select name="status"><option value="">All statuses</option>{% for value in statuses %}<option value="{{ value }}" {% if value == status_filter %}selected{% endif %}>{{ value }}</option>{% endfor %}</select></label>
<label>From <input type="date" name="date_from" value="{{ date_from or '' }}"></label>
<label>To <input type="date" name="date_to" value="{{ date_to or '' }}"></label>
<button type="submit">Filter</button></form>
<p>{{ total }} request(s)</p>
{% if items %}<table><thead><tr><th>Created</th><th>Name</th><th>Exam</th><th>Eligibility</th><th>Status</th><th>Assigned to</th></tr></thead><tbody>
{% for item in items %}<tr><td>{{ item.created_at.strftime('%Y-%m-%d %H:%M UTC') }}</td><td><a href="/admin/requests/{{ item.request_id }}">{{ item.first_name or 'Lead' }}</a></td><td>{{ exam_names.get(item.exam_id, item.exam_id or '—') }}</td><td>{{ item.eligibility_status or '—' }}</td><td>{{ item.status.value }}</td><td>{{ item.assigned_to or '—' }}</td></tr>{% endfor %}
</tbody></table>{% else %}<p>No requests match these filters.</p>{% endif %}
<nav>{% if previous_url %}<a href="{{ previous_url }}">Previous</a>{% endif %}<span>Page {{ page }}</span>{% if next_url %}<a href="{{ next_url }}">Next</a>{% endif %}</nav>
</body></html>"""
)

_DETAIL_TEMPLATE = _HTML.from_string(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Counselling request</title><style>body{font:16px system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#17202a}dt{font-weight:700;margin-top:.7rem}dd{margin-left:0}textarea{width:100%;max-width:50rem}label{display:block;margin:.7rem 0}input,select,button{font:inherit;padding:.35rem}</style></head>
<body><p><a href="/admin/requests">All requests</a></p><h1>Counselling request</h1>
<dl><dt>Request</dt><dd>{{ detail.request_id }}</dd><dt>Lead reference</dt><dd>{{ detail.lead_id }}</dd>
<dt>Name</dt><dd>{{ detail.name or '—' }}</dd><dt>Age</dt><dd>{{ detail.age or '—' }}</dd>
<dt>Highest qualification</dt><dd>{{ detail.qualification or '—' }}</dd><dt>Exam</dt><dd>{{ detail.exam or '—' }}</dd>
<dt>Eligibility</dt><dd>{{ detail.eligibility or '—' }}</dd><dt>Interests</dt><dd>{{ detail.interests or '—' }}</dd>
{% if detail.telegram_reference %}<dt>Telegram conversation reference</dt><dd>{{ detail.telegram_reference }}</dd>{% endif %}
<dt>Contact</dt><dd>{{ detail.contact or 'No phone or email provided' }}</dd></dl>
<h2>Consent history</h2>{% if consents %}<ul>{% for item in consents %}<li>{{ item.channel }} — {{ item.wording_version }} — granted {{ item.granted_at.strftime('%Y-%m-%d %H:%M UTC') }}{% if item.revoked_at %}; revoked {{ item.revoked_at.strftime('%Y-%m-%d %H:%M UTC') }}{% endif %}</li>{% endfor %}</ul>{% else %}<p>No consent record.</p>{% endif %}
<h2>Latest conversation messages</h2>{% if messages %}<ol>{% for message in messages %}<li><strong>{{ message.direction }}</strong> ({{ message.received_at.strftime('%Y-%m-%d %H:%M UTC') }}): {{ message.body }}</li>{% endfor %}</ol>{% else %}<p>No messages.</p>{% endif %}
<h2>Update request</h2><form method="post" action="/admin/requests/{{ detail.request_id }}/status" enctype="application/x-www-form-urlencoded">
<label>Status <select name="status">{% for value in statuses %}<option value="{{ value }}" {% if value == detail.status %}selected{% endif %}>{{ value }}</option>{% endfor %}</select></label>
<label>Assigned to <input name="assigned_to" maxlength="120" value="{{ detail.assigned_to or '' }}"></label>
<label>Notes <textarea name="notes" maxlength="1000" rows="5">{{ detail.notes or '' }}</textarea></label><button type="submit">Save changes</button></form>
</body></html>"""
)


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: CounsellingRequestStatus
    assigned_to: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("assigned_to")
    @classmethod
    def validate_assignment(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not all(character.isalnum() or character in "_.-" for character in value):
            raise ValueError("invalid assignment")
        return value

    @field_validator("notes")
    @classmethod
    def reject_contact_values(cls, value: str | None) -> str | None:
        if value is not None and mask_contact_text(value) != value:
            raise ValueError("notes must not contain contact information")
        return value or None


async def require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_BASIC),  # noqa: B008
) -> str:
    settings = cast(Settings, request.app.state.settings)
    address = request.client.host if request.client is not None else "unknown"
    limiter = cast(AdminAuthRateLimiter, request.app.state.admin_auth_limiter)
    if settings.app_env.casefold() == "production" and request.url.scheme != "https":
        raise HTTPException(status_code=400, detail="HTTPS required")
    if limiter.is_blocked(address):
        raise HTTPException(status_code=429, detail="Authentication unavailable")

    supplied_username = credentials.username if credentials is not None else ""
    supplied_password = credentials.password if credentials is not None else ""
    expected_username = settings.admin_username or ""
    encoded_hash = settings.admin_password_hash or ""
    username_ok = compare_digest(
        supplied_username.encode("utf-8"), expected_username.encode("utf-8")
    )
    password_ok = verify_admin_password(supplied_password, encoded_hash)
    if credentials is None or not (username_ok and password_ok):
        if limiter.record_failure(address):
            raise HTTPException(status_code=429, detail="Authentication unavailable")
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Basic"},
        )
    limiter.clear(address)
    return expected_username


@router.get("/requests", response_class=HTMLResponse)
async def list_requests(
    request: Request,
    staff: str = Depends(require_admin),
    exam: str | None = Query(default=None, max_length=100),
    status_filter: CounsellingRequestStatus | None = Query(  # noqa: B008
        default=None, alias="status"
    ),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1, le=100_000),
) -> HTMLResponse:
    _ = staff
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=400, detail="Invalid date range")
    exam_menu = cast(ExamMenuFile, request.app.state.exam_menu)
    exam_by_id = {
        item.exam_id: item.display_name
        for item in exam_menu.exams
        if item.status == "ACTIVE"
    }
    if exam is not None and exam not in exam_by_id:
        raise HTTPException(status_code=400, detail="Invalid exam filter")
    sessions = cast(
        async_sessionmaker[AsyncSession], request.app.state.admin_sessions
    )
    async with sessions() as session:
        items, total = await CounsellingRequestRepository(session).list_page(
            exam_id=exam,
            status=status_filter,
            date_from=date_from,
            date_to=date_to,
            page=page,
        )
    query: dict[str, str] = {}
    if exam:
        query["exam"] = exam
    if status_filter:
        query["status"] = status_filter.value
    if date_from:
        query["date_from"] = date_from.isoformat()
    if date_to:
        query["date_to"] = date_to.isoformat()
    previous_url = (
        "/admin/requests?" + urlencode({**query, "page": str(page - 1)})
        if page > 1
        else None
    )
    next_url = (
        "/admin/requests?" + urlencode({**query, "page": str(page + 1)})
        if page * 25 < total
        else None
    )
    return HTMLResponse(
        _LIST_TEMPLATE.render(
            items=items,
            total=total,
            page=page,
            exams=[{"id": key, "label": value} for key, value in exam_by_id.items()],
            exam_names=exam_by_id,
            exam_filter=exam,
            status_filter=status_filter.value if status_filter else None,
            statuses=[item.value for item in CounsellingRequestStatus],
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            previous_url=previous_url,
            next_url=next_url,
        )
    )


@router.get("/requests/{request_id}", response_class=HTMLResponse)
async def request_detail(
    request: Request,
    request_id: UUID,
    staff: str = Depends(require_admin),
) -> HTMLResponse:
    sessions = cast(
        async_sessionmaker[AsyncSession], request.app.state.admin_sessions
    )
    cipher = cast(ContactCipher, request.app.state.contact_cipher)
    async with sessions() as session:
        async with session.begin():
            repository = CounsellingRequestRepository(session)
            joined = await repository.get_with_lead(request_id)
            if joined is None:
                raise HTTPException(status_code=404, detail="Request not found")
            request_row, lead = joined
            contact = await LeadRepository(session, cipher).get_decrypted_contact_value(
                lead.id
            )
            consent_rows = await ConsentRepository(session).list_for_lead(lead.id)
            message_rows = await MessageRepository(session).list_recent(
                lead.id, limit=5
            )
            await AuditRepository(session).append_audit_event(
                lead_id=lead.id,
                event_type="admin_contact_detail_viewed",
                detail={
                    "staff_identity": staff,
                    "action": "contact_detail_viewed",
                    "request_id": str(request_row.id),
                },
            )
            exam_menu = cast(ExamMenuFile, request.app.state.exam_menu)
            exam_name = next(
                (
                    item.display_name
                    for item in exam_menu.exams
                    if item.exam_id == lead.exam_id
                ),
                lead.exam_id,
            )
            detail = {
                "request_id": request_row.id,
                "lead_id": lead.id,
                "name": lead.name,
                "age": lead.age_years,
                "qualification": lead.qualification,
                "exam": exam_name,
                "eligibility": lead.eligibility_status,
                "interests": ", ".join(
                    item
                    for item in (lead.goal, lead.target, lead.timeline)
                    if item
                ),
                "telegram_reference": (
                    lead.external_user_id
                    if lead.channel == ContactChannel.telegram.value
                    else None
                ),
                "contact": contact
                or (
                    "Telegram conversation"
                    if lead.channel == ContactChannel.telegram.value
                    else None
                ),
                "status": request_row.status,
                "assigned_to": request_row.assigned_to,
                "notes": request_row.notes,
            }
            messages = [
                {
                    "direction": row.direction,
                    "received_at": row.received_at,
                    "body": mask_contact_text(row.body),
                }
                for row in message_rows
            ]
    return HTMLResponse(
        _DETAIL_TEMPLATE.render(
            detail=detail,
            consents=consent_rows,
            messages=messages,
            statuses=[item.value for item in CounsellingRequestStatus],
        )
    )


@router.post("/requests/{request_id}/status")
async def update_request_status(
    request: Request,
    request_id: UUID,
    staff: str = Depends(require_admin),
) -> Response:
    payload = await _parse_status_update(request)
    if isinstance(payload, Response):
        return payload
    sessions = cast(
        async_sessionmaker[AsyncSession], request.app.state.admin_sessions
    )
    try:
        async with sessions() as session:
            async with session.begin():
                joined = await CounsellingRequestRepository(session).get_with_lead(
                    request_id
                )
                if joined is None:
                    raise HTTPException(status_code=404, detail="Request not found")
                request_row, lead = joined
                updated = await CounsellingRequestRepository(session).update(
                    request_id,
                    status=payload.status,
                    assigned_to=payload.assigned_to,
                    notes=payload.notes,
                    now=datetime.now(UTC),
                )
                if updated is None:
                    raise HTTPException(status_code=404, detail="Request not found")
                await AuditRepository(session).append_audit_event(
                    lead_id=lead.id,
                    event_type="admin_counselling_request_status_changed",
                    detail={
                        "staff_identity": staff,
                        "action": "status_changed",
                        "request_id": str(request_row.id),
                        "status": payload.status.value,
                    },
                )
                result = {
                    "request_id": str(updated.id),
                    "status": updated.status,
                    "assigned_to": updated.assigned_to,
                    "notes": mask_contact_text(updated.notes or "") or None,
                    "updated_at": updated.updated_at.isoformat(),
                }
    except IntegrityError:
        return JSONResponse(
            {"detail": "Request update conflicts with an existing open request"},
            status_code=409,
        )
    if request.headers.get("content-type", "").startswith(
        "application/x-www-form-urlencoded"
    ):
        return RedirectResponse(
            f"/admin/requests/{request_id}", status_code=303
        )
    return JSONResponse(result)


async def _parse_status_update(request: Request) -> StatusUpdate | Response:
    body = await request.body()
    if len(body) > 8192:
        return JSONResponse({"detail": "Invalid status update"}, status_code=413)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    try:
        if content_type == "application/json":
            raw: object = json.loads(body)
        elif content_type == "application/x-www-form-urlencoded":
            parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            raw = {key: values[-1] for key, values in parsed.items() if values}
        else:
            return JSONResponse(
                {"detail": "Unsupported status update format"}, status_code=415
            )
        return StatusUpdate.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        return JSONResponse({"detail": "Invalid status update"}, status_code=422)

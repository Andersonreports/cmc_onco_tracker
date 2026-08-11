
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import reports_client
from exome_roles import can_edit, forbidden, require_tracker_access, username_for

router = APIRouter(prefix="/exome-tracker/api", dependencies=[Depends(require_tracker_access)])

class ReportIn(BaseModel):
    sno: str = ""
    name: str = ""
    test: str = ""
    gen_id: str = ""
    and_id: str = ""
    client: str = ""
    tat: str = ""
    rep_exp: str = ""
    cnv_status: str = ""
    analyst: str = ""
    analyst_raw: str = ""
    assign_date: str = ""
    ana_date: str = ""
    pri_rev: str = ""
    final: str = ""
    remark: str = ""
    rel_date: str = ""
    history: str = ""
    bioinfo_time: str = ""
    last_updated_by: str = ""
    run_text: str = ""
    is_priority: bool = False
    is_reanalysis: bool = False


class BulkReleaseIn(BaseModel):
    ids: list[str]
    rel_date: str


class BulkRemarkIn(BaseModel):
    ids: list[str]
    remark: str


class BulkReviewerIn(BaseModel):
    ids: list[str]
    pri_rev: str


@router.get("/reports")
def list_reports(request: Request):
    return reports_client.list_reports()


def _stamped(report: ReportIn, request: Request) -> dict:
    payload = report.model_dump()
    payload["last_updated_by"] = payload.get("last_updated_by") or username_for(request)
    return payload


@router.post("/reports")
def create_report(report: ReportIn, request: Request):
    if not can_edit(request):
        return forbidden()
    return reports_client.create_report(_stamped(report, request))


@router.put("/reports/bulk-release")
def bulk_release(payload: BulkReleaseIn, request: Request):
    if not can_edit(request):
        return forbidden()
    rel_date = payload.rel_date.strip()
    if not rel_date:
        return JSONResponse({"error": "rel_date is required"}, status_code=400)
    if not payload.ids:
        return JSONResponse({"error": "No valid report ids provided"}, status_code=400)

    count = reports_client.bulk_release(payload.ids, rel_date)
    return {"ok": True, "count": count}


@router.put("/reports/bulk-remark")
def bulk_remark(payload: BulkRemarkIn, request: Request):
    if not can_edit(request):
        return forbidden()
    remark = payload.remark.strip()
    if not remark:
        return JSONResponse({"error": "remark is required"}, status_code=400)
    if not payload.ids:
        return JSONResponse({"error": "No valid report ids provided"}, status_code=400)

    count = reports_client.bulk_remark(payload.ids, remark)
    return {"ok": True, "count": count}


@router.put("/reports/bulk-reviewer")
def bulk_reviewer(payload: BulkReviewerIn, request: Request):
    """Allocation: hand a batch of samples to one reviewer in a single pass.

    The reviewer is what the tracker counts workload by, so this is also what
    moves the samples onto that person's plate.
    """
    if not can_edit(request):
        return forbidden()
    reviewer = payload.pri_rev.strip()
    if not reviewer:
        return JSONResponse({"error": "pri_rev is required"}, status_code=400)
    if not payload.ids:
        return JSONResponse({"error": "No valid report ids provided"}, status_code=400)

    count = reports_client.bulk_reviewer(payload.ids, reviewer)
    return {"ok": True, "count": count}


@router.put("/reports/{report_id}")
def update_report(
    report_id: str,
    report: ReportIn,
    request: Request,
):
    if not can_edit(request):
        return forbidden()
    doc = reports_client.update_report(report_id, _stamped(report, request))
    if doc is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return doc


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, request: Request):
    if not can_edit(request):
        return forbidden()
    reports_client.delete_report(report_id)
    return {"ok": True}


@router.post("/reports/bulk-add")
def bulk_add(reports: list[ReportIn], request: Request):
    if not can_edit(request):
        return forbidden()
    if not reports:
        return {"ok": True, "count": 0}
    count = reports_client.bulk_add([_stamped(r, request) for r in reports])
    return {"ok": True, "count": count}


from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import reports_client
from exome_roles import (can_edit, can_upload, forbidden, require_tracker_access,
                         username_for)

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
    remarks: str = ""
    report_release_date: str = ""
    history: str = ""
    bioinfo_time: str = ""
    last_updated_by: str = ""
    run_text: str = ""
    is_priority: bool = False
    is_reanalysis: bool = False
    visible: bool = True


class BulkReleaseIn(BaseModel):
    id: list[str]
    report_release_date: str


class BulkRemarkIn(BaseModel):
    id: list[str]
    remarks: str


class BulkReviewerIn(BaseModel):
    id: list[str]
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
    if not can_upload(request):
        return forbidden()
    return reports_client.create_report(_stamped(report, request))


@router.put("/reports/bulk-release")
def bulk_release(payload: BulkReleaseIn, request: Request):
    if not can_edit(request):
        return forbidden()
    report_release_date = payload.report_release_date.strip()
    if not report_release_date:
        return JSONResponse({"error": "report_release_date is required"}, status_code=400)
    if not payload.id:
        return JSONResponse({"error": "No valid report ids provided"}, status_code=400)

    count = reports_client.bulk_release(payload.id, report_release_date, username_for(request))
    return {"ok": True, "count": count}


@router.put("/reports/bulk-remarks")
def bulk_remarks(payload: BulkRemarkIn, request: Request):
    if not can_edit(request):
        return forbidden()
    remarks = payload.remarks.strip()
    if not remarks:
        return JSONResponse({"error": "remarks is required"}, status_code=400)
    if not payload.id:
        return JSONResponse({"error": "No valid report ids provided"}, status_code=400)

    count = reports_client.bulk_remarks(payload.id, remarks, username_for(request))
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
    if not payload.id:
        return JSONResponse({"error": "No valid report ids provided"}, status_code=400)

    count = reports_client.bulk_reviewer(payload.id, reviewer, username_for(request))
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
def delete_report(report_id: str):
    """No sample leaves the tracker from here.

    Cancelling used to hide a sample by clearing IT's visible flag, which is
    unrecoverable from this side — one stray click and a run's sample was gone
    from every list. A sample called off is recorded in its remarks instead,
    which keeps the row readable and its history intact.
    """
    return JSONResponse(
        {"error": "Samples cannot be deleted. Record the cancellation in the "
                  "sample's remarks instead."},
        status_code=405,
    )


@router.post("/reports/bulk-add")
def bulk_add(reports: list[ReportIn], request: Request):
    if not can_upload(request):
        return forbidden()
    if not reports:
        return {"ok": True, "count": 0}
    count = reports_client.bulk_add([_stamped(r, request) for r in reports])
    return {"ok": True, "count": count}

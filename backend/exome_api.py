
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import reports_client
from exome_roles import can_edit, forbidden, require_tracker_access

router = APIRouter(prefix="/exome-tracker/api", dependencies=[Depends(require_tracker_access)])

DEFAULT_RUN_NUMBER = 9999


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
    run_number: int = DEFAULT_RUN_NUMBER
    run_text: str = "—"
    is_hidden: bool = False
    is_priority: bool = False
    is_reanalysis: bool = False


class BulkReleaseIn(BaseModel):
    ids: list[str]
    rel_date: str


class BulkRemarkIn(BaseModel):
    ids: list[str]
    remark: str


@router.get("/reports")
def list_reports(request: Request):
    return reports_client.list_reports()


@router.post("/reports")
def create_report(report: ReportIn, request: Request):
    if not can_edit(request):
        return forbidden()
    return reports_client.create_report(report.model_dump())


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


@router.put("/reports/{report_id}")
def update_report(
    report_id: str,
    report: ReportIn,
    request: Request,
):
    if not can_edit(request):
        return forbidden()
    doc = reports_client.update_report(report_id, report.model_dump())
    if doc is None:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return doc


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, request: Request):
    if not can_edit(request):
        return forbidden()
    if not reports_client.delete_report(report_id):
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return {"ok": True}


@router.post("/reports/bulk-add")
def bulk_add(reports: list[ReportIn], request: Request):
    if not can_edit(request):
        return forbidden()
    if not reports:
        return {"ok": True, "count": 0}
    count = reports_client.bulk_add([r.model_dump() for r in reports])
    return {"ok": True, "count": count}

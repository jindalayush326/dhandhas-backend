from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth, companies, einvoice, gstin, hsn, import_export, members, reports, scan, sync, sync_ws, vouchers,
)
from app.api.v1.endpoints.masters import all_master_routers

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(companies.router)
api_router.include_router(members.router)
api_router.include_router(members.public_router)
api_router.include_router(import_export.router)
api_router.include_router(members.firm_router)
for r in all_master_routers:
    api_router.include_router(r)
api_router.include_router(vouchers.router)
api_router.include_router(reports.router)
api_router.include_router(gstin.router)
api_router.include_router(hsn.router)
api_router.include_router(einvoice.router)
api_router.include_router(scan.router)
api_router.include_router(sync.router)
api_router.include_router(sync_ws.router)
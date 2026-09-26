from fastapi import APIRouter, Depends

from app.providers.base import GSTProvider
from app.providers.factory import get_provider
from app.schemas.gstin import GSTINValidateResponse
from app.services.gstin_service import GSTINService

router = APIRouter(prefix="/gstin", tags=["GSTIN"])


def get_gstin_service(provider: GSTProvider = Depends(get_provider)) -> GSTINService:
    return GSTINService(provider)


@router.get("/{gstin}", response_model=GSTINValidateResponse)
async def validate_gstin(gstin: str, service: GSTINService = Depends(get_gstin_service)) -> GSTINValidateResponse:
    data = await service.validate_and_fetch(gstin)
    return GSTINValidateResponse(valid=True, data=data)

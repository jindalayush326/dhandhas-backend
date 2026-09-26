from fastapi import APIRouter, Depends

from app.providers.hsn_base import HSNProvider
from app.providers.hsn_factory import get_offline_hsn_provider
from app.schemas.hsn import HSNValidateResponse
from app.services.hsn_service import HSNService

router = APIRouter(prefix="/hsn", tags=["HSN"])


def get_hsn_service(provider: HSNProvider = Depends(get_offline_hsn_provider)) -> HSNService:
    return HSNService(provider)


@router.get("/{code}", response_model=HSNValidateResponse)
async def validate_hsn(code: str, service: HSNService = Depends(get_hsn_service)) -> HSNValidateResponse:
    data = await service.validate_and_fetch(code)
    return HSNValidateResponse(valid=True, data=data)

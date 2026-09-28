from security_auth import current_principal
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, status, Body

from schemas import (
    DemoExchangeVerifyRequest,
    DemoExchangeVerifyResponse,
    DemoAccountSummaryResponse,
)
from services.demo_exchange import (
    verify_demo_credentials_service,
    get_demo_account_summary_service,
)

router = APIRouter(prefix="/v1/exchange/demo", tags=["Demo Exchange"], dependencies=[Depends(current_principal)])


@router.post(
    "/verify",
    response_model=DemoExchangeVerifyResponse,
    status_code=status.HTTP_200_OK,
)
def verify_demo_exchange(
    request: Optional[DemoExchangeVerifyRequest] = Body(None),
):
    """
    Verify authenticated read access to the demo exchange environment.
    Exposes safe capability flags and verification status without leaking secret credentials.
    """
    try:
        return verify_demo_credentials_service(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential verification error: {str(e)}",
        )


@router.get(
    "/account-summary",
    response_model=DemoAccountSummaryResponse,
    status_code=status.HTTP_200_OK,
)
def get_demo_account_summary():
    """
    Fetch safe demo account summary information including balances and positions (if supported).
    """
    try:
        return get_demo_account_summary_service()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch demo account summary: {str(e)}",
        )

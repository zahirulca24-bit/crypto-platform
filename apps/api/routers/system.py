from security_auth import current_principal
from fastapi import Depends, APIRouter, Request

from services.system_capabilities import CapabilitiesService, SystemCapabilities, SystemReadiness

router = APIRouter(prefix="/v1/system", tags=["System"], dependencies=[Depends(current_principal)])


def _service(request: Request) -> CapabilitiesService:
    return CapabilitiesService(request.app.state.settings)


@router.get("/readiness", response_model=SystemReadiness)
def readiness(request: Request) -> SystemReadiness:
    return _service(request).readiness()


@router.get("/capabilities", response_model=SystemCapabilities)
def capabilities(request: Request) -> SystemCapabilities:
    return _service(request).capabilities()

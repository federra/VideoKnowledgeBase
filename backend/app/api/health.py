from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get('/health', response_model=HealthResponse, tags=['system'])
def health() -> HealthResponse:
    """API liveness only; does not claim database, Redis or worker readiness."""
    return HealthResponse(status='ok', service=settings.app_name, version='0.1.0')

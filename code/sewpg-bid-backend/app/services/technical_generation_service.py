from __future__ import annotations

from app.services.bid_generation_flow import BidGenerationService
from app.services.bid_project_service import technical_project_service


class TechnicalGenerationService(BidGenerationService):
    pass


technical_generation_service = TechnicalGenerationService(technical_project_service, "/api/technical/projects")

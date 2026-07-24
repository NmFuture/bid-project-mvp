from __future__ import annotations

from app.services.bid_generation_flow import BidGenerationService
from app.services.bid_project_service import business_project_service


class BusinessGenerationService(BidGenerationService):
    pass


business_generation_service = BusinessGenerationService(business_project_service, "/api/business/projects")

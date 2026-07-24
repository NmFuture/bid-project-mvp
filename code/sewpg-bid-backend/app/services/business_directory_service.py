from __future__ import annotations

from app.services.bid_directory_flow import BidDirectoryService
from app.services.bid_project_service import business_project_service


class BusinessDirectoryService(BidDirectoryService):
    pass


business_directory_service = BusinessDirectoryService(business_project_service, "/api/business/projects")

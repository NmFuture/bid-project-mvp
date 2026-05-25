from __future__ import annotations

from app.services.bid_directory_flow import BidDirectoryService
from app.services.bid_project_service import technical_project_service


class TechnicalDirectoryService(BidDirectoryService):
    pass


technical_directory_service = TechnicalDirectoryService(technical_project_service, "/api/technical/projects")

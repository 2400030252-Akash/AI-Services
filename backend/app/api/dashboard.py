"""
app/api/dashboard.py
====================
Dashboard API endpoints — mounts at /api/v1/dashboard.

All routes are protected by admin JWT authentication via ``Depends(get_current_admin)``.

Endpoints:
  GET /api/v1/dashboard/summary      — High-level call metrics summary
  GET /api/v1/dashboard/active-calls — List calls currently active with live duration
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.database.session import get_db
from app.models.admin_user import AdminUser
from app.schemas.dashboard import ActiveCallOut, DashboardSummaryOut
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "/summary",
    response_model=DashboardSummaryOut,
    status_code=status.HTTP_200_OK,
    summary="Get dashboard call metrics summary",
)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> DashboardSummaryOut:
    """
    Return high-level call metrics summary.

    Includes total call count, active call count, calls started today,
    and cumulative talk time in seconds.
    """
    service = DashboardService(db)
    return await service.get_summary()


@router.get(
    "/active-calls",
    response_model=list[ActiveCallOut],
    status_code=status.HTTP_200_OK,
    summary="Get currently active calls with live duration",
)
async def get_active_calls(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> list[ActiveCallOut]:
    """
    Return all calls currently in 'active' status along with their computed live duration in seconds.
    """
    service = DashboardService(db)
    return await service.get_active_calls()

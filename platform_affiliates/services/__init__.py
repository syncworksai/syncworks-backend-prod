from __future__ import annotations

from .attribution_service import assign_business_to_affiliate, get_client_ip
from .code_generator import generate_affiliate_code, normalize_affiliate_code
from .commission_service import record_syncworks_revenue_commission
from .metrics_service import get_affiliate_dashboard_metrics, get_godmode_overview_metrics
from .qr_service import build_qr_svg_placeholder, build_referral_link

__all__ = [
    "assign_business_to_affiliate",
    "get_client_ip",
    "generate_affiliate_code",
    "normalize_affiliate_code",
    "record_syncworks_revenue_commission",
    "get_affiliate_dashboard_metrics",
    "get_godmode_overview_metrics",
    "build_qr_svg_placeholder",
    "build_referral_link",
]
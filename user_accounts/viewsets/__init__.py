# backend/user_accounts/viewsets/__init__.py
"""
Optional convenience imports for viewsets.

IMPORTANT:
Do NOT hard-import Sales OS viewsets here, because any mismatch between
models/__init__.py exports and sales_os.py imports will crash Django startup
(and block migrations / showmigrations / manage.py commands).

Keep Sales OS imports inside try/except.
"""

from __future__ import annotations

# Core viewsets are usually imported directly from their modules in urls.py,
# so this file should be safe and minimal.

# ✅ Optional: expose Sales OS viewsets without breaking startup
try:
    from .sales_os import (  # noqa: F401
        SalesPipelineViewSet,
        SalesPipelineMemberViewSet,
        ProspectStageViewSet,
        ProspectViewSet,
        SalesKPIViewSet,
    )

    # Optional ones (only if present in your sales_os.py)
    try:
        from .sales_os import ProspectAttachmentViewSet  # noqa: F401
    except Exception:
        ProspectAttachmentViewSet = None  # type: ignore

    try:
        from .sales_os import ProspectActivityViewSet  # noqa: F401
    except Exception:
        ProspectActivityViewSet = None  # type: ignore

except Exception:
    # If Sales OS is mid-refactor, we never want it to block Django boot.
    SalesPipelineViewSet = None  # type: ignore
    SalesPipelineMemberViewSet = None  # type: ignore
    ProspectStageViewSet = None  # type: ignore
    ProspectViewSet = None  # type: ignore
    SalesKPIViewSet = None  # type: ignore
    ProspectAttachmentViewSet = None  # type: ignore
    ProspectActivityViewSet = None  # type: ignore
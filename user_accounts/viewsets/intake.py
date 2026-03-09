# user_accounts/viewsets/intake.py
from __future__ import annotations

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from user_accounts.service_taxonomy import (
    get_wizard_config,
    build_wizard_for,
)


class IntakeWizardConfigAPIView(APIView):
    """
    Returns the static wizard config:
    - LIFE_CATEGORIES
    - SUBTYPES
    - PRIORITY_LEVELS
    Frontend uses this to render the first slides (like "Home", "Rides", etc).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(get_wizard_config(), status=200)


class IntakeWizardStepsAPIView(APIView):
    """
    Returns the step list for a given life_category (and optional subtype).
    Example:
      /intake/wizard-steps/?life_category=home_property
      /intake/wizard-steps/?life_category=rides_transport&subtype=ride_airport
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        life_category = (request.query_params.get("life_category") or "").strip() or "other"
        subtype = (request.query_params.get("subtype") or "").strip() or None
        steps = build_wizard_for(life_category=life_category, subtype=subtype)
        return Response(
            {
                "life_category": life_category,
                "subtype": subtype,
                "steps": steps,
            },
            status=200,
        )

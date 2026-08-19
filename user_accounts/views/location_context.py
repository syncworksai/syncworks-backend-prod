from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from sync_ai.location_intelligence import reverse_geocode


class ReverseCurrentLocationAPIView(APIView):
    """Turn browser coordinates into a service-ready address without persisting them."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            latitude = float(request.data.get("latitude"))
            longitude = float(request.data.get("longitude"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Valid latitude and longitude are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return Response(
                {"detail": "Coordinates are outside valid ranges."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = reverse_geocode(latitude, longitude)
        result["persisted"] = False
        result["replaces_home"] = False
        http_status = status.HTTP_200_OK if result.get("available") else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(result, status=http_status)

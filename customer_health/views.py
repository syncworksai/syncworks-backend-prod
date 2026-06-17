from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CustomerHealthProfile
from .serializers import CustomerHealthProfileSerializer


class CustomerHealthMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request) -> CustomerHealthProfile:
        profile, _created = CustomerHealthProfile.objects.get_or_create(
            user=request.user
        )
        return profile

    def get(self, request):
        profile = self.get_object(request)
        serializer = CustomerHealthProfileSerializer(profile)
        return Response(serializer.data)

    def patch(self, request):
        profile = self.get_object(request)
        serializer = CustomerHealthProfileSerializer(
            profile,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
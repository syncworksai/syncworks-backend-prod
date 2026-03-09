from rest_framework.views import APIView
from rest_framework.response import Response
from user_accounts.serializers.users import MeSerializer


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)

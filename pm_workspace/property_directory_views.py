"""Owner-only portfolio property search for command-center jump navigation."""
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import PMProperty
from .views import _requested_workspace

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def quick_property_search(request):
    workspace=_requested_workspace(request)
    query=str(request.query_params.get("q") or "").strip()[:100]
    qs=PMProperty.objects.filter(workspace=workspace)
    if query:
        qs=qs.filter(Q(name__icontains=query)|Q(address__icontains=query)|
                     Q(city__icontains=query)|Q(zip__icontains=query))
    count=qs.count()
    matches=list(qs.order_by("name","id").values("id","name","address","city","state","status")[:8])
    return Response({"matches":matches,"total_matching":count,"is_truncated":count>len(matches)})

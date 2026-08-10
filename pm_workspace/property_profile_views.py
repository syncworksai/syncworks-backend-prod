from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .document_models import PMPropertyDocument
from .leasing_views import requested_workspace
from .models import PMProperty, PMUnit
from .property_profile_models import PMPropertyAsset, PMPropertyProfile


class PMPropertyProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMPropertyProfile
        fields = "__all__"
        read_only_fields = ("id", "property", "workspace", "updated_by", "created_at", "updated_at")


class PMPropertyAssetSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = PMPropertyAsset
        fields = "__all__"
        read_only_fields = ("id", "workspace", "property", "created_by", "created_at", "updated_at", "unit_label", "photo_url")

    def get_photo_url(self, obj):
        document = obj.photo_document
        if not document or not document.document:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(document.document.url) if request else document.document.url

    def validate(self, attrs):
        property_obj = self.context["property"]
        unit = attrs.get("unit")
        photo_document = attrs.get("photo_document")
        if unit and unit.property_id != property_obj.id:
            raise serializers.ValidationError({"unit": "Choose a unit from this property."})
        if photo_document and photo_document.property_id != property_obj.id:
            raise serializers.ValidationError({"photo_document": "Choose a photo from this property."})
        return attrs


def _property(request, property_id):
    workspace = requested_workspace(request)
    return workspace, PMProperty.objects.filter(workspace=workspace, pk=property_id).first()


def _profile_defaults(property_obj, workspace):
    units = PMUnit.objects.filter(workspace=workspace, property=property_obj)
    if units.count() == 1:
        unit = units.first()
        return {
            "bedrooms": unit.bedrooms,
            "bathrooms": unit.bathrooms,
            "square_feet": unit.square_feet,
        }
    return {}


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def property_profile(request, property_id):
    workspace, property_obj = _property(request, property_id)
    if not property_obj:
        return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)
    profile, _ = PMPropertyProfile.objects.get_or_create(
        workspace=workspace,
        property=property_obj,
        defaults=_profile_defaults(property_obj, workspace),
    )
    if request.method == "GET":
        return Response({"profile": PMPropertyProfileSerializer(profile).data})
    serializer = PMPropertyProfileSerializer(profile, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save(updated_by=request.user)
    return Response({"detail": "Property details saved.", "profile": serializer.data})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def property_inventory(request, property_id):
    workspace, property_obj = _property(request, property_id)
    if not property_obj:
        return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        qs = PMPropertyAsset.objects.filter(workspace=workspace, property=property_obj).select_related("unit", "photo_document")
        category = str(request.query_params.get("category") or "").upper()
        if category:
            qs = qs.filter(category=category)
        furnished = request.query_params.get("furnished")
        if furnished in {"1", "true", "True"}:
            qs = qs.filter(furnished_item=True)
        serializer = PMPropertyAssetSerializer(qs, many=True, context={"request": request, "property": property_obj})
        return Response({
            "items": serializer.data,
            "total": qs.count(),
            "furnished_items": qs.filter(furnished_item=True).count(),
            "needs_attention": qs.filter(condition__in=[PMPropertyAsset.Condition.POOR, PMPropertyAsset.Condition.NEEDS_REPAIR, PMPropertyAsset.Condition.MISSING]).count(),
        })
    serializer = PMPropertyAssetSerializer(data=request.data, context={"request": request, "property": property_obj})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(workspace=workspace, property=property_obj, created_by=request.user)
    return Response({"detail": "Property item added.", "item": PMPropertyAssetSerializer(item, context={"request": request, "property": property_obj}).data}, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def property_inventory_item(request, property_id, item_id):
    workspace, property_obj = _property(request, property_id)
    if not property_obj:
        return Response({"detail": "Property not found."}, status=status.HTTP_404_NOT_FOUND)
    item = PMPropertyAsset.objects.filter(workspace=workspace, property=property_obj, pk=item_id).select_related("unit", "photo_document").first()
    if not item:
        return Response({"detail": "Inventory item not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = PMPropertyAssetSerializer(item, data=request.data, partial=True, context={"request": request, "property": property_obj})
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return Response({"detail": "Property item updated.", "item": PMPropertyAssetSerializer(item, context={"request": request, "property": property_obj}).data})

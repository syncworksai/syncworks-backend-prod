from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .document_models import PMPropertyDocument
from .leasing_views import requested_workspace


DOCUMENT_CHECKLIST = [
    {"key": "management_agreement", "category": "MANAGEMENT_AGREEMENT", "label": "Property management agreement", "scope": "OWNER"},
    {"key": "ownership_packet", "category": "OWNERSHIP", "label": "Ownership / management change packet", "scope": "OWNER"},
    {"key": "lease", "category": "LEASE", "label": "Signed lease agreement", "scope": "TENANT"},
    {"key": "move_in_inspection", "category": "MOVE_IN_INSPECTION", "label": "Move-in inspection", "scope": "TENANT"},
    {"key": "security_deposit", "category": "SECURITY_DEPOSIT", "label": "Security deposit receipt or agreement", "scope": "TENANT"},
    {"key": "payment_arrangement", "category": "PAYMENT_ARRANGEMENT", "label": "Payment arrangement / late-fee agreement", "scope": "TENANT", "optional": True},
    {"key": "insurance", "category": "INSURANCE", "label": "Renter or property insurance", "scope": "TENANT", "optional": True},
    {"key": "section8_packet", "category": "SECTION8", "label": "Housing authority / Section 8 packet", "scope": "SECTION8", "conditional": True},
    {"key": "rent_increase", "category": "RENT_INCREASE", "label": "Housing-authority rent increase request", "scope": "SECTION8", "optional": True},
    {"key": "operating_statement", "category": "OPERATING_STATEMENT", "label": "Owner operating statement", "scope": "REPORTING", "optional": True},
]


class PMPropertyDocumentSerializer(serializers.ModelSerializer):
    document_url = serializers.SerializerMethodField()
    property_name = serializers.CharField(source="property.name", read_only=True)
    tenant_name = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="property_owner.name", read_only=True)

    class Meta:
        model = PMPropertyDocument
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at", "document_url", "property_name", "tenant_name", "owner_name")

    def get_document_url(self, obj):
        if not obj.document:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(obj.document.url) if request else obj.document.url

    def get_tenant_name(self, obj):
        return f"{obj.tenant.first_name} {obj.tenant.last_name}".strip() if obj.tenant else ""

    def validate(self, attrs):
        workspace = requested_workspace(self.context["request"])
        for field in ("property", "tenant", "lease", "property_owner"):
            value = attrs.get(field)
            if value and value.workspace_id != workspace.id:
                raise serializers.ValidationError({field: "This record is not in the selected portfolio."})
        if not attrs.get("document") and not attrs.get("source_url") and not getattr(self.instance, "document", None) and not getattr(self.instance, "source_url", ""):
            raise serializers.ValidationError("Upload a file or provide a source URL.")
        return attrs


class PMPropertyDocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMPropertyDocumentSerializer

    def get_queryset(self):
        workspace = requested_workspace(self.request)
        qs = PMPropertyDocument.objects.filter(workspace=workspace).select_related("property", "tenant", "lease", "property_owner")
        property_id = self.request.query_params.get("property_id")
        tenant_id = self.request.query_params.get("tenant_id")
        category = str(self.request.query_params.get("category") or "").upper()
        if property_id:
            qs = qs.filter(property_id=property_id)
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        if category:
            qs = qs.filter(category=category)
        return qs

    def perform_create(self, serializer):
        serializer.save(workspace=requested_workspace(self.request), created_by=self.request.user)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def property_document_checklist(request):
    workspace = requested_workspace(request)
    property_id = request.query_params.get("property_id")
    documents = PMPropertyDocument.objects.filter(workspace=workspace)
    if property_id:
        documents = documents.filter(property_id=property_id)
    categories = set(documents.exclude(status="ARCHIVED").values_list("category", flat=True))
    rows = [{**item, "complete": item["category"] in categories} for item in DOCUMENT_CHECKLIST]
    return Response({"items": rows, "complete": sum(1 for row in rows if row["complete"]), "total": len(rows)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_template_catalog(request):
    return Response({
        "templates": [
            {"key": "standard_lease", "category": "LEASE", "name": "Standard residential lease", "fields": ["tenant", "property", "term", "rent", "deposit", "late fees", "utilities", "signatures"]},
            {"key": "management_agreement", "category": "MANAGEMENT_AGREEMENT", "name": "Property management agreement", "fields": ["owner", "manager", "properties", "management fee", "repair approval limit", "term", "signatures"]},
            {"key": "mha_change_ownership", "category": "OWNERSHIP", "name": "MHA change of ownership / management", "fields": ["property", "owner", "manager", "tax ID", "HAP assignment", "direct deposit"]},
            {"key": "mha_rfta", "category": "SECTION8", "name": "MHA RFTA / program leasing packet", "fields": ["tenant", "unit", "proposed rent", "deposit", "utilities", "owner certifications"]},
            {"key": "mha_rent_increase", "category": "RENT_INCREASE", "name": "MHA rent increase request", "fields": ["current rent", "requested rent", "HAP anniversary", "amenities", "utilities", "signatures"]},
            {"key": "operating_statement", "category": "OPERATING_STATEMENT", "name": "Owner operating statement", "fields": ["date range", "income", "expenses", "management fees", "owner distributions", "net cash flow"]},
            {"key": "move_in_inspection", "category": "MOVE_IN_INSPECTION", "name": "Move-in inspection", "fields": ["rooms", "condition", "photos", "meters", "keys", "signatures"]},
            {"key": "security_deposit", "category": "SECURITY_DEPOSIT", "name": "Security deposit receipt / agreement", "fields": ["amount", "received date", "payment method", "held by", "applied balance", "signatures"]},
            {"key": "payment_arrangement", "category": "PAYMENT_ARRANGEMENT", "name": "Payment arrangement", "fields": ["balance", "installments", "dates", "late-fee treatment", "default terms", "signatures"]},
        ]
    })

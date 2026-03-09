# backend/user_accounts/viewsets/templates.py
from __future__ import annotations

from typing import Any, Dict

from django.template import Context, Engine, TemplateSyntaxError
from django.utils import timezone

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers

from user_accounts.models import DocumentTemplate, Business


def _get_active_business_from_request(request) -> Business | None:
    raw = (
        request.headers.get("X-Business-Id")
        or request.headers.get("x-business-id")
        or request.query_params.get("business_id")
        or ""
    )
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        biz_id = int(raw)
    except Exception:
        return None

    biz = Business.objects.filter(id=biz_id, is_active=True).first()
    if not biz:
        return None

    u = request.user
    if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
        return biz

    if getattr(biz, "owner_id", None) == getattr(u, "id", None):
        return biz

    # If you later want non-owners to access templates, you can expand this
    return None


class DocumentTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentTemplate
        fields = [
            "id",
            "business",
            "name",
            "template_type",
            "body",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "business", "created_at", "updated_at"]


class TemplateRenderSerializer(serializers.Serializer):
    """
    POST body: { "context": { ... } }
    """
    context = serializers.DictField(child=serializers.JSONField(), required=False)

    def validate_context(self, v):
        return v or {}


class DocumentTemplateViewSet(viewsets.ModelViewSet):
    """
    /api/v1/doc-templates/
    Business-scoped templates.

    ✅ Added:
      POST /api/v1/doc-templates/:id/render/
      Body: { "context": { "amount": "100.00", ... } }
    """
    serializer_class = DocumentTemplateSerializer
    permission_classes = [IsAuthenticated]
    queryset = DocumentTemplate.objects.all()

    def get_queryset(self):
        u = self.request.user
        qs = DocumentTemplate.objects.all().order_by("-updated_at", "-created_at")

        if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
            # allow platform view all if needed
            biz = _get_active_business_from_request(self.request)
            if biz:
                return qs.filter(business_id=biz.id)
            return qs

        biz = _get_active_business_from_request(self.request)
        if not biz:
            return qs.none()

        return qs.filter(business_id=biz.id)

    def perform_create(self, serializer):
        biz = _get_active_business_from_request(self.request)
        if not biz:
            raise serializers.ValidationError({"detail": "X-Business-Id required."})
        serializer.save(business=biz, created_at=timezone.now())

    @action(detail=True, methods=["post"], url_path="render")
    def render_template(self, request, pk=None):
        """
        Render template.body using Django template syntax with provided context.

        Example template: "Taxi ride / trip fee: {{amount}}"
        POST: { "context": {"amount": "75.00"} }
        """
        tpl: DocumentTemplate = self.get_object()

        # Enforce business ownership
        biz = _get_active_business_from_request(request)
        u = request.user
        if not (getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False)):
            if not biz or tpl.business_id != biz.id:
                return Response({"detail": "Not allowed."}, status=403)
        else:
            # even admins: if header present, ensure it matches
            if biz and tpl.business_id != biz.id:
                return Response({"detail": "Template not in active business."}, status=403)

        ser = TemplateRenderSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        ctx: Dict[str, Any] = ser.validated_data.get("context") or {}

        # Render using a minimal Engine (no filesystem loaders needed)
        engine = Engine(
            debug=False,
            autoescape=False,  # template bodies are text; keep simple
        )
        try:
            compiled = engine.from_string(tpl.body or "")
            rendered = compiled.render(Context(ctx))
        except TemplateSyntaxError as e:
            return Response({"detail": "Template syntax error", "error": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": "Render failed", "error": str(e)}, status=400)

        return Response(
            {
                "template_id": tpl.id,
                "template_name": tpl.name,
                "template_type": tpl.template_type,
                "rendered": rendered,
                "context_used": ctx,
            }
        )

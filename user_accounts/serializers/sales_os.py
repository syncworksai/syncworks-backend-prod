# backend/user_accounts/serializers/sales_os.py
from __future__ import annotations

from django.apps import apps
from rest_framework import serializers


def _get_model(model_name: str):
    """
    Safely load a model by name without hard imports.
    Prevents startup crashes when class names change during iteration.
    """
    try:
        return apps.get_model("user_accounts", model_name)
    except Exception:
        return None


SalesPipeline = _get_model("SalesPipeline")
SalesPipelineStage = _get_model("SalesPipelineStage")
SalesProspect = _get_model("SalesProspect")
SalesEvent = _get_model("SalesEvent")
SalesPipelineMember = _get_model("SalesPipelineMember")

# Optional / may not exist in your schema yet
SalesProspectAttachment = (
    _get_model("SalesProspectAttachment")
    or _get_model("ProspectAttachment")
    or _get_model("SalesAttachment")
)


class SalesPipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesPipeline
        fields = "__all__"


class ProspectStageSerializer(serializers.ModelSerializer):
    """
    IMPORTANT FIX:
    DO NOT do: pipeline_id = serializers.IntegerField(source="pipeline_id")
    That triggers DRF assertion (redundant source).
    We accept pipeline_id as write-only and map it to pipeline FK ourselves.
    """
    pipeline_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = SalesPipelineStage
        fields = "__all__"

    def validate(self, attrs):
        if SalesPipeline is None or SalesPipelineStage is None:
            raise serializers.ValidationError("Sales OS models not available.")
        pipeline_id = attrs.pop("pipeline_id", None)
        if pipeline_id is not None:
            pipeline = SalesPipeline.objects.filter(id=pipeline_id).first()
            if not pipeline:
                raise serializers.ValidationError({"pipeline_id": "Invalid pipeline_id."})
            attrs["pipeline"] = pipeline
        return attrs


class ProspectSerializer(serializers.ModelSerializer):
    pipeline_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = SalesProspect
        fields = "__all__"

    def validate(self, attrs):
        if SalesPipeline is None or SalesProspect is None:
            raise serializers.ValidationError("Sales OS models not available.")
        pipeline_id = attrs.pop("pipeline_id", None)
        if pipeline_id is not None:
            pipeline = SalesPipeline.objects.filter(id=pipeline_id).first()
            if not pipeline:
                raise serializers.ValidationError({"pipeline_id": "Invalid pipeline_id."})
            attrs["pipeline"] = pipeline
        return attrs


class SalesEventSerializer(serializers.ModelSerializer):
    pipeline_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = SalesEvent
        fields = "__all__"

    def validate(self, attrs):
        if SalesPipeline is None or SalesEvent is None:
            raise serializers.ValidationError("Sales OS models not available.")
        pipeline_id = attrs.pop("pipeline_id", None)
        if pipeline_id is not None:
            pipeline = SalesPipeline.objects.filter(id=pipeline_id).first()
            if not pipeline:
                raise serializers.ValidationError({"pipeline_id": "Invalid pipeline_id."})
            attrs["pipeline"] = pipeline
        return attrs


class SalesPipelineMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesPipelineMember
        fields = "__all__"


# ✅ MUST EXIST because your viewsets import it.
# If the attachment model isn't created yet, we still don't crash server startup.
if SalesProspectAttachment is not None:

    class ProspectAttachmentSerializer(serializers.ModelSerializer):
        class Meta:
            model = SalesProspectAttachment
            fields = "__all__"

else:

    class ProspectAttachmentSerializer(serializers.Serializer):
        """
        Placeholder to prevent ImportError during boot.
        If/when you add the attachment model, this will auto-upgrade to ModelSerializer above.
        """

        def to_representation(self, instance):
            return {"detail": "Attachments not enabled (model missing)."}

        def create(self, validated_data):
            raise serializers.ValidationError("Attachments not enabled (model missing).")

        def update(self, instance, validated_data):
            raise serializers.ValidationError("Attachments not enabled (model missing).")
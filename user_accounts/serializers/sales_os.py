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


# ✅ Canonical model names from your current codebase
SalesPipeline = _get_model("SalesPipeline")
ProspectStage = _get_model("ProspectStage")
Prospect = _get_model("Prospect")
SalesEvent = _get_model("SalesEvent")
SalesPipelineMember = _get_model("SalesPipelineMember")

# Optional / may not exist in your schema yet
ProspectAttachment = (
    _get_model("ProspectAttachment")
    or _get_model("SalesProspectAttachment")
    or _get_model("SalesAttachment")
)


class SalesPipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesPipeline
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]


class ProspectStageSerializer(serializers.ModelSerializer):
    """
    Accept pipeline_id from the frontend and map it to pipeline FK.
    """
    pipeline_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = ProspectStage
        fields = "__all__"

    def validate(self, attrs):
        if SalesPipeline is None or ProspectStage is None:
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
        model = Prospect
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if SalesPipeline is None or Prospect is None:
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
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

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
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


if ProspectAttachment is not None:

    class ProspectAttachmentSerializer(serializers.ModelSerializer):
        class Meta:
            model = ProspectAttachment
            fields = "__all__"
            read_only_fields = [
                "id",
                "uploaded_by",
                "created_at",
                "updated_at",
            ]

else:

    class ProspectAttachmentSerializer(serializers.Serializer):
        """
        Placeholder to prevent ImportError during boot.
        """

        def to_representation(self, instance):
            return {"detail": "Attachments not enabled (model missing)."}

        def create(self, validated_data):
            raise serializers.ValidationError("Attachments not enabled (model missing).")

        def update(self, instance, validated_data):
            raise serializers.ValidationError("Attachments not enabled (model missing).")
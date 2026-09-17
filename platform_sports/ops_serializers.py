from rest_framework import serializers

from .ops_models import (
    SoftballStatLedgerEntry,
    SportsPlayerProfile,
    TeamFee,
    TeamFeeAssignment,
    TeamPaymentSettings,
)
from .serializers import SportsPlayerSerializer


class SportsPlayerProfileSerializer(serializers.ModelSerializer):
    player_detail = SportsPlayerSerializer(source="player", read_only=True)
    profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = SportsPlayerProfile
        fields = (
            "id", "player", "player_detail", "email", "phone", "profile_photo",
            "profile_photo_url", "emergency_contact_name", "emergency_contact_phone",
            "notes", "created_at", "updated_at",
        )
        read_only_fields = ("id", "profile_photo_url", "created_at", "updated_at")
        extra_kwargs = {"profile_photo": {"write_only": True, "required": False}}

    def get_profile_photo_url(self, obj):
        if not obj.profile_photo:
            return ""
        request = self.context.get("request")
        url = obj.profile_photo.url
        return request.build_absolute_uri(url) if request else url


class TeamPaymentSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamPaymentSettings
        fields = (
            "id", "team", "cash_app_url", "venmo_url", "stripe_url", "payment_note",
            "platform_fee_bps", "free_mode", "created_at", "updated_at",
        )
        read_only_fields = ("id", "platform_fee_bps", "free_mode", "created_at", "updated_at")


class TeamFeeSerializer(serializers.ModelSerializer):
    assignment_count = serializers.IntegerField(source="assignments.count", read_only=True)

    class Meta:
        model = TeamFee
        fields = (
            "id", "team", "title", "description", "amount_cents", "due_date", "is_active",
            "assignment_count", "created_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "assignment_count", "created_by", "created_at", "updated_at")


class TeamFeeAssignmentSerializer(serializers.ModelSerializer):
    player_detail = SportsPlayerSerializer(source="player", read_only=True)
    fee_detail = TeamFeeSerializer(source="fee", read_only=True)

    class Meta:
        model = TeamFeeAssignment
        fields = (
            "id", "fee", "fee_detail", "player", "player_detail", "amount_cents",
            "amount_paid_cents", "status", "paid_at", "payment_method", "note",
            "updated_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "paid_at", "updated_by", "created_at", "updated_at")


class SoftballStatLedgerEntrySerializer(serializers.ModelSerializer):
    player_detail = SportsPlayerSerializer(source="player", read_only=True)

    class Meta:
        model = SoftballStatLedgerEntry
        fields = (
            "id", "team", "player", "player_detail", "season_name", "scope", "games",
            "pa", "ab", "hits", "doubles", "triples", "home_runs", "walks", "sac_flies",
            "rbi", "runs", "source", "note", "created_by", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        team = attrs.get("team", getattr(self.instance, "team", None))
        player = attrs.get("player", getattr(self.instance, "player", None))
        if team and player and player.team_id != team.id:
            raise serializers.ValidationError({"player": "Player must belong to this team."})
        hits = int(attrs.get("hits", getattr(self.instance, "hits", 0)) or 0)
        at_bats = int(attrs.get("ab", getattr(self.instance, "ab", 0)) or 0)
        doubles = int(attrs.get("doubles", getattr(self.instance, "doubles", 0)) or 0)
        triples = int(attrs.get("triples", getattr(self.instance, "triples", 0)) or 0)
        home_runs = int(attrs.get("home_runs", getattr(self.instance, "home_runs", 0)) or 0)
        if hits > at_bats:
            raise serializers.ValidationError({"hits": "Hits cannot exceed at-bats."})
        if doubles + triples + home_runs > hits:
            raise serializers.ValidationError({"hits": "Extra-base hits cannot exceed total hits."})
        return attrs

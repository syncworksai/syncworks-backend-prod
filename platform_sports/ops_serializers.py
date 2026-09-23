import base64
from io import BytesIO
from datetime import date

from PIL import Image, ImageOps, UnidentifiedImageError
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
    clear_photo = serializers.BooleanField(write_only=True, required=False, default=False)
    age = serializers.SerializerMethodField()

    class Meta:
        model = SportsPlayerProfile
        fields = (
            "id", "player", "player_detail", "email", "phone", "birth_date", "age", "show_age", "profile_photo",
            "profile_photo_url", "card_style", "card_nickname", "card_photo_position",
            "clear_photo", "emergency_contact_name", "emergency_contact_phone",
            "notes", "created_at", "updated_at",
        )
        read_only_fields = ("id", "age", "profile_photo_url", "created_at", "updated_at")
        extra_kwargs = {"profile_photo": {"write_only": True, "required": False}}

    def validate_birth_date(self, value):
        if value is not None and (value > date.today() or value.year < 1900):
            raise serializers.ValidationError("Enter a valid birth date.")
        return value

    def get_age(self, obj):
        if not obj.birth_date:
            return None
        today = date.today()
        return today.year - obj.birth_date.year - ((today.month, today.day) < (obj.birth_date.month, obj.birth_date.day))

    def get_profile_photo_url(self, obj):
        # DB-backed thumbnail survives Render rolling deploys and works even
        # when the app authenticates via an Authorization header instead of cookies.
        if obj.card_photo_data:
            data = bytes(obj.card_photo_data)
            return "data:" + (obj.card_photo_mime or "image/jpeg") + ";base64," + base64.b64encode(data).decode("ascii")
        if obj.profile_photo:
            request = self.context.get("request")
            url = obj.profile_photo.url
            return request.build_absolute_uri(url) if request else url
        return ""

    def validate_card_photo_position(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("Photo position must be from 0 to 100.")
        return value

    @staticmethod
    def _durable_photo(upload):
        if upload.size > 8 * 1024 * 1024:
            raise serializers.ValidationError({"profile_photo": "Choose an image under 8 MB."})
        try:
            upload.seek(0)
            image = Image.open(upload)
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode != "RGB":
                background = Image.new("RGB", image.size, (12, 20, 35))
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            image.thumbnail((820, 820))
            output = BytesIO()
            image.save(output, "JPEG", quality=80, optimize=True)
            if output.tell() > 450 * 1024:
                output = BytesIO()
                image.thumbnail((600, 600))
                image.save(output, "JPEG", quality=72, optimize=True)
            return output.getvalue()
        except (OSError, ValueError, UnidentifiedImageError):
            raise serializers.ValidationError({"profile_photo": "Upload a valid photo (JPEG, PNG or HEIC converted by your phone)."})

    def _save(self, validated_data, *, instance=None):
        photo = validated_data.pop("profile_photo", None)
        clear = validated_data.pop("clear_photo", False)
        if photo and clear:
            raise serializers.ValidationError({"profile_photo": "Choose either a new photo or Remove photo."})
        image_bytes = self._durable_photo(photo) if photo else None
        saved = super().create(validated_data) if instance is None else super().update(instance, validated_data)
        if image_bytes is not None:
            saved.card_photo_data = image_bytes
            saved.card_photo_mime = "image/jpeg"
            saved.save(update_fields=("card_photo_data", "card_photo_mime", "updated_at"))
        elif clear:
            saved.card_photo_data = None
            saved.card_photo_mime = ""
            if saved.profile_photo:
                saved.profile_photo = None
            saved.save(update_fields=("card_photo_data", "card_photo_mime", "profile_photo", "updated_at"))
        return saved

    def create(self, validated_data):
        return self._save(validated_data)

    def update(self, instance, validated_data):
        return self._save(validated_data, instance=instance)


    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and instance.player.user_id == getattr(request.user, "id", None):
            from platform_social.models import GroupMembership
            manager = GroupMembership.objects.filter(
                group_id=instance.player.team.group_id,
                user=request.user,
                status=GroupMembership.Status.ACTIVE,
                role__in=(
                    GroupMembership.Role.OWNER,
                    GroupMembership.Role.DIRECTOR,
                    GroupMembership.Role.MANAGER,
                ),
            ).exists()
            if not manager:
                data.pop("notes", None)
        return data


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

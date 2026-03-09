# backend/user_accounts/serializers/pm_section8.py
from __future__ import annotations

from rest_framework import serializers

from user_accounts.models.pm_section8 import PMSection8Case


# ✅ Your standard "packet checklist" template (matches the spreadsheet vibe)
# Add/remove keys as your SOP evolves.
REQUIRED_PACKET_KEYS: list[str] = [
    "w9",
    "voided_check",
    "direct_deposit_auth",
    "dl",  # driver's license
    "ss_card",  # social security card
    "lease_addendum",
    "landlord_certification",
    "tax_assessment",
]


def _normalize_packet(packet_items: dict | None) -> dict:
    """
    Ensures all required keys exist. Missing keys become False.
    Ignores non-bool values by casting to bool.
    """
    src = packet_items if isinstance(packet_items, dict) else {}
    out = {}
    for k in REQUIRED_PACKET_KEYS:
        out[k] = bool(src.get(k, False))
    # Preserve any extra keys user may add in the future
    for k, v in src.items():
        if k not in out:
            out[k] = bool(v)
    return out


def _packet_progress(packet_items: dict | None) -> int:
    items = _normalize_packet(packet_items)
    keys = [k for k in REQUIRED_PACKET_KEYS]  # progress only counts required keys
    if not keys:
        return 0
    done = sum(1 for k in keys if bool(items.get(k)))
    return int(round((done / len(keys)) * 100))


def _packet_missing(packet_items: dict | None) -> list[str]:
    items = _normalize_packet(packet_items)
    missing = [k for k in REQUIRED_PACKET_KEYS if not bool(items.get(k))]
    return missing


class PMSection8CaseSerializer(serializers.ModelSerializer):
    property_label = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(read_only=True)
    tenant_label = serializers.CharField(read_only=True)

    packet_progress_pct = serializers.SerializerMethodField()
    packet_missing_keys = serializers.SerializerMethodField()

    class Meta:
        model = PMSection8Case
        fields = [
            "id",
            "business",
            "property",
            "unit",
            "tenant",
            "status",
            "housing_authority_name",
            "housing_authority_phone",
            "housing_authority_email",
            "caseworker_name",
            "caseworker_phone",
            "caseworker_email",
            "voucher_number",
            "hap_contract_number",
            "hap_start_date",
            "hap_end_date",
            "recert_due_date",
            "recert_submitted_date",
            "recert_approved_date",
            "inspection_status",
            "inspection_scheduled_date",
            "inspection_completed_date",
            "inspection_fail_reasons",
            "contract_rent",
            "tenant_portion",
            "subsidy_portion",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
            "property_label",
            "unit_label",
            "tenant_label",
            # ✅ DB fields
            "packet_items",
            "packet_ready",
            "packet_last_reviewed_at",
            # ✅ computed helpers
            "packet_progress_pct",
            "packet_missing_keys",
        ]
        read_only_fields = [
            "id",
            "business",
            "created_by",
            "created_at",
            "updated_at",
            "property_label",
            "unit_label",
            "tenant_label",
            "packet_progress_pct",
            "packet_missing_keys",
        ]

    def validate_packet_items(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("packet_items must be a JSON object.")
        # normalize values to booleans
        normalized = {str(k): bool(v) for k, v in value.items()}
        # ensure required keys exist
        return _normalize_packet(normalized)

    def get_packet_progress_pct(self, obj):
        return _packet_progress(getattr(obj, "packet_items", None))

    def get_packet_missing_keys(self, obj):
        return _packet_missing(getattr(obj, "packet_items", None))

from datetime import date

from rest_framework import serializers

from .models import HealthAthleteProfile


def calculate_age(date_of_birth):
    if not date_of_birth:
        return 0
    today = date.today()
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


def resolve_age_group(age):
    if not age:
        return HealthAthleteProfile.AgeGroup.UNKNOWN
    if age < 13:
        return HealthAthleteProfile.AgeGroup.CHILD
    if age < 18:
        return HealthAthleteProfile.AgeGroup.TEEN
    if age < 30:
        return HealthAthleteProfile.AgeGroup.YOUNG_ADULT
    if age < 50:
        return HealthAthleteProfile.AgeGroup.ADULT
    if age < 65:
        return HealthAthleteProfile.AgeGroup.MASTERS
    return HealthAthleteProfile.AgeGroup.OLDER_ADULT


class HealthAthleteProfileSerializer(serializers.ModelSerializer):
    age = serializers.SerializerMethodField()

    class Meta:
        model = HealthAthleteProfile
        fields = (
            "id", "date_of_birth", "age", "age_group", "primary_sport",
            "training_experience", "measurements", "plan_preferences",
            "simulation_preferences", "requires_plan_review", "profile_version",
            "last_plan_reset_at", "last_plan_restart_at", "updated_at", "created_at",
        )
        read_only_fields = (
            "id", "age", "age_group", "profile_version", "last_plan_reset_at",
            "last_plan_restart_at", "updated_at", "created_at",
        )

    def get_age(self, obj):
        return calculate_age(obj.date_of_birth)

    def validate_measurements(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Measurements must be an object.")
        allowed = {
            "height", "heightUnit", "height_unit", "weight", "weightUnit",
            "weight_unit", "waist", "hips", "chest", "arm", "thigh",
            "measurementUnit", "measurement_unit",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise serializers.ValidationError(
                f"Unsupported measurement fields: {', '.join(unknown)}"
            )
        return value

    def update(self, instance, validated_data):
        dob = validated_data.get("date_of_birth", instance.date_of_birth)
        instance.age_group = resolve_age_group(calculate_age(dob))
        instance.profile_version += 1
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        return instance

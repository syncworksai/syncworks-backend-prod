from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.customer_settings import CustomerSettings

from .models import CustomerHealthProfile
from .serializers import (
    CustomerHealthProfileSerializer,
    RedeemHealthAccessCodeSerializer,
)

logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

NUTRITION_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "meal_name": {
            "type": "string",
        },
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "source_type": {
            "type": "string",
            "enum": [
                "restaurant",
                "homemade",
                "packaged",
                "unknown",
            ],
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "type": "string",
                    },
                    "quantity": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "serving_description": {
                        "type": "string",
                    },
                    "calories": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "protein": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "carbs": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "fat": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "fiber": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "sugar": {
                        "type": "number",
                        "minimum": 0,
                    },
                },
                "required": [
                    "name",
                    "quantity",
                    "serving_description",
                    "calories",
                    "protein",
                    "carbs",
                    "fat",
                    "fiber",
                    "sugar",
                ],
            },
        },
        "totals": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "calories": {
                    "type": "number",
                    "minimum": 0,
                },
                "protein": {
                    "type": "number",
                    "minimum": 0,
                },
                "carbs": {
                    "type": "number",
                    "minimum": 0,
                },
                "fat": {
                    "type": "number",
                    "minimum": 0,
                },
                "fiber": {
                    "type": "number",
                    "minimum": 0,
                },
                "sugar": {
                    "type": "number",
                    "minimum": 0,
                },
            },
            "required": [
                "calories",
                "protein",
                "carbs",
                "fat",
                "fiber",
                "sugar",
            ],
        },
        "assumptions": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "warnings": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "meal_name",
        "confidence",
        "source_type",
        "items",
        "totals",
        "assumptions",
        "warnings",
    ],
}


def _configured_health_access_code() -> str:
    return str(
        getattr(
            settings,
            "HEALTH_LIFETIME_ACCESS_CODE",
            "SWFIT26",
        )
        or "SWFIT26"
    ).strip().upper()


def _openai_api_key() -> str:
    return str(
        getattr(settings, "OPENAI_API_KEY", "")
        or ""
    ).strip()


def _nutrition_model() -> str:
    return str(
        getattr(
            settings,
            "OPENAI_NUTRITION_MODEL",
            "gpt-4.1-mini",
        )
        or "gpt-4.1-mini"
    ).strip()


def _extract_response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")

    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    for output_item in payload.get("output") or []:
        if not isinstance(output_item, dict):
            continue

        for content_item in output_item.get("content") or []:
            if not isinstance(content_item, dict):
                continue

            text = content_item.get("text")

            if isinstance(text, str) and text.strip():
                return text.strip()

    return ""


def _normalize_number(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, round(parsed, 2))


def _normalize_analysis(
    analysis: dict[str, Any],
) -> dict[str, Any]:
    items = []

    for raw_item in analysis.get("items") or []:
        if not isinstance(raw_item, dict):
            continue

        items.append(
            {
                "name": str(
                    raw_item.get("name") or "Food item"
                ).strip(),
                "quantity": _normalize_number(
                    raw_item.get("quantity")
                ),
                "serving_description": str(
                    raw_item.get("serving_description")
                    or ""
                ).strip(),
                "calories": _normalize_number(
                    raw_item.get("calories")
                ),
                "protein": _normalize_number(
                    raw_item.get("protein")
                ),
                "carbs": _normalize_number(
                    raw_item.get("carbs")
                ),
                "fat": _normalize_number(
                    raw_item.get("fat")
                ),
                "fiber": _normalize_number(
                    raw_item.get("fiber")
                ),
                "sugar": _normalize_number(
                    raw_item.get("sugar")
                ),
            }
        )

    totals = analysis.get("totals") or {}

    return {
        "meal_name": str(
            analysis.get("meal_name")
            or "Nutrition estimate"
        ).strip(),
        "confidence": str(
            analysis.get("confidence") or "low"
        ).strip().lower(),
        "source_type": str(
            analysis.get("source_type") or "unknown"
        ).strip().lower(),
        "items": items,
        "totals": {
            "calories": _normalize_number(
                totals.get("calories")
            ),
            "protein": _normalize_number(
                totals.get("protein")
            ),
            "carbs": _normalize_number(
                totals.get("carbs")
            ),
            "fat": _normalize_number(
                totals.get("fat")
            ),
            "fiber": _normalize_number(
                totals.get("fiber")
            ),
            "sugar": _normalize_number(
                totals.get("sugar")
            ),
        },
        "assumptions": [
            str(item).strip()
            for item in analysis.get("assumptions") or []
            if str(item).strip()
        ],
        "warnings": [
            str(item).strip()
            for item in analysis.get("warnings") or []
            if str(item).strip()
        ],
    }


class CustomerHealthMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request) -> CustomerHealthProfile:
        profile, _created = (
            CustomerHealthProfile.objects.get_or_create(
                user=request.user
            )
        )
        return profile

    def get(self, request):
        profile = self.get_object(request)
        serializer = CustomerHealthProfileSerializer(profile)
        return Response(serializer.data)

    def patch(self, request):
        profile = self.get_object(request)

        serializer = CustomerHealthProfileSerializer(
            profile,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


class NutritionAnalyzeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        description = str(
            request.data.get("description") or ""
        ).strip()

        meal_type = str(
            request.data.get("meal_type") or ""
        ).strip()

        restaurant = str(
            request.data.get("restaurant") or ""
        ).strip()

        if not description:
            return Response(
                {
                    "detail": (
                        "Describe the meal before requesting "
                        "a nutrition estimate."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(description) > 2000:
            return Response(
                {
                    "detail": (
                        "Meal descriptions must be "
                        "2,000 characters or fewer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        api_key = _openai_api_key()

        if not api_key:
            return Response(
                {
                    "detail": (
                        "Nutrition AI is not configured. "
                        "Set OPENAI_API_KEY on the backend."
                    ),
                    "code": "nutrition_ai_not_configured",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        user_context = {
            "description": description,
            "meal_type": meal_type,
            "restaurant": restaurant,
        }

        system_prompt = (
            "You are the SyncWorks nutrition analysis engine. "
            "Estimate nutrition for the user's meal description. "
            "Break combined meals into individual food items. "
            "Use standard published restaurant portions when a "
            "restaurant and menu item are clearly named. For "
            "homemade meals, use reasonable serving assumptions. "
            "Never claim medical precision. Return calories, "
            "protein, carbohydrates, fat, fiber, and sugar. "
            "Make totals equal the sum of the item estimates. "
            "State meaningful assumptions and warnings. Use low "
            "confidence when portions or foods are ambiguous."
        )

        request_payload = {
            "model": _nutrition_model(),
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_prompt,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                user_context,
                                ensure_ascii=False,
                            ),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "nutrition_analysis",
                    "strict": True,
                    "schema": NUTRITION_RESPONSE_SCHEMA,
                }
            },
            "temperature": 0.2,
            "max_output_tokens": 2200,
        }

        try:
            openai_response = requests.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=45,
            )
        except requests.RequestException:
            logger.exception(
                "Nutrition analysis request failed."
            )

            return Response(
                {
                    "detail": (
                        "Nutrition analysis is temporarily "
                        "unavailable. Try again shortly."
                    ),
                    "code": "nutrition_ai_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not openai_response.ok:
            logger.warning(
                "Nutrition analysis provider returned %s: %s",
                openai_response.status_code,
                openai_response.text[:1000],
            )

            return Response(
                {
                    "detail": (
                        "Nutrition analysis could not be "
                        "completed right now."
                    ),
                    "code": "nutrition_ai_provider_error",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        provider_payload = openai_response.json()
        output_text = _extract_response_text(
            provider_payload
        )

        if not output_text:
            logger.warning(
                "Nutrition analysis returned no output text."
            )

            return Response(
                {
                    "detail": (
                        "Nutrition analysis returned an "
                        "empty response."
                    ),
                    "code": "nutrition_ai_empty_response",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            analysis = json.loads(output_text)
        except json.JSONDecodeError:
            logger.exception(
                "Nutrition analysis returned invalid JSON."
            )

            return Response(
                {
                    "detail": (
                        "Nutrition analysis returned an "
                        "invalid response."
                    ),
                    "code": "nutrition_ai_invalid_response",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        normalized = _normalize_analysis(analysis)

        return Response(
            {
                **normalized,
                "provider": "openai",
                "model": _nutrition_model(),
            },
            status=status.HTTP_200_OK,
        )


class RedeemHealthAccessCodeView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = RedeemHealthAccessCodeSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        submitted_code = serializer.validated_data["code"]
        expected_code = _configured_health_access_code()

        if submitted_code != expected_code:
            return Response(
                {
                    "detail": (
                        "Health & Fitness access code is invalid."
                    ),
                    "valid": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer_settings, _created = (
            CustomerSettings.objects.select_for_update()
            .get_or_create(user=request.user)
        )

        customer_settings.health_access = True
        customer_settings.health_until = None
        customer_settings.health_fitness_enabled = True

        customer_settings.save(
            update_fields=[
                "health_access",
                "health_until",
                "health_fitness_enabled",
                "updated_at",
            ]
        )

        CustomerHealthProfile.objects.get_or_create(
            user=request.user
        )

        return Response(
            {
                "detail": (
                    "Health & Fitness has been unlocked "
                    "for this account."
                ),
                "valid": True,
                "code": submitted_code,
                "health_access": True,
                "health_until": None,
                "lifetime_access": True,
            },
            status=status.HTTP_200_OK,
        )

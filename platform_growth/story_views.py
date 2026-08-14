from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_growth.models import GrowthContentDraft
from platform_growth.serializers import GrowthContentDraftSerializer


class IsGodModeOrSBO(BasePermission):
    message = "Not allowed."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        from user_accounts.services.god_mode import is_god_mode

        if is_god_mode(user):
            return True

        return (getattr(user, "role", "") or "").upper() == "SBO"


def _clean(value, max_length=1200):
    return str(value or "").strip()[:max_length]


def _sentence(value):
    text = _clean(value)
    if not text:
        return ""
    return text if text[-1] in ".!?" else f"{text}."


class GrowthStoryDraftAPIView(APIView):
    """Turn verified business facts into a safe-mode, human-centered social draft."""

    permission_classes = [IsAuthenticated, IsGodModeOrSBO]

    def post(self, request):
        business_name = _clean(request.data.get("business_name"), 120) or "Our business"
        headline = _clean(request.data.get("headline"), 160) or f"Behind the Scenes at {business_name}"
        situation = _clean(request.data.get("situation"))
        obstacle = _clean(request.data.get("obstacle"))
        solution = _clean(request.data.get("solution"))
        outcome = _clean(request.data.get("outcome"))
        value = _clean(request.data.get("value"), 300) or "doing what makes the most sense for the customer"
        thanks = _clean(request.data.get("thanks"), 300)
        closing = _clean(request.data.get("closing"), 180) or "Serving people, one story at a time."
        call_to_action = _clean(request.data.get("call_to_action"), 240)
        hashtags = _clean(request.data.get("hashtags"), 300)
        customer_permission = bool(request.data.get("customer_permission"))
        contains_customer_identity = bool(request.data.get("contains_customer_identity"))

        required = {
            "situation": situation,
            "solution": solution,
            "outcome": outcome,
        }
        missing = [key for key, value_text in required.items() if not value_text]
        if missing:
            return Response(
                {"detail": f"Missing required fields: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if contains_customer_identity and not customer_permission:
            return Response(
                {"detail": "Customer permission is required before including identifying information."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paragraphs = [
            f"💙 {headline} 💙",
            "Not every day is only about business.\nSometimes it is about people.",
            _sentence(situation),
        ]

        if obstacle:
            paragraphs.append(_sentence(obstacle))

        paragraphs.extend(
            [
                "Instead of walking away, we found another solution.",
                _sentence(solution),
                _sentence(outcome),
                (
                    f"This is the kind of work that reminds us why we started {business_name}. "
                    f"Our mission is about more than completing a job. It is about {_sentence(value).lower()}"
                ),
            ]
        )

        if thanks:
            paragraphs.append(_sentence(thanks))

        if call_to_action:
            paragraphs.append(_sentence(call_to_action))

        paragraphs.append(f"❤️ {closing}")

        if hashtags:
            normalized_hashtags = " ".join(
                token if token.startswith("#") else f"#{token.lstrip('#')}"
                for token in hashtags.replace(",", " ").split()
                if token.strip()
            )
            if normalized_hashtags:
                paragraphs.append(normalized_hashtags)

        body = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)

        draft = GrowthContentDraft.objects.create(
            title=headline,
            body=body,
            status=GrowthContentDraft.Status.DRAFT,
            source="STORY_CAPTURE",
            metadata={
                "safe_mode": True,
                "no_external_post": True,
                "created_from": "growth_story_generator",
                "customer_permission": customer_permission,
                "contains_customer_identity": contains_customer_identity,
                "facts_verified_by_user": True,
                "recipe": "community_story",
            },
            created_by=request.user,
        )

        return Response(GrowthContentDraftSerializer(draft).data, status=status.HTTP_201_CREATED)

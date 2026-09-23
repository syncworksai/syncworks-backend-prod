"""Private paper scorebook archive attached to existing SportsGame records.

Do not infer statistical results from images. A manager must compare the image
against entries in the editable digital Game Book before marking it reviewed.
"""
from io import BytesIO

from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from platform_social.models import GroupMembership
from .models import SportsGame, SportsGameBookPage


MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_PIXELS = 45_000_000
MAX_PAGES_PER_GAME = 16
MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
MANAGER_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)
STAFF_ROLES = MANAGER_ROLES + (GroupMembership.Role.SCOREKEEPER,)


def _page_metadata(page):
    return {
        "id": page.id,
        "page_number": page.page_number,
        "original_filename": page.original_filename,
        "image_mime": page.image_mime,
        "image_width": page.image_width,
        "image_height": page.image_height,
        "notes": page.notes,
        "review_status": page.review_status,
        "reviewed_at": page.reviewed_at,
        "uploaded_by": page.uploaded_by_id,
        "reviewed_by": page.reviewed_by_id,
        "created_at": page.created_at,
    }


def _inspect_photo(uploaded):
    if not uploaded:
        return None, Response({"detail": "Choose a scorebook photograph."}, status=400)
    if uploaded.size > MAX_PHOTO_BYTES:
        return None, Response({"detail": "Each photograph must be 10 MB or less."}, status=400)
    if uploaded.size <= 0:
        return None, Response({"detail": "The uploaded image is empty."}, status=400)

    original = uploaded.read()
    try:
        with Image.open(BytesIO(original)) as image:
            image_format = image.format
            if image_format not in MIME_BY_FORMAT:
                return None, Response({
                    "detail": "Upload a JPEG, PNG or WebP photo. iPhone HEIC images must be exported as JPEG."
                }, status=400)
            width, height = image.size
            if width * height > MAX_PHOTO_PIXELS:
                return None, Response({
                    "detail": "Image resolution is too large. Use a photograph under 45 megapixels."
                }, status=400)
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None, Response({"detail": "The image could not be verified. Please retake or export it."}, status=400)

    filename = str(uploaded.name or "scorebook").replace("\\", "/").split("/")[-1][:180]
    # Preserve source file bytes rather than recompressing handwriting.
    return {
        "image_data": original,
        "image_mime": MIME_BY_FORMAT[image_format],
        "image_width": width,
        "image_height": height,
        "original_filename": filename,
    }, None


class GameBookPhotoMixin:
    @staticmethod
    def _page_permission(user, game, manager_only=False):
        return GroupMembership.objects.filter(
            group_id=game.team.group_id, user=user,
            status=GroupMembership.Status.ACTIVE,
            role__in=MANAGER_ROLES if manager_only else STAFF_ROLES,
        ).exists()

    @action(
        detail=True, methods=["get", "post"], url_path="scorebook-pages",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def scorebook_pages(self, request, pk=None):
        game = self.get_object()
        if not self._page_permission(request.user, game):
            return Response({"detail": "Only team scoring staff may access paper scorebooks."}, status=403)

        if request.method == "GET":
            pages = SportsGameBookPage.objects.filter(game=game).defer("image_data")
            response = Response([_page_metadata(page) for page in pages])
            response["Cache-Control"] = "private, no-store"
            return response

        photo = request.FILES.get("photo")
        image_fields, problem = _inspect_photo(photo)
        if problem:
            return problem
        notes = str(request.data.get("notes", "")).strip()
        if len(notes) > 1000:
            return Response({"detail": "Page notes must be 1,000 characters or less."}, status=400)

        with transaction.atomic():
            # Serialize parallel uploads for the same game and preserve ordering.
            locked = SportsGame.objects.select_for_update().get(pk=game.pk)
            page_count = SportsGameBookPage.objects.filter(game=locked).count()
            if page_count >= MAX_PAGES_PER_GAME:
                return Response({
                    "detail": "A game can have at most 16 scorebook photos."
                }, status=400)
            highest = SportsGameBookPage.objects.filter(game=locked).aggregate(
                highest=Max("page_number")
            )["highest"] or 0
            page = SportsGameBookPage.objects.create(
                game=locked, page_number=highest + 1,
                notes=notes, uploaded_by=request.user, **image_fields,
            )
        return Response(_page_metadata(page), status=status.HTTP_201_CREATED)

    @action(
        detail=True, methods=["patch", "delete"],
        url_path=r"scorebook-pages/(?P<page_id>\d+)",
        parser_classes=[JSONParser, FormParser],
    )
    def scorebook_page(self, request, pk=None, page_id=None):
        game = self.get_object()
        if not self._page_permission(request.user, game, manager_only=True):
            return Response({"detail": "Only team managers may approve or remove source photos."}, status=403)
        page = get_object_or_404(SportsGameBookPage.objects.defer("image_data"), game=game, pk=page_id)
        if request.method == "DELETE":
            page.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        changed = []
        if "notes" in request.data:
            notes = str(request.data["notes"] or "").strip()
            if len(notes) > 1000:
                return Response({"detail": "Page notes must be 1,000 characters or less."}, status=400)
            page.notes = notes
            changed.append("notes")
        if "reviewed" in request.data:
            reviewed = request.data["reviewed"]
            if not isinstance(reviewed, bool):
                return Response({"detail": "reviewed must be true or false."}, status=400)
            page.review_status = (
                SportsGameBookPage.ReviewStatus.REVIEWED if reviewed
                else SportsGameBookPage.ReviewStatus.NEEDS_REVIEW
            )
            page.reviewed_by = request.user if reviewed else None
            page.reviewed_at = timezone.now() if reviewed else None
            changed += ["review_status", "reviewed_by", "reviewed_at"]
        if not changed:
            return Response({"detail": "Provide notes or reviewed."}, status=400)
        page.save(update_fields=[*changed, "updated_at"])
        return Response(_page_metadata(page))

    @action(
        detail=True, methods=["get"],
        url_path=r"scorebook-pages/(?P<page_id>\d+)/image",
    )
    def scorebook_page_image(self, request, pk=None, page_id=None):
        game = self.get_object()
        if not self._page_permission(request.user, game):
            return Response({"detail": "Only team scoring staff may access paper scorebooks."}, status=403)
        page = get_object_or_404(SportsGameBookPage, game=game, pk=page_id)
        response = HttpResponse(bytes(page.image_data), content_type=page.image_mime)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = f'inline; filename="game-{game.id}-page-{page.id}.jpg"'
        return response

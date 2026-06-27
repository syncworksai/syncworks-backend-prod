from __future__ import annotations

from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AssetIdentifier, TicketAssetLink, TrackableAsset
from user_accounts.serializers.assets import (
    AssetIdentifierSerializer,
    TicketAssetLinkSerializer,
    TrackableAssetSerializer,
    normalize_identifier,
)
from user_accounts.viewsets.ticket_conversations import _business_context, _visible_tickets


def _business_assets(request):
    business, _, _ = _business_context(request)
    return business, TrackableAsset.objects.filter(business=business)


def _asset_or_404(request, asset_id):
    business, queryset = _business_assets(request)
    asset = queryset.select_related("customer").prefetch_related("identifiers").filter(id=asset_id).first()
    if not asset:
        raise Http404
    return business, asset


class AssetListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, queryset = _business_assets(request)
        asset_type = str(request.query_params.get("asset_type") or "").strip().upper()
        status = str(request.query_params.get("status") or "").strip().upper()
        customer_id = request.query_params.get("customer_id")
        query = str(request.query_params.get("q") or "").strip()

        if asset_type:
            queryset = queryset.filter(asset_type=asset_type)
        if status:
            queryset = queryset.filter(status=status)
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        if query:
            queryset = queryset.filter(name__icontains=query)

        queryset = queryset.select_related("customer").prefetch_related("identifiers")[:300]
        return Response({
            "business_id": business.id,
            "results": TrackableAssetSerializer(queryset, many=True).data,
        })

    def post(self, request):
        business, _, _ = _business_context(request)
        serializer = TrackableAssetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = serializer.save(business=business, created_by=request.user)

        sync_value = f"SW-ASSET-{asset.public_token}"
        AssetIdentifier.objects.create(
            asset=asset,
            identifier_type=AssetIdentifier.IdentifierType.SYNCWORKS_QR,
            value=sync_value,
            normalized_value=normalize_identifier(
                sync_value,
                AssetIdentifier.IdentifierType.SYNCWORKS_QR,
            ),
            source="SYNCWORKS",
            is_primary=True,
        )

        asset = TrackableAsset.objects.select_related("customer").prefetch_related("identifiers").get(id=asset.id)
        return Response(TrackableAssetSerializer(asset).data, status=201)


class AssetDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, asset_id):
        _, asset = _asset_or_404(request, asset_id)
        return Response(TrackableAssetSerializer(asset).data)

    def patch(self, request, asset_id):
        _, asset = _asset_or_404(request, asset_id)
        serializer = TrackableAssetSerializer(asset, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        asset = serializer.save()
        return Response(TrackableAssetSerializer(asset).data)


class AssetIdentifierCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, asset_id):
        _, asset = _asset_or_404(request, asset_id)
        serializer = AssetIdentifierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier_type = serializer.validated_data["identifier_type"]
        value = serializer.validated_data["value"]
        normalized = normalize_identifier(value, identifier_type)
        if not normalized:
            raise ValidationError({"value": "Identifier value is required."})

        collision = AssetIdentifier.objects.filter(
            asset__business=asset.business,
            identifier_type=identifier_type,
            normalized_value=normalized,
            is_active=True,
        ).exclude(asset=asset).select_related("asset").first()

        if collision:
            raise ValidationError({
                "value": f"This identifier is already linked to asset {collision.asset_id}."
            })

        try:
            with transaction.atomic():
                identifier = AssetIdentifier.objects.create(
                    asset=asset,
                    identifier_type=identifier_type,
                    value=str(value).strip(),
                    normalized_value=normalized,
                    source=serializer.validated_data.get("source", ""),
                    is_primary=serializer.validated_data.get("is_primary", False),
                    is_active=serializer.validated_data.get("is_active", True),
                )
        except IntegrityError:
            raise ValidationError({"value": "This identifier already exists on the asset."})

        return Response(AssetIdentifierSerializer(identifier).data, status=201)


class AssetScanResolveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        business, _, _ = _business_context(request)
        value = str((request.data or {}).get("value") or "").strip()
        identifier_type = str((request.data or {}).get("identifier_type") or "").strip().upper()

        if not value:
            raise ValidationError({"value": "Scan or identifier value is required."})

        candidate_types = [identifier_type] if identifier_type else [
            choice for choice, _ in AssetIdentifier.IdentifierType.choices
        ]

        matches = []
        for kind in candidate_types:
            normalized = normalize_identifier(value, kind)
            if not normalized:
                continue
            found = AssetIdentifier.objects.filter(
                asset__business=business,
                identifier_type=kind,
                normalized_value=normalized,
                is_active=True,
                asset__is_active=True,
            ).select_related("asset", "asset__customer").prefetch_related("asset__identifiers")
            matches.extend(list(found[:3]))

        unique_assets = {identifier.asset_id: identifier for identifier in matches}

        if not unique_assets:
            return Response({
                "matched": False,
                "value": value,
                "identifier_type": identifier_type or None,
                "asset": None,
            }, status=404)

        if len(unique_assets) > 1:
            return Response({
                "matched": False,
                "ambiguous": True,
                "value": value,
                "results": [
                    TrackableAssetSerializer(item.asset).data
                    for item in unique_assets.values()
                ],
            }, status=409)

        identifier = next(iter(unique_assets.values()))
        return Response({
            "matched": True,
            "identifier": AssetIdentifierSerializer(identifier).data,
            "asset": TrackableAssetSerializer(identifier.asset).data,
        })


class TicketAssetLinkAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
        if not ticket:
            raise Http404

        links = TicketAssetLink.objects.filter(ticket=ticket).select_related(
            "asset",
            "asset__customer",
        ).prefetch_related("asset__identifiers")
        return Response({
            "ticket_id": ticket.id,
            "results": TicketAssetLinkSerializer(links, many=True).data,
        })

    def post(self, request, ticket_id):
        business, _, _ = _business_context(request)
        ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
        if not ticket:
            raise Http404

        asset_id = (request.data or {}).get("asset")
        asset = TrackableAsset.objects.filter(
            id=asset_id,
            business=business,
            is_active=True,
        ).first()
        if not asset:
            raise ValidationError({"asset": "Asset was not found in the active business."})

        role = str((request.data or {}).get("role") or "PRIMARY").upper()
        valid_roles = {choice for choice, _ in TicketAssetLink.Role.choices}
        if role not in valid_roles:
            raise ValidationError({"role": "Invalid asset link role."})

        link, created = TicketAssetLink.objects.get_or_create(
            ticket=ticket,
            asset=asset,
            role=role,
            defaults={
                "notes": str((request.data or {}).get("notes") or "").strip(),
                "created_by": request.user,
            },
        )
        return Response(TicketAssetLinkSerializer(link).data, status=201 if created else 200)

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    AssetIdentifier,
    Business,
    BusinessMember,
    ServiceCategory,
    Ticket,
    TicketAssetLink,
    TrackableAsset,
)
from user_accounts.viewsets.assets import (
    AssetIdentifierCreateAPIView,
    AssetListCreateAPIView,
    AssetScanResolveAPIView,
    TicketAssetLinkAPIView,
)


class UniversalAssetTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(username="asset-customer", email="asset-customer@example.com", password="test-pass-123")
        self.owner = User.objects.create_user(username="asset-owner", email="asset-owner@example.com", password="test-pass-123")
        self.tech = User.objects.create_user(username="asset-tech", email="asset-tech@example.com", password="test-pass-123")
        self.outsider = User.objects.create_user(username="asset-outsider", email="asset-outsider@example.com", password="test-pass-123")
        self.business = Business.objects.create(owner=self.owner, name="Universal Service Co")
        BusinessMember.objects.create(business=self.business, user=self.tech, role="TECHNICIAN", is_active=True)
        self.category = ServiceCategory.objects.create(key="asset-service", name="Asset Service")
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.tech,
            category=self.category,
        )
        self.factory = APIRequestFactory()

    def _auth(self, request, user=None):
        force_authenticate(request, user=user or self.tech)
        return request

    def test_business_user_can_create_asset_with_syncworks_identifier(self):
        request = self.factory.post(
            "/api/v1/assets/",
            {
                "customer": self.customer.id,
                "asset_type": "VEHICLE",
                "name": "2021 Ford F-150",
                "make": "Ford",
                "model": "F-150",
                "year": 2021,
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AssetListCreateAPIView.as_view()(self._auth(request))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["asset_type"], "VEHICLE")
        self.assertEqual(response.data["identifiers"][0]["identifier_type"], "SYNCWORKS_QR")

    def test_existing_barcode_can_be_mapped_and_resolved(self):
        asset = TrackableAsset.objects.create(
            business=self.business,
            customer=self.customer,
            asset_type="VEHICLE",
            name="Customer Vehicle",
        )
        request = self.factory.post(
            f"/api/v1/assets/{asset.id}/identifiers/",
            {
                "identifier_type": "BARCODE",
                "value": "SHOP-00857391",
                "source": "Existing shop sticker",
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AssetIdentifierCreateAPIView.as_view()(self._auth(request), asset_id=asset.id)
        self.assertEqual(response.status_code, 201)

        scan = self.factory.post(
            "/api/v1/assets/scan/resolve/",
            {"value": "shop 00857391", "identifier_type": "BARCODE"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        resolved = AssetScanResolveAPIView.as_view()(self._auth(scan))
        self.assertEqual(resolved.status_code, 200)
        self.assertTrue(resolved.data["matched"])
        self.assertEqual(resolved.data["asset"]["id"], asset.id)

    def test_vin_normalization_resolves_same_asset(self):
        asset = TrackableAsset.objects.create(
            business=self.business,
            customer=self.customer,
            asset_type="VEHICLE",
            name="VIN Vehicle",
        )
        AssetIdentifier.objects.create(
            asset=asset,
            identifier_type="VIN",
            value="1FT-FW1E50-MFA12345",
            normalized_value="1FTFW1E50MFA12345",
        )
        scan = self.factory.post(
            "/api/v1/assets/scan/resolve/",
            {"value": "1ft fw1e50 mfa12345", "identifier_type": "VIN"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AssetScanResolveAPIView.as_view()(self._auth(scan))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["asset"]["id"], asset.id)

    def test_asset_can_link_to_ticket(self):
        asset = TrackableAsset.objects.create(
            business=self.business,
            customer=self.customer,
            asset_type="EQUIPMENT",
            name="HVAC Unit",
        )
        request = self.factory.post(
            f"/api/v1/tickets/{self.ticket.id}/assets/",
            {"asset": asset.id, "role": "PRIMARY"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketAssetLinkAPIView.as_view()(self._auth(request), ticket_id=self.ticket.id)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(TicketAssetLink.objects.filter(ticket=self.ticket, asset=asset).exists())

    def test_outsider_cannot_list_business_assets(self):
        request = self.factory.get("/api/v1/assets/", HTTP_X_BUSINESS_ID=str(self.business.id))
        response = AssetListCreateAPIView.as_view()(self._auth(request, self.outsider))
        self.assertIn(response.status_code, {403, 404})

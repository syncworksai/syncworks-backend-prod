from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from platform_affiliates.permissions import IsCustomerAffiliateApplicant
from platform_affiliates.views.affiliate_portal import AffiliateAgreementView


class BusinessOwnerAffiliatePermissionsTests(SimpleTestCase):
    def setUp(self):
        self.perm = IsCustomerAffiliateApplicant()
        self.request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))

    @patch("platform_affiliates.permissions.is_god_mode", return_value=False)
    @patch("platform_affiliates.permissions.BusinessMember.objects.filter")
    @patch("platform_affiliates.permissions.Business.objects.filter")
    def test_owner_can_apply(self, business_filter, membership_filter, _god):
        business_filter.return_value.exists.return_value = True
        membership_filter.return_value.exists.return_value = True
        self.assertTrue(self.perm.has_permission(self.request, None))

    @patch("platform_affiliates.permissions.is_god_mode", return_value=False)
    @patch("platform_affiliates.permissions.BusinessMember.objects.filter")
    @patch("platform_affiliates.permissions.Business.objects.filter")
    def test_employee_cannot_apply_via_business_membership(self, business_filter, membership_filter, _god):
        business_filter.return_value.exists.return_value = False
        membership_filter.return_value.exists.side_effect = [True, False]
        self.assertFalse(self.perm.has_permission(self.request, None))

    @patch("platform_affiliates.permissions.is_god_mode", return_value=False)
    @patch("platform_affiliates.permissions.BusinessMember.objects.filter")
    @patch("platform_affiliates.permissions.Business.objects.filter")
    def test_customer_without_membership_can_apply(self, business_filter, membership_filter, _god):
        business_filter.return_value.exists.return_value = False
        membership_filter.return_value.exists.side_effect = [False, False]
        self.assertTrue(self.perm.has_permission(self.request, None))

    def test_agreement_api_requires_authentication(self):
        from rest_framework.permissions import IsAuthenticated
        self.assertIn(IsAuthenticated, AffiliateAgreementView.permission_classes)

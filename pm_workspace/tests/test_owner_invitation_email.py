from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from pm_workspace.access_models import PMInvestorGrant
from pm_workspace.models import PMWorkspace, PMProperty
from pm_workspace.owner_models import PMPropertyOwner


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_BASE_URL="https://syncworksapp.com",
)
class PMOwnerInvitationEmailTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.pm = User.objects.create_user(username="pm-invite-owner", email="pm@example.com", password="Password123!")
        self.invitee = User.objects.create_user(username="pm-invited-owner", email="owner@example.com", password="Password123!")
        self.other = User.objects.create_user(username="pm-other-owner", email="wrong@example.com", password="Password123!")
        self.workspace = PMWorkspace.objects.create(owner=self.pm, name="Test Management Company", office_email="office@example.com")
        self.property = PMProperty.objects.create(workspace=self.workspace, name="Test Property", address="100 Main St", city="Montgomery", state="AL", zip="36104", created_by=self.pm)
        self.owner = PMPropertyOwner.objects.create(workspace=self.workspace, name="Morgan Owner", email=self.invitee.email)
        self.owner.properties.add(self.property)

    def test_owner_invitation_email_contains_code_and_signup_link_and_claim_is_email_scoped(self):
        self.client.force_authenticate(self.pm)
        response = self.client.post("/api/v1/pm-hub/access/investors/", {"owner_id":self.owner.id}, format="json",
                                    HTTP_X_PM_WORKSPACE_ID=str(self.workspace.id))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["email_sent"])
        self.assertEqual(len(mail.outbox), 1)
        code = response.data["invitation_code"]
        self.assertIn("register?role=owner", mail.outbox[0].body)
        self.assertIn("email=owner%40example.com", mail.outbox[0].body)
        self.assertIn(code, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])

        self.client.force_authenticate(self.other)
        unauthorized = self.client.post("/api/v1/pm-hub/access/investors/accept/", {"code":code}, format="json")
        self.assertEqual(unauthorized.status_code, 403)
        self.assertFalse(PMInvestorGrant.objects.get(workspace=self.workspace, property_owner=self.owner).user_id)

        self.client.force_authenticate(self.invitee)
        accepted = self.client.post("/api/v1/pm-hub/access/investors/accept/", {"code":code}, format="json")
        self.assertEqual(accepted.status_code, 200, accepted.data)
        grant = PMInvestorGrant.objects.get(workspace=self.workspace, property_owner=self.owner)
        self.assertEqual(grant.user, self.invitee)
        self.assertEqual(grant.status, "ACCEPTED")
        repeat = self.client.post("/api/v1/pm-hub/access/investors/accept/", {"code":code}, format="json")
        self.assertEqual(repeat.status_code, 404)

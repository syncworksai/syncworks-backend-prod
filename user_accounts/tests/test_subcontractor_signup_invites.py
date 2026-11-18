from django.test import TestCase,override_settings
from django.core import mail
from rest_framework.test import APIClient
from user_accounts.models import Business,BusinessMember,User,BusinessPartnerInvitation


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",FRONTEND_URL="https://syncworksapp.com")
class PartnerSignupInviteTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create_user(username="sub-invite-owner",email="sub-owner@example.com",password="test")
        self.other=User.objects.create_user(username="sub-invite-recipient",email="sub-recipient@example.com",password="test",email_verified=True)
        self.business=Business.objects.create(name="Contracting Company",owner=self.owner)
        self.partner=Business.objects.create(name="Recipient Company",owner=self.other)
        self.client=APIClient()

    def test_email_invitation_and_verified_accept(self):
        self.client.force_authenticate(self.owner)
        self.client.credentials(HTTP_X_BUSINESS_ID=str(self.business.id))
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post("/api/v1/business-partner-invitations/",{
                "business_name":"Recipient Company","contact_name":"Trade Partner",
                "email":self.other.email,"relationship_type":"SUBCONTRACTOR"
            },format="json")
        self.assertEqual(response.status_code,201,response.data)
        self.assertTrue(response.data.get("email_queued"))
        self.assertEqual(len(mail.outbox),1)
        self.assertIn("/partner/join?token=",mail.outbox[0].body)
        invite=BusinessPartnerInvitation.objects.get(pk=response.data["id"])
        self.assertIsNotNone(invite.expires_at)
        self.client.force_authenticate(self.other)
        self.client.credentials(HTTP_X_BUSINESS_ID=str(self.partner.id))
        accepted=self.client.post("/api/v1/business-partner-invitations/respond/",{
            "token":invite.token,"decision":"ACCEPT"
        },format="json")
        self.assertEqual(accepted.status_code,200,accepted.data)

    def test_unverified_invited_email_cannot_accept(self):
        from django.utils import timezone
        from datetime import timedelta
        invite=BusinessPartnerInvitation.objects.create(
            inviting_business=self.business,business_name=self.partner.name,
            email=self.other.email,created_by=self.owner,
            expires_at=timezone.now()+timedelta(days=14),
        )
        self.other.email_verified=False
        self.other.save(update_fields=["email_verified"])
        self.client.force_authenticate(self.other)
        self.client.credentials(HTTP_X_BUSINESS_ID=str(self.partner.id))
        response=self.client.post("/api/v1/business-partner-invitations/respond/",{
            "token":invite.token,"decision":"ACCEPT"
        },format="json")
        self.assertEqual(response.status_code,400,response.data)

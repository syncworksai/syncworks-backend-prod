"""Technician crew/region permission and filtering regression tests."""
from django.test import TestCase
from rest_framework.test import APIClient
from user_accounts.models import Business,BusinessMember,BusinessTechnicianGroup,User,WorkforceProfile


class BusinessCrewGroupTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create_user(username="crew-owner",email="crew-owner@example.com",password="test")
        self.employee=User.objects.create_user(username="crew-tech",email="crew-tech@example.com",password="test")
        self.business=Business.objects.create(name="Region Test",owner=self.owner)
        self.member=BusinessMember.objects.create(business=self.business,user=self.employee,role="TECHNICIAN")
        self.profile=WorkforceProfile.objects.create(member=self.member,is_schedulable=True)
        self.client=APIClient()
        self.headers={"HTTP_X_BUSINESS_ID":str(self.business.pk)}

    def test_owner_can_create_group_and_assign_technician(self):
        self.client.force_authenticate(self.owner)
        created=self.client.post("/api/v1/sync-ai/business/technician-groups/",{"name":"Montgomery North"},format="json",**self.headers)
        self.assertEqual(created.status_code,201,created.data)
        group=BusinessTechnicianGroup.objects.get(pk=created.data["id"])
        assigned=self.client.patch("/api/v1/sync-ai/business/workforce/",{
            "business_id":self.business.id,"member_id":self.member.id,"technician_group_id":group.pk
        },format="json",**self.headers)
        self.assertEqual(assigned.status_code,200,assigned.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.technician_group_id,group.pk)
        listing=self.client.get("/api/v1/sync-ai/business/technician-groups/",**self.headers)
        self.assertEqual(listing.data["groups"][0]["members"],1)

    def test_technician_cannot_manage_groups(self):
        self.client.force_authenticate(self.employee)
        attempt=self.client.post("/api/v1/sync-ai/business/technician-groups/",{"name":"Unapproved"},format="json",**self.headers)
        self.assertEqual(attempt.status_code,403)

    def test_another_business_group_cannot_be_assigned(self):
        self.client.force_authenticate(self.owner)
        other=Business.objects.create(name="Different Business",owner=self.owner)
        group=BusinessTechnicianGroup.objects.create(business=other,name="Other Region")
        attempt=self.client.patch("/api/v1/sync-ai/business/workforce/",{
            "business_id":self.business.id,"member_id":self.member.id,"technician_group_id":group.id
        },format="json",**self.headers)
        self.assertEqual(attempt.status_code,400)

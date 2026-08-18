from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from platform_social.models import GroupMembership, SocialGroup

from .models import HouseholdMemberSettings, HouseholdProfile

User = get_user_model()


class HouseholdPrivacyTests(APITestCase):
    def user(self, email):
        username = email.split("@", 1)[0]
        return User.objects.create_user(username=username, email=email, password="test-pass-123")

    def client_for(self, actor):
        client = APIClient()
        client.force_authenticate(actor)
        return client

    def group_for(self, owner, *, name="Family", kind=SocialGroup.Kind.HOUSEHOLD):
        group = SocialGroup.objects.create(
            name=name,
            kind=kind,
            visibility=SocialGroup.Visibility.INVITE_ONLY,
            created_by=owner,
        )
        GroupMembership.objects.create(
            group=group,
            user=owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=owner,
        )
        return group

    def test_group_named_family_does_not_gain_household_access_by_name(self):
        owner = self.user("owner-family-name@example.com")
        normal_group = self.group_for(owner, name="Family", kind=SocialGroup.Kind.COMMUNITY)
        response = self.client_for(owner).post(
            "/api/v1/household/households/",
            {"group": normal_group.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(HouseholdProfile.objects.count(), 0)

    def test_household_creation_defaults_finance_sharing_off(self):
        owner = self.user("household-owner@example.com")
        group = self.group_for(owner)
        response = self.client_for(owner).post(
            "/api/v1/household/households/",
            {
                "group": group.id,
                "address_line1": "100 Main St",
                "city": "Montgomery",
                "state": "AL",
                "postal_code": "36104",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        settings = HouseholdMemberSettings.objects.get(user=owner)
        self.assertTrue(settings.share_calendar)
        self.assertFalse(settings.share_finance_summary)
        self.assertFalse(settings.share_finance_accounts)
        self.assertFalse(settings.share_finance_bills)
        self.assertFalse(settings.share_finance_income)
        self.assertFalse(settings.share_finance_transactions)
        self.assertFalse(settings.share_finance_budgets)

    def test_late_accepted_member_gets_own_private_settings_on_first_load(self):
        owner = self.user("late-owner@example.com")
        member = self.user("late-member@example.com")
        group = self.group_for(owner)
        household = HouseholdProfile.objects.create(group=group, created_by=owner)
        HouseholdMemberSettings.objects.create(household=household, user=owner)
        GroupMembership.objects.create(
            group=group,
            user=member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=owner,
        )

        response = self.client_for(member).get("/api/v1/household/member-settings/")

        self.assertEqual(response.status_code, 200)
        member_settings = HouseholdMemberSettings.objects.get(household=household, user=member)
        self.assertTrue(member_settings.share_calendar)
        self.assertFalse(member_settings.share_finance_summary)
        self.assertFalse(member_settings.share_finance_accounts)
        self.assertFalse(member_settings.share_finance_transactions)

    def test_member_cannot_enable_someone_elses_finance_sharing(self):
        owner = self.user("finance-owner@example.com")
        member = self.user("finance-member@example.com")
        group = self.group_for(owner)
        GroupMembership.objects.create(
            group=group,
            user=member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=owner,
        )
        household = HouseholdProfile.objects.create(group=group, created_by=owner)
        owner_settings = HouseholdMemberSettings.objects.create(household=household, user=owner)
        HouseholdMemberSettings.objects.create(household=household, user=member)

        response = self.client_for(member).patch(
            f"/api/v1/household/member-settings/{owner_settings.id}/",
            {"share_finance_accounts": True, "share_finance_transactions": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        owner_settings.refresh_from_db()
        self.assertFalse(owner_settings.share_finance_accounts)
        self.assertFalse(owner_settings.share_finance_transactions)

    def test_active_household_member_can_add_task_but_outsider_cannot_read_it(self):
        owner = self.user("task-owner@example.com")
        member = self.user("task-member@example.com")
        outsider = self.user("task-outsider@example.com")
        group = self.group_for(owner)
        GroupMembership.objects.create(
            group=group,
            user=member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=owner,
        )
        household = HouseholdProfile.objects.create(group=group, created_by=owner)
        HouseholdMemberSettings.objects.create(household=household, user=owner)
        HouseholdMemberSettings.objects.create(household=household, user=member)

        created = self.client_for(member).post(
            "/api/v1/household/tasks/",
            {
                "household": household.id,
                "title": "Call insurance",
                "estimated_minutes": 20,
                "requires_phone": True,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client_for(owner).get("/api/v1/household/tasks/").json()[0]["title"], "Call insurance")
        self.assertEqual(self.client_for(outsider).get("/api/v1/household/tasks/").json(), [])

    def test_shopping_and_goals_are_household_scoped(self):
        owner = self.user("shopping-owner@example.com")
        outsider = self.user("shopping-outsider@example.com")
        group = self.group_for(owner)
        household = HouseholdProfile.objects.create(group=group, created_by=owner)
        HouseholdMemberSettings.objects.create(household=household, user=owner)
        owner_client = self.client_for(owner)

        item = owner_client.post(
            "/api/v1/household/shopping/",
            {"household": household.id, "name": "Paper towels", "category": "HOUSEHOLD"},
            format="json",
        )
        goal = owner_client.post(
            "/api/v1/household/goals/",
            {"household": household.id, "title": "Meal prep", "cadence": "WEEKLY", "target_value": "1"},
            format="json",
        )
        self.assertEqual(item.status_code, 201)
        self.assertEqual(goal.status_code, 201)
        outsider_client = self.client_for(outsider)
        self.assertEqual(outsider_client.get("/api/v1/household/shopping/").json(), [])
        self.assertEqual(outsider_client.get("/api/v1/household/goals/").json(), [])

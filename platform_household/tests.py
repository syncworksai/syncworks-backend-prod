import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from platform_social.models import GroupMembership, SocialGroup

from .models import HouseholdMemberSettings, HouseholdProfile

User = get_user_model()


def user(email):
    return User.objects.create_user(email=email, password="test-pass-123")


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def group_for(owner, *, name="Family", kind=SocialGroup.Kind.HOUSEHOLD):
    group = SocialGroup.objects.create(name=name, kind=kind, visibility=SocialGroup.Visibility.INVITE_ONLY, created_by=owner)
    GroupMembership.objects.create(group=group, user=owner, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=owner)
    return group


@pytest.mark.django_db
def test_group_named_family_does_not_gain_household_access_by_name():
    owner = user("owner-family-name@example.com")
    normal_group = group_for(owner, name="Family", kind=SocialGroup.Kind.COMMUNITY)
    response = client_for(owner).post("/api/v1/household/households/", {"group": normal_group.id}, format="json")
    assert response.status_code == 400
    assert HouseholdProfile.objects.count() == 0


@pytest.mark.django_db
def test_household_creation_defaults_finance_sharing_off():
    owner = user("household-owner@example.com")
    group = group_for(owner)
    response = client_for(owner).post(
        "/api/v1/household/households/",
        {"group": group.id, "address_line1": "100 Main St", "city": "Montgomery", "state": "AL", "postal_code": "36104"},
        format="json",
    )
    assert response.status_code == 201
    settings = HouseholdMemberSettings.objects.get(user=owner)
    assert settings.share_calendar is True
    assert settings.share_finance_summary is False
    assert settings.share_finance_accounts is False
    assert settings.share_finance_bills is False
    assert settings.share_finance_income is False
    assert settings.share_finance_transactions is False
    assert settings.share_finance_budgets is False


@pytest.mark.django_db
def test_member_cannot_enable_someone_elses_finance_sharing():
    owner = user("finance-owner@example.com")
    member = user("finance-member@example.com")
    group = group_for(owner)
    GroupMembership.objects.create(group=group, user=member, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.ACTIVE, invited_by=owner)
    household = HouseholdProfile.objects.create(group=group, created_by=owner)
    owner_settings = HouseholdMemberSettings.objects.create(household=household, user=owner)
    HouseholdMemberSettings.objects.create(household=household, user=member)

    response = client_for(member).patch(
        f"/api/v1/household/member-settings/{owner_settings.id}/",
        {"share_finance_accounts": True, "share_finance_transactions": True},
        format="json",
    )
    assert response.status_code == 400
    owner_settings.refresh_from_db()
    assert owner_settings.share_finance_accounts is False
    assert owner_settings.share_finance_transactions is False


@pytest.mark.django_db
def test_active_household_member_can_add_task_but_outsider_cannot_read_it():
    owner = user("task-owner@example.com")
    member = user("task-member@example.com")
    outsider = user("task-outsider@example.com")
    group = group_for(owner)
    GroupMembership.objects.create(group=group, user=member, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.ACTIVE, invited_by=owner)
    household = HouseholdProfile.objects.create(group=group, created_by=owner)
    HouseholdMemberSettings.objects.create(household=household, user=owner)
    HouseholdMemberSettings.objects.create(household=household, user=member)

    created = client_for(member).post(
        "/api/v1/household/tasks/",
        {"household": household.id, "title": "Call insurance", "estimated_minutes": 20, "requires_phone": True},
        format="json",
    )
    assert created.status_code == 201
    assert client_for(owner).get("/api/v1/household/tasks/").json()[0]["title"] == "Call insurance"
    assert client_for(outsider).get("/api/v1/household/tasks/").json() == []


@pytest.mark.django_db
def test_shopping_and_goals_are_household_scoped():
    owner = user("shopping-owner@example.com")
    outsider = user("shopping-outsider@example.com")
    group = group_for(owner)
    household = HouseholdProfile.objects.create(group=group, created_by=owner)
    HouseholdMemberSettings.objects.create(household=household, user=owner)
    owner_client = client_for(owner)

    item = owner_client.post("/api/v1/household/shopping/", {"household": household.id, "name": "Paper towels", "category": "HOUSEHOLD"}, format="json")
    goal = owner_client.post("/api/v1/household/goals/", {"household": household.id, "title": "Meal prep", "cadence": "WEEKLY", "target_value": "1"}, format="json")
    assert item.status_code == 201
    assert goal.status_code == 201
    outsider_client = client_for(outsider)
    assert outsider_client.get("/api/v1/household/shopping/").json() == []
    assert outsider_client.get("/api/v1/household/goals/").json() == []

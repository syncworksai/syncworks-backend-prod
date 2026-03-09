# user_accounts/services/permissions.py
from user_accounts.models import BusinessMember


def get_active_membership(user, business_id):
    return (
        BusinessMember.objects
        .filter(user_id=user.id, business_id=business_id, is_active=True)
        .first()
    )

from rest_framework.routers import DefaultRouter

from .views import (
    CollectionShareViewSet,
    CollectionViewSet,
    ConnectionViewSet,
    EventMemberResponseViewSet,
    GroupEventInvitationViewSet,
    GroupInviteLinkViewSet,
    GroupMembershipViewSet,
    GroupMessageViewSet,
    PeopleViewSet,
    SocialEventViewSet,
    SocialGroupViewSet,
)

router = DefaultRouter()
router.register("people", PeopleViewSet, basename="social-people")
router.register("connections", ConnectionViewSet, basename="social-connections")
router.register("groups", SocialGroupViewSet, basename="social-groups")
router.register("memberships", GroupMembershipViewSet, basename="social-memberships")
router.register("group-invite-links", GroupInviteLinkViewSet, basename="social-group-invite-links")
router.register("group-messages", GroupMessageViewSet, basename="social-group-messages")
router.register("events", SocialEventViewSet, basename="social-events")
router.register("event-invitations", GroupEventInvitationViewSet, basename="social-event-invitations")
router.register("event-responses", EventMemberResponseViewSet, basename="social-event-responses")
router.register("collections", CollectionViewSet, basename="social-collections")
router.register("collection-shares", CollectionShareViewSet, basename="social-collection-shares")

urlpatterns = router.urls

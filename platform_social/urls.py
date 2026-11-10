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

from django.urls import path
from .card_rooms import card_rooms, card_room_detail, card_room_action
from .online_poker import online_poker_game

urlpatterns = [
    path("card-rooms/", card_rooms, name="social-card-rooms"),
    path("card-rooms/<int:room_id>/", card_room_detail, name="social-card-room-detail"),
    path("card-rooms/<int:room_id>/game/", online_poker_game, name="social-card-room-game"),
    path("card-rooms/<int:room_id>/<str:verb>/", card_room_action, name="social-card-room-action"),
] + router.urls

"""Authenticated, group-scoped poker lobby. No real-money processing or dealing."""
import secrets

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import CardPokerRoom, CardPokerSeat, GroupMembership, SocialGroup

GAMES = ("357", "fyb", "442", "bozo", "queen-follower")
MAX_VIRTUAL_CENTS = 1_000_000


def _member(user, group_id):
    return GroupMembership.objects.filter(
        group_id=group_id, user=user, status=GroupMembership.Status.ACTIVE,
    ).exists() or SocialGroup.objects.filter(pk=group_id, created_by=user, is_active=True).exists()


def _manager(user, group_id):
    return GroupMembership.objects.filter(
        group_id=group_id, user=user, status=GroupMembership.Status.ACTIVE,
        role__in=["OWNER", "DIRECTOR", "MANAGER"],
    ).exists() or SocialGroup.objects.filter(pk=group_id, created_by=user, is_active=True).exists()


def _room_or_denied(user, room_id):
    room = get_object_or_404(CardPokerRoom.objects.select_related("group", "created_by"), pk=room_id)
    if not room.group.is_active or not _member(user, room.group_id):
        return None
    return room


def _seat_info(seat):
    user = seat.user
    label = "Computer" if seat.is_computer else (
        (f"{user.first_name} {user.last_name}".strip() or user.email) if user else "Open seat"
    )
    return {
        "id": seat.id,
        "nickname": seat.nickname,
        "avatar_url": "",
        "position": seat.position,
        "user_id": seat.user_id,
        "name": seat.nickname or label,
        "is_computer": seat.is_computer,
        "virtual_chips_cents": seat.virtual_chips_cents,
    }


def _snapshot(room, user):
    seats = list(room.seats.select_related("user").order_by("position"))
    return {
        "id": room.pk,
        "group": room.group_id,
        "name": room.name,
        "capacity": room.capacity,
        "virtual_buy_in_cents": room.virtual_buy_in_cents,
        "state": room.state,
        "created_by": room.created_by_id,
        "host": room.created_by_id == user.pk,
        "dealer_position": room.dealer_position,
        "game_code": room.game_code,
        "game_selection": room.game_selection,
        "ante_cents": room.ante_cents,
        "pot_cap_cents": room.pot_cap_cents,
        "hand_number": room.hand_number,
        "seats": [_seat_info(s) for s in seats],
        "updated_at": room.updated_at,
    }


def _parse_integer(data, field, min_value, max_value, default=None):
    raw = data.get(field, default)
    if isinstance(raw, bool):
        raise ValueError(field)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(field) from None
    if value < min_value or value > max_value:
        raise ValueError(field)
    return value


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def card_rooms(request):
    if request.method == "GET":
        try:
            group_id = _parse_integer(request.query_params, "group", 1, 2**31 - 1)
        except ValueError:
            return Response({"detail": "A valid group ID is required."}, status=400)
        if not _member(request.user, group_id):
            return Response({"detail": "You must be an active group member."}, status=403)
        rooms = CardPokerRoom.objects.filter(group_id=group_id).exclude(state=CardPokerRoom.State.CLOSED).select_related("created_by")
        return Response([_snapshot(room, request.user) for room in rooms[:50]])

    try:
        group_id = _parse_integer(request.data, "group", 1, 2**31 - 1)
        capacity = _parse_integer(request.data, "capacity", 2, 6, 6)
        buyin = _parse_integer(request.data, "virtual_buy_in_cents", 0, MAX_VIRTUAL_CENTS, 2000)
    except ValueError as exc:
        return Response({"detail": f"Invalid field: {exc}"}, status=400)
    if not _member(request.user, group_id):
        return Response({"detail": "Join this group before creating a room."}, status=403)
    name = str(request.data.get("name") or "Poker Table").strip()[:80]
    if not name:
        return Response({"detail": "Room name is required."}, status=400)
    room = CardPokerRoom.objects.create(group_id=group_id, created_by=request.user, name=name, capacity=capacity, virtual_buy_in_cents=buyin)
    return Response(_snapshot(room, request.user), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def card_room_detail(request, room_id):
    room = _room_or_denied(request.user, room_id)
    if room is None:
        return Response({"detail": "Room unavailable."}, status=404)
    return Response(_snapshot(room, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def card_room_action(request, room_id, verb):
    if verb not in {"join", "leave", "nickname", "add-computer", "start", "configure", "next-dealer", "close"}:
        return Response({"detail": "Unknown room action."}, status=404)
    with transaction.atomic():
        room = CardPokerRoom.objects.select_for_update().select_related("group", "created_by").filter(pk=room_id).first()
        if room is None or not room.group.is_active or not _member(request.user, room.group_id):
            return Response({"detail": "Room unavailable."}, status=404)
        host = room.created_by_id == request.user.id
        if room.state == CardPokerRoom.State.CLOSED:
            return Response({"detail": "Room closed."}, status=409)
        seats = list(room.seats.select_for_update().select_related("user").order_by("position"))
        if verb == "join":
            if room.state != CardPokerRoom.State.WAITING:
                return Response({"detail": "This room is no longer seating players."}, status=409)
            if not any(s.user_id == request.user.id for s in seats):
                if len(seats) >= room.capacity:
                    return Response({"detail": "Table is full."}, status=409)
                position = next(i for i in range(room.capacity) if i not in {s.position for s in seats})
                CardPokerSeat.objects.create(room=room, user=request.user, position=position, virtual_chips_cents=room.virtual_buy_in_cents)
        elif verb == "leave":
            if room.state != CardPokerRoom.State.WAITING:
                return Response({"detail": "Wait for the host to close the game."}, status=409)
            room.seats.filter(user=request.user).delete()
        elif verb == "nickname":
            player_seat = next((s for s in seats if s.user_id == request.user.pk), None)
            if player_seat is None:
                return Response({"detail": "Join the room before editing your table name."}, status=403)
            nickname = str(request.data.get("nickname") or "").strip()[:32]
            player_seat.nickname = nickname
            player_seat.save(update_fields=["nickname"])
        elif verb == "add-computer":
            if not host or room.state != CardPokerRoom.State.WAITING:
                return Response({"detail": "Only the host may add a computer before starting."}, status=403)
            if len(seats) >= room.capacity or any(s.is_computer for s in seats):
                return Response({"detail": "Only one computer seat is supported, within the room limit."}, status=409)
            position = next(i for i in range(room.capacity) if i not in {s.position for s in seats})
            CardPokerSeat.objects.create(room=room, is_computer=True, position=position, virtual_chips_cents=room.virtual_buy_in_cents)
        elif verb == "start":
            if not host:
                return Response({"detail": "Only the room creator can start the table."}, status=403)
            if room.state != CardPokerRoom.State.WAITING or len(seats) < 2:
                return Response({"detail": "At least two seated players are required."}, status=409)
            room.dealer_position = seats[secrets.randbelow(len(seats))].position
            room.state = CardPokerRoom.State.DEALER
            room.hand_number = 1
            room.save(update_fields=["dealer_position", "state", "hand_number", "updated_at"])
        elif verb == "configure":
            dealer = next((s for s in seats if s.position == room.dealer_position), None)
            if room.state != CardPokerRoom.State.DEALER or not (host or dealer and dealer.user_id == request.user.pk):
                return Response({"detail": "Only the dealer or room creator can choose the game."}, status=403)
            choice = str(request.data.get("game_selection") or "DEALER").upper()
            if choice not in {"DEALER", "RANDOM"}:
                return Response({"detail": "Invalid game selection mode."}, status=400)
            game = str(request.data.get("game_code") or "357")
            if choice == "RANDOM":
                game = GAMES[secrets.randbelow(len(GAMES))]
            if game not in GAMES:
                return Response({"detail": "Unknown card game."}, status=400)
            try:
                ante = _parse_integer(request.data, "ante_cents", 0, MAX_VIRTUAL_CENTS, 25)
                cap = _parse_integer(request.data, "pot_cap_cents", 1, MAX_VIRTUAL_CENTS, 5000) if game != "fyb" else 0
            except ValueError as exc:
                return Response({"detail": f"Invalid field: {exc}"}, status=400)
            room.game_code, room.game_selection, room.ante_cents, room.pot_cap_cents = game, choice, ante, cap
            room.state = CardPokerRoom.State.READY
            room.save(update_fields=["game_code", "game_selection", "ante_cents", "pot_cap_cents", "state", "updated_at"])
        elif verb == "next-dealer":
            if not host or room.state not in (CardPokerRoom.State.DEALER, CardPokerRoom.State.READY):
                return Response({"detail": "Only the room creator can advance dealer."}, status=403)
            positions = [s.position for s in seats]
            next_pos = next((p for p in positions if p > room.dealer_position), positions[0])
            room.dealer_position = next_pos
            room.game_code = ""
            room.state = CardPokerRoom.State.DEALER
            room.hand_number += 1
            room.save(update_fields=["dealer_position", "game_code", "state", "hand_number", "updated_at"])
        elif verb == "close":
            if not host:
                return Response({"detail": "Only the room creator can close the room."}, status=403)
            room.state = CardPokerRoom.State.CLOSED
            room.save(update_fields=["state", "updated_at"])
        room.refresh_from_db()
        return Response(_snapshot(room, request.user))

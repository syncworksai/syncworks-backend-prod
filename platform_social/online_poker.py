"""Authoritative virtual-chip 3-5-7 for signed-in members of one Card Club.

All deck, opposing hands and decisions live on the server. Polling refreshes
deadline transitions under a row lock. No real money, payment or escrow APIs.
"""
import itertools
import secrets
import time
from collections import Counter

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import CardPokerRoom
from .card_rooms import _member

CHIP = 25
TURN_SECONDS = 30
CONTINUE_SECONDS = 10
RANK_NAME = {11: "Jacks", 12: "Queens", 13: "Kings", 14: "Aces"}


def _deck():
    cards = [{"rank": rank, "suit": suit} for rank in range(2, 15) for suit in "SHDC"]
    secrets.SystemRandom().shuffle(cards)
    return cards


def _straight_high(values):
    ordered = set(values)
    if 14 in ordered:
        ordered.add(1)
    for top in range(14, 4, -1):
        if set(range(top - 4, top + 1)).issubset(ordered):
            return top
    return 0


def _five_natural(ranks, all_same_suit):
    counts = sorted(Counter(ranks).items(), key=lambda item: (item[1], item[0]), reverse=True)
    groups = [count for _, count in counts]
    high = _straight_high(ranks)
    if groups[0] == 5:
        return (9, counts[0][0]), "Five of a kind"
    if high and all_same_suit:
        return (8, high), "Straight flush"
    if groups[0] == 4:
        return (7, counts[0][0], counts[1][0]), "Four of a kind"
    if groups[:2] == [3, 2]:
        return (6, counts[0][0], counts[1][0]), "Full house"
    if all_same_suit:
        return (5, *sorted(ranks, reverse=True)), "Flush"
    if high:
        return (4, high), "Straight"
    if groups[0] == 3:
        return (3, counts[0][0], *sorted((r for r in ranks if r != counts[0][0]), reverse=True)), "Three of a kind"
    if groups[:2] == [2, 2]:
        pairs = sorted((r for r, n in counts if n == 2), reverse=True)
        return (2, *pairs, next(r for r, n in counts if n == 1)), "Two pair"
    if groups[0] == 2:
        return (1, counts[0][0], *sorted((r for r in ranks if r != counts[0][0]), reverse=True)), "Pair"
    return (0, *sorted(ranks, reverse=True)), "High card"


def _score(cards, street):
    wild = (3, 5, 7)[street]
    count = (3, 5, 7)[street]
    if len(cards) != count:
        raise ValueError("Wrong card count")
    best = None
    for subset in itertools.combinations(cards, min(5, count)):
        regular = [c for c in subset if c["rank"] != wild]
        wild_count = len(subset) - len(regular)
        naturals = [c["rank"] for c in regular]
        if count == 3:
            for replacements in itertools.combinations_with_replacement(range(2, 15), wild_count):
                ranks = naturals + list(replacements)
                groups = sorted(Counter(ranks).items(), key=lambda x: (x[1], x[0]), reverse=True)
                ordered = tuple([groups[0][1], groups[0][0]] + sorted(ranks, reverse=True))
                label = {3: "Three of a kind", 2: "Pair"}.get(groups[0][1], "High card")
                if best is None or ordered > best[0]:
                    best = (ordered, label)
        else:
            flush_possible = len({c["suit"] for c in regular}) <= 1
            for replacements in itertools.combinations_with_replacement(range(2, 15), wild_count):
                rank, label = _five_natural(naturals + list(replacements), flush_possible)
                if best is None or rank > best[0]:
                    best = (rank, label)
    return best


def _seat(room, user):
    return next((s for s in room.seats.all() if s.user_id == user.id), None)


def _public(room, user):
    game = room.game_state or {}
    seats = list(room.seats.order_by("position"))
    own = next((s for s in seats if s.user_id == user.id), None)
    my_pos = str(own.position) if own else None
    phase = game.get("phase", "not_started")
    holders = [key for key, action in game.get("actions", {}).items() if action == "hold"]
    view_others = phase in {"result", "continue"} and my_pos in holders
    return {
        "room": room.id, "game_code": room.game_code, "phase": phase,
        "version": game.get("version", 0), "street": game.get("street", 0),
        "wild_rank": (3, 5, 7)[game.get("street", 0)],
        "hand_number": room.hand_number, "pot_cents": game.get("pot", 0),
        "cap_cents": room.pot_cap_cents, "ante_cents": room.ante_cents,
        "deadline": game.get("deadline"), "continue_deadline": game.get("continue_deadline"),
        "my_position": own.position if own else None, "my_hand": game.get("hands", {}).get(my_pos, []) if own else [],
        "players": [
            {"position": seat.position, "name": seat.nickname or (seat.user.get_full_name() or seat.user.email),
             "chips_cents": seat.virtual_chips_cents,
             "decision": ("ready" if game.get("actions", {}).get(str(seat.position)) else None) if phase == "choosing" and seat.position != (own.position if own else None) else game.get("actions", {}).get(str(seat.position)),
             "strikes": game.get("strikes", {}).get(str(seat.position), 0),
             "eligible": str(seat.position) in game.get("eligible", [])}
            for seat in seats
        ],
        "revealed_holders": {
            key: cards for key, cards in game.get("hands", {}).items()
            if view_others and key in holders
        },
        "result": game.get("result") if phase in {"result", "continue", "finished"} else None,
        "practice_mode": False, "is_host": room.created_by_id == user.id,
        "can_start": phase in {"not_started", "finished"} and room.state == CardPokerRoom.State.READY,
    }


def _save(room, game, *, end=False):
    game["version"] = game.get("version", 0) + 1
    room.game_state = game
    room.hand_active = not end
    if end:
        room.state = CardPokerRoom.State.DEALER
        occupied = list(room.seats.order_by("position").values_list("position", flat=True))
        room.dealer_position = next((p for p in occupied if p > (room.dealer_position or 0)), occupied[0] if occupied else None)
    room.save(update_fields=["game_state", "hand_active", "state", "dealer_position", "updated_at"])


def _fresh(room, seats, old=None):
    state = old or {}
    chips = [s for s in seats if s.virtual_chips_cents >= CHIP]
    if not chips:
        raise ValueError("No funded seats remain. Rebuy is required before continuing.")
    deck = _deck()
    eligible = [str(s.position) for s in chips]
    pot = state.get("pot", 0)
    per_seat = min(room.ante_cents, max(0, (room.pot_cap_cents - pot) // len(chips) // CHIP * CHIP))
    for s in chips:
        if per_seat:
            s.virtual_chips_cents -= per_seat
            s.save(update_fields=["virtual_chips_cents"])
    pot += per_seat * len(chips)
    hands = {}
    for s in chips:
        hands[str(s.position)] = [deck.pop() for _ in range(3)]
    return {
        "phase": "choosing", "street": 0, "deck": deck, "hands": hands, "eligible": eligible,
        "actions": {}, "strikes": state.get("strikes", {}), "pot": pot,
        "result": None, "deadline": time.time() + TURN_SECONDS,
        "continue_deadline": None, "version": state.get("version", 0),
    }


def _finish_decisions(room, game, seats):
    # Do not reveal opposing cards to dropped players.
    choices = game["actions"]
    for position in game["eligible"]:
        choices.setdefault(position, "drop")
    holders = [p for p in game["eligible"] if choices[p] == "hold"]
    pot = game["pot"]
    result = {"type": "carry", "winner": None, "hand": None, "payout_cents": 0, "matches": {}}
    finished = False
    if len(holders) == 1:
        only = holders[0]
        game["strikes"][only] = game["strikes"].get(only, 0) + 1
        result["type"] = "uncontested"
        result["winner"] = int(only)
        if game["strikes"][only] >= 3:
            result.update(type="game_winner", payout_cents=pot, hand="Three uncontested holds")
            next(s for s in seats if str(s.position) == only).virtual_chips_cents += pot
            game["pot"] = 0
            finished = True
    elif len(holders) > 1:
        ranked = sorted([(_score(game["hands"][pos], game["street"]), pos) for pos in holders], reverse=True)
        top = ranked[0]
        if len(ranked) > 1 and ranked[1][0][0] == top[0][0]:
            result["type"] = "tie"
        else:
            winner = top[1]
            losers = [p for p in holders if p != winner]
            replacement = pot * len(losers)
            new_pot = min(room.pot_cap_cents, replacement)
            bonus = max(0, replacement - new_pot)
            for seat in seats:
                if str(seat.position) == winner:
                    seat.virtual_chips_cents += pot + bonus
                elif str(seat.position) in losers:
                    seat.virtual_chips_cents -= pot
            game["pot"] = new_pot
            result.update(type="round_winner", winner=int(winner), hand=top[0][1],
                          payout_cents=pot + bonus, matches={p: pot for p in losers})
    for seat in seats:
        seat.save(update_fields=["virtual_chips_cents"])
    game["phase"] = "finished" if finished else "result"
    game["deadline"] = None
    game["continue_deadline"] = None
    result["next_pot_cents"] = game["pot"]
    game["result"] = result
    _save(room, game, end=finished)


def _advance(room, game, seats):
    if game["street"] == 2:
        room.hand_number += 1
        game = _fresh(room, seats, game)
        room.save(update_fields=["hand_number"])
    else:
        game["street"] += 1
        game["phase"] = "choosing"
        game["actions"] = {}
        game["result"] = None
        game["continue_deadline"] = None
        game["deadline"] = time.time() + TURN_SECONDS
        # Every seated player from the original hand receives two more cards
        # regardless of whether they dropped on an earlier street.
        for position in game["eligible"]:
            game["hands"][position].extend(game["deck"].pop() for _ in range(2))
    _save(room, game)


def _tick(room, game, seats):
    now = time.time()
    if game.get("phase") == "choosing" and now >= game.get("deadline", now + 1):
        _finish_decisions(room, game, seats)
    elif game.get("phase") == "continue" and now >= game.get("continue_deadline", now + 1):
        _advance(room, game, seats)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def online_poker_game(request, room_id):
    with transaction.atomic():
        room = CardPokerRoom.objects.select_for_update().select_related("group").filter(pk=room_id).first()
        if room is None or not room.group.is_active or not _member(request.user, room.group_id):
            return Response({"detail": "Room unavailable."}, status=404)
        # Do not lock a nullable user LEFT JOIN (Postgres forbids FOR UPDATE on it).
        seats = list(room.seats.select_for_update().order_by("position"))
        own = next((s for s in seats if s.user_id == request.user.id), None)
        if own is None:
            return Response({"detail": "Join a seat before playing."}, status=403)
        if any(s.is_computer for s in seats):
            return Response({"detail": "Online game requires human-only seats. Bot rooms stay in practice."}, status=409)
        game = room.game_state or {}
        if game:
            _tick(room, game, seats)
            game = room.game_state or {}
        if request.method == "POST":
            action = request.data.get("action")
            if action == "start":
                if room.state != CardPokerRoom.State.READY or room.game_code != "357" or room.hand_active:
                    return Response({"detail": "Dealer must select 3-5-7 and the room must be ready."}, status=409)
                if len(seats) < 2 or request.user.id != room.created_by_id:
                    return Response({"detail": "Host and at least two human players required."}, status=403)
                if room.ante_cents % CHIP or room.pot_cap_cents % CHIP or room.ante_cents < CHIP:
                    return Response({"detail": "Virtual wagers must be 25-cent increments."}, status=400)
                try:
                    game = _fresh(room, seats)
                except ValueError as exc:
                    return Response({"detail": str(exc)}, status=409)
                _save(room, game)
            elif action in {"hold", "drop"}:
                position = str(own.position)
                if game.get("phase") != "choosing" or position not in game.get("eligible", []):
                    return Response({"detail": "No active decision for your seat."}, status=409)
                if position in game["actions"]:
                    return Response({"detail": "Decision already locked for this round."}, status=409)
                game["actions"][position] = action
                if len(game["actions"]) == len(game["eligible"]):
                    _finish_decisions(room, game, seats)
                else:
                    _save(room, game)
            elif action == "continue":
                if game.get("phase") == "result":
                    game["phase"] = "continue"
                    game["continue_deadline"] = time.time() + CONTINUE_SECONDS
                    _save(room, game)
                elif game.get("phase") != "continue":
                    return Response({"detail": "No settled hand to continue."}, status=409)
            else:
                return Response({"detail": "Unknown game action."}, status=400)
        return Response(_public(room, request.user))

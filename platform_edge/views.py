from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .kalshi import get_balance
from .models import EdgeAuditEvent, EdgeExchangeConnection, EdgePaperTrade, EdgeSignal, EdgeStrategy
from .security import decrypt_secret, encrypt_secret
from .serializers import EdgeExchangeConnectionSerializer, EdgePaperTradeSerializer, EdgeSignalSerializer, EdgeStrategySerializer


def _default_strategy(user):
    strategy, _ = EdgeStrategy.objects.get_or_create(
        user=user,
        name="MLB Comeback Edge",
        defaults={
            "sport": "MLB",
            "execution_mode": "MANUAL",
            "is_armed": False,
            "daily_risk_limit_cents": 1500,
            "per_trade_limit_cents": 100,
            "minimum_edge_bps": 800,
            "minimum_score": 85,
            "min_entry_cents": 15,
            "max_entry_cents": 45,
            "max_spread_cents": 3,
            "never_chase": True,
            "auto_exit": False,
        },
    )
    return strategy


def _environment(request):
    value = str(request.data.get("environment") or request.query_params.get("environment") or "DEMO").upper()
    if value not in {"DEMO", "LIVE"}:
        return None
    return value


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard(request):
    strategy = _default_strategy(request.user)
    connections = EdgeExchangeConnection.objects.filter(user=request.user, is_active=True)
    signals = EdgeSignal.objects.filter(user=request.user)[:20]
    paper = EdgePaperTrade.objects.filter(user=request.user)
    pnl = paper.aggregate(total=Sum("pnl_cents"))["total"] or 0
    return Response({
        "mode": "PAPER",
        "live_trading_enabled": False,
        "automation_enabled": False,
        "strategy": EdgeStrategySerializer(strategy).data,
        "connections": EdgeExchangeConnectionSerializer(connections, many=True).data,
        "signals": EdgeSignalSerializer(signals, many=True).data,
        "paper": {
            "trades": paper.count(),
            "open": paper.filter(status="OPEN").count(),
            "pnl_cents": pnl,
        },
    })


class StrategyViewSet(viewsets.ModelViewSet):
    serializer_class = EdgeStrategySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        _default_strategy(self.request.user)
        return EdgeStrategy.objects.filter(user=self.request.user).order_by("sport", "name")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, is_armed=False)

    def perform_update(self, serializer):
        serializer.save(is_armed=False)

    @action(detail=True, methods=["post"])
    def disarm(self, request, pk=None):
        strategy = self.get_object()
        strategy.is_armed = False
        strategy.save(update_fields=["is_armed", "updated_at"])
        EdgeAuditEvent.objects.create(user=request.user, event_type="STRATEGY_DISARMED", payload={"strategy_id": strategy.id})
        return Response(self.get_serializer(strategy).data)


class PaperTradeViewSet(viewsets.ModelViewSet):
    serializer_class = EdgePaperTradeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return EdgePaperTrade.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def kalshi_connection(request):
    environment = _environment(request)
    if not environment:
        return Response({"detail": "environment must be DEMO or LIVE"}, status=status.HTTP_400_BAD_REQUEST)

    existing = EdgeExchangeConnection.objects.filter(user=request.user, exchange="KALSHI", environment=environment).first()

    if request.method == "GET":
        if not existing:
            return Response({"exchange": "KALSHI", "environment": environment, "connected": False})
        return Response(EdgeExchangeConnectionSerializer(existing).data)

    if request.method == "DELETE":
        if existing:
            existing.delete()
        EdgeAuditEvent.objects.create(user=request.user, event_type="KALSHI_DISCONNECTED", payload={"environment": environment})
        return Response(status=status.HTTP_204_NO_CONTENT)

    api_key_id = str(request.data.get("api_key_id") or "").strip()
    private_key = str(request.data.get("private_key") or "").strip()
    if not api_key_id or "PRIVATE KEY" not in private_key:
        return Response({"detail": "A Kalshi API Key ID and RSA private key are required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        balance = get_balance(api_key_id, private_key, environment)
        encrypted_private_key = encrypt_secret(private_key)
    except RuntimeError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except (ValueError, TypeError) as exc:
        EdgeAuditEvent.objects.create(user=request.user, event_type="KALSHI_CONNECT_FAILED", payload={"environment": environment})
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return Response({"detail": "Kalshi connection verification is temporarily unavailable."}, status=status.HTTP_502_BAD_GATEWAY)

    connection, _ = EdgeExchangeConnection.objects.update_or_create(
        user=request.user,
        exchange="KALSHI",
        environment=environment,
        defaults={
            "api_key_id": api_key_id,
            "encrypted_private_key": encrypted_private_key,
            "can_read": True,
            "can_trade": False,
            "is_active": True,
            "last_verified_at": timezone.now(),
        },
    )
    EdgeAuditEvent.objects.create(user=request.user, event_type="KALSHI_VERIFIED", payload={"environment": environment})
    data = EdgeExchangeConnectionSerializer(connection).data
    data.update({
        "balance_cents": int(balance.get("balance") or 0),
        "portfolio_value_cents": int(balance.get("portfolio_value") or 0),
        "live_trading_enabled": False,
        "message": "Kalshi account verified and connected. Trading remains locked until the execution stage is enabled.",
    })
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def kalshi_verify(request):
    environment = _environment(request)
    if not environment:
        return Response({"detail": "environment must be DEMO or LIVE"}, status=status.HTTP_400_BAD_REQUEST)

    connection = EdgeExchangeConnection.objects.filter(
        user=request.user,
        exchange="KALSHI",
        environment=environment,
        is_active=True,
    ).first()
    if not connection:
        return Response({"detail": "No saved Kalshi connection was found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        private_key = decrypt_secret(connection.encrypted_private_key)
        balance = get_balance(connection.api_key_id, private_key, environment)
    except RuntimeError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except (ValueError, TypeError) as exc:
        connection.can_read = False
        connection.can_trade = False
        connection.save(update_fields=["can_read", "can_trade", "updated_at"])
        EdgeAuditEvent.objects.create(user=request.user, event_type="KALSHI_VERIFY_FAILED", payload={"environment": environment})
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return Response({"detail": "Kalshi verification is temporarily unavailable."}, status=status.HTTP_502_BAD_GATEWAY)

    connection.can_read = True
    connection.can_trade = False
    connection.last_verified_at = timezone.now()
    connection.save(update_fields=["can_read", "can_trade", "last_verified_at", "updated_at"])
    EdgeAuditEvent.objects.create(user=request.user, event_type="KALSHI_VERIFIED", payload={"environment": environment})

    data = EdgeExchangeConnectionSerializer(connection).data
    data.update({
        "balance_cents": int(balance.get("balance") or 0),
        "portfolio_value_cents": int(balance.get("portfolio_value") or 0),
        "live_trading_enabled": False,
        "message": "Kalshi account verified. Trading remains locked until the execution stage is enabled.",
    })
    return Response(data)

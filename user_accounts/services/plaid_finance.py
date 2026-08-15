from __future__ import annotations

import base64
import hashlib
import os
from datetime import date
from decimal import Decimal

import requests
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from user_accounts.models.personal_finance import (
    FinanceAccount,
    FinanceConnection,
    FinanceLiability,
    FinanceTransaction,
)


def _fernet() -> Fernet:
    raw = os.getenv("FINANCE_TOKEN_ENCRYPTION_KEY") or settings.SECRET_KEY
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_token(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def plaid_base_url() -> str:
    env = (os.getenv("PLAID_ENV") or "sandbox").lower()
    if env == "production":
        return "https://production.plaid.com"
    if env == "development":
        return "https://development.plaid.com"
    return "https://sandbox.plaid.com"


def _credentials() -> dict:
    client_id = os.getenv("PLAID_CLIENT_ID", "")
    secret = os.getenv("PLAID_SECRET", "")
    if not client_id or not secret:
        raise RuntimeError("Plaid is not configured. Set PLAID_CLIENT_ID and PLAID_SECRET.")
    return {"client_id": client_id, "secret": secret}


def plaid_post(path: str, payload: dict) -> dict:
    data = {**_credentials(), **payload}
    response = requests.post(f"{plaid_base_url()}{path}", json=data, timeout=30)
    response.raise_for_status()
    return response.json()


def create_link_token(user) -> dict:
    products = ["transactions", "liabilities"]
    return plaid_post(
        "/link/token/create",
        {
            "user": {"client_user_id": str(user.id)},
            "client_name": "SyncWorks",
            "products": products,
            "country_codes": ["US"],
            "language": "en",
            "webhook": os.getenv("PLAID_WEBHOOK_URL", "") or None,
        },
    )


def exchange_public_token(user, public_token: str, institution: dict | None = None) -> FinanceConnection:
    result = plaid_post("/item/public_token/exchange", {"public_token": public_token})
    access_token = result["access_token"]
    item_id = result["item_id"]
    institution = institution or {}
    connection, _ = FinanceConnection.objects.update_or_create(
        user=user,
        provider=FinanceConnection.Provider.PLAID,
        provider_item_id=item_id,
        defaults={
            "institution_id": institution.get("institution_id", ""),
            "institution_name": institution.get("name", ""),
            "encrypted_access_token": encrypt_token(access_token),
            "status": FinanceConnection.Status.ACTIVE,
            "last_error": "",
        },
    )
    sync_connection(connection)
    return connection


def _account_kind(account: dict) -> str:
    subtype = (account.get("subtype") or "").lower()
    mapping = {
        "checking": FinanceAccount.Kind.CHECKING,
        "savings": FinanceAccount.Kind.SAVINGS,
        "credit card": FinanceAccount.Kind.CREDIT_CARD,
        "mortgage": FinanceAccount.Kind.MORTGAGE,
        "student": FinanceAccount.Kind.STUDENT_LOAN,
        "auto": FinanceAccount.Kind.AUTO_LOAN,
    }
    return mapping.get(subtype, FinanceAccount.Kind.OTHER)


def _decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _upsert_accounts(connection: FinanceConnection, accounts: list[dict]) -> dict[str, FinanceAccount]:
    result = {}
    for item in accounts:
        balances = item.get("balances") or {}
        obj, _ = FinanceAccount.objects.update_or_create(
            user=connection.user,
            provider_account_id=item.get("account_id", ""),
            defaults={
                "connection": connection,
                "name": item.get("name") or item.get("official_name") or "Connected account",
                "official_name": item.get("official_name") or "",
                "kind": _account_kind(item),
                "mask": item.get("mask") or "",
                "currency": balances.get("iso_currency_code") or "USD",
                "current_balance": _decimal(balances.get("current")),
                "available_balance": _decimal(balances.get("available")),
                "credit_limit": _decimal(balances.get("limit")),
                "is_manual": False,
                "metadata": {"type": item.get("type"), "subtype": item.get("subtype")},
            },
        )
        result[item.get("account_id", "")] = obj
    return result


def sync_transactions(connection: FinanceConnection) -> None:
    token = decrypt_token(connection.encrypted_access_token)
    cursor = connection.cursor or None
    has_more = True
    while has_more:
        payload = {"access_token": token, "count": 500}
        if cursor:
            payload["cursor"] = cursor
        result = plaid_post("/transactions/sync", payload)
        accounts = _upsert_accounts(connection, result.get("accounts") or [])
        for tx in result.get("added") or []:
            account = accounts.get(tx.get("account_id")) or FinanceAccount.objects.filter(
                user=connection.user, provider_account_id=tx.get("account_id", "")
            ).first()
            if not account:
                continue
            amount = _decimal(tx.get("amount")) or Decimal("0")
            category = tx.get("personal_finance_category") or {}
            FinanceTransaction.objects.update_or_create(
                user=connection.user,
                provider_transaction_id=tx.get("transaction_id", ""),
                defaults={
                    "account": account,
                    "merchant_name": tx.get("merchant_name") or "",
                    "description": tx.get("name") or "",
                    "amount": amount,
                    "date": _date(tx.get("date")) or timezone.localdate(),
                    "pending": bool(tx.get("pending")),
                    "category_primary": category.get("primary") or "",
                    "category_detailed": category.get("detailed") or "",
                    "is_income": amount < 0,
                    "metadata": {"payment_channel": tx.get("payment_channel")},
                },
            )
        for tx in result.get("modified") or []:
            FinanceTransaction.objects.filter(
                user=connection.user, provider_transaction_id=tx.get("transaction_id", "")
            ).update(
                merchant_name=tx.get("merchant_name") or "",
                description=tx.get("name") or "",
                amount=_decimal(tx.get("amount")) or Decimal("0"),
                pending=bool(tx.get("pending")),
            )
        removed_ids = [x.get("transaction_id") for x in result.get("removed") or [] if x.get("transaction_id")]
        if removed_ids:
            FinanceTransaction.objects.filter(user=connection.user, provider_transaction_id__in=removed_ids).delete()
        cursor = result.get("next_cursor") or cursor
        has_more = bool(result.get("has_more"))
    connection.cursor = cursor or ""
    connection.save(update_fields=["cursor", "updated_at"])


def sync_liabilities(connection: FinanceConnection) -> None:
    token = decrypt_token(connection.encrypted_access_token)
    result = plaid_post("/liabilities/get", {"access_token": token})
    accounts = _upsert_accounts(connection, result.get("accounts") or [])
    liabilities = result.get("liabilities") or {}

    for card in liabilities.get("credit") or []:
        account = accounts.get(card.get("account_id"))
        if not account:
            continue
        FinanceLiability.objects.update_or_create(
            user=connection.user,
            account=account,
            defaults={
                "name": account.name,
                "kind": FinanceLiability.Kind.CREDIT_CARD,
                "outstanding_balance": account.current_balance,
                "minimum_payment": _decimal(card.get("minimum_payment_amount")),
                "next_payment_amount": _decimal(card.get("minimum_payment_amount")),
                "next_payment_date": _date(card.get("next_payment_due_date")),
                "apr": _decimal(((card.get("aprs") or [{}])[0]).get("apr_percentage")),
                "last_payment_amount": _decimal(card.get("last_payment_amount")),
                "last_payment_date": _date(card.get("last_payment_date")),
                "is_manual": False,
                "metadata": card,
            },
        )

    for mortgage in liabilities.get("mortgage") or []:
        account = accounts.get(mortgage.get("account_id"))
        if not account:
            continue
        FinanceLiability.objects.update_or_create(
            user=connection.user,
            account=account,
            defaults={
                "name": account.name,
                "kind": FinanceLiability.Kind.MORTGAGE,
                "lender": mortgage.get("loan_type_description") or "",
                "outstanding_balance": account.current_balance,
                "original_principal": _decimal(mortgage.get("origination_principal_amount")),
                "next_payment_amount": _decimal(mortgage.get("next_monthly_payment")),
                "next_payment_date": _date(mortgage.get("next_payment_due_date")),
                "interest_rate": _decimal((mortgage.get("interest_rate") or {}).get("percentage")),
                "origination_date": _date(mortgage.get("origination_date")),
                "maturity_date": _date(mortgage.get("maturity_date")),
                "last_payment_amount": _decimal(mortgage.get("last_payment_amount")),
                "last_payment_date": _date(mortgage.get("last_payment_date")),
                "property_address": ", ".join(filter(None, [
                    (mortgage.get("property_address") or {}).get("street"),
                    (mortgage.get("property_address") or {}).get("city"),
                    (mortgage.get("property_address") or {}).get("region"),
                    (mortgage.get("property_address") or {}).get("postal_code"),
                ])),
                "escrow_balance": _decimal(mortgage.get("escrow_balance")),
                "is_manual": False,
                "metadata": mortgage,
            },
        )

    for student in liabilities.get("student") or []:
        account = accounts.get(student.get("account_id"))
        if not account:
            continue
        FinanceLiability.objects.update_or_create(
            user=connection.user,
            account=account,
            defaults={
                "name": account.name,
                "kind": FinanceLiability.Kind.STUDENT_LOAN,
                "lender": student.get("guarantor") or "",
                "outstanding_balance": account.current_balance,
                "original_principal": _decimal(student.get("origination_principal_amount")),
                "minimum_payment": _decimal(student.get("minimum_payment_amount")),
                "next_payment_amount": _decimal(student.get("minimum_payment_amount")),
                "next_payment_date": _date(student.get("next_payment_due_date")),
                "interest_rate": _decimal(student.get("interest_rate_percentage")),
                "origination_date": _date(student.get("origination_date")),
                "last_payment_amount": _decimal(student.get("last_payment_amount")),
                "last_payment_date": _date(student.get("last_payment_date")),
                "is_manual": False,
                "metadata": student,
            },
        )


@transaction.atomic
def sync_connection(connection: FinanceConnection) -> FinanceConnection:
    try:
        sync_transactions(connection)
        sync_liabilities(connection)
        connection.status = FinanceConnection.Status.ACTIVE
        connection.last_error = ""
        connection.last_synced_at = timezone.now()
        connection.save(update_fields=["status", "last_error", "last_synced_at", "updated_at"])
    except Exception as exc:
        connection.status = FinanceConnection.Status.NEEDS_ATTENTION
        connection.last_error = str(exc)[:2000]
        connection.save(update_fields=["status", "last_error", "updated_at"])
        raise
    return connection

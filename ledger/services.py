"""Money maths in one place so views and tests agree."""
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Category, Transaction, Wallet

ZERO = Decimal("0")

DEFAULT_WALLETS = [
    ("Business", Wallet.BUSINESS, "#2563EB"),
    ("Job Salary", Wallet.SALARY, "#0F6B5A"),
    ("Offline Cash", Wallet.OFFLINE, "#C98A0B"),
    ("In-Hand Savings", Wallet.SAVINGS, "#7C3AED"),
]
DEFAULT_EXPENSE = ["Petrol", "Food", "Bills & Rent", "Shopping", "Health", "Travel", "Education",
                   "Entertainment", "EMI & Loans", "Stock & Supplies", "Wages", "Another"]
DEFAULT_INCOME = ["Salary", "Sales", "Interest", "Other Income"]


def seed_categories(user):
    for name in DEFAULT_EXPENSE:
        Category.objects.get_or_create(owner=user, name=name, kind=Category.EXPENSE)
    for name in DEFAULT_INCOME:
        Category.objects.get_or_create(owner=user, name=name, kind=Category.INCOME)


def seed_wallets(user):
    """Create a default wallet only for kinds the user does not have yet."""
    for name, kind, color in DEFAULT_WALLETS:
        if not Wallet.objects.filter(owner=user, kind=kind).exists():
            Wallet.objects.create(owner=user, name=name, kind=kind, color=color)


def seed_defaults(user):
    seed_categories(user)
    seed_wallets(user)


def parse_month(value):
    """'2026-04' -> (date(2026,4,1), date(2026,5,1)); anything else -> (None, None)."""
    if value and re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = int(value[:4]), int(value[5:])
        if 1 <= month <= 12 and year >= 1900:
            start = date(year, month, 1)
            return start, (start + timedelta(days=32)).replace(day=1)
    return None, None


def month_add(d, n):
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


def wallet_summary(user):
    """All-time balance per wallet: opening + income - expense - transfers out + transfers in."""
    inc, exp, out, inn = (defaultdict(lambda: ZERO) for _ in range(4))
    for row in Transaction.objects.filter(owner=user).values("wallet_id", "kind").annotate(t=Sum("amount")):
        {"income": inc, "expense": exp, "transfer": out}[row["kind"]][row["wallet_id"]] += row["t"]
    for row in (Transaction.objects.filter(owner=user, kind=Transaction.TRANSFER)
                .values("to_wallet_id").annotate(t=Sum("amount"))):
        inn[row["to_wallet_id"]] += row["t"]
    result = []
    for w in Wallet.objects.filter(owner=user):
        result.append({
            "wallet": w, "income": inc[w.id], "expense": exp[w.id],
            "sent": out[w.id], "received": inn[w.id],
            "balance": w.opening_balance + inc[w.id] - exp[w.id] - out[w.id] + inn[w.id],
        })
    return result


def wallet_balance(wallet):
    for row in wallet_summary(wallet.owner):
        if row["wallet"].id == wallet.id:
            return row["balance"]
    return ZERO


def income_expense(qs):
    agg = qs.filter(kind__in=[Transaction.INCOME, Transaction.EXPENSE]).aggregate(
        income=Sum("amount", filter=Q(kind=Transaction.INCOME)),
        expense=Sum("amount", filter=Q(kind=Transaction.EXPENSE)),
    )
    income, expense = agg["income"] or ZERO, agg["expense"] or ZERO
    net = income - expense
    rate = (net / income * 100) if income > 0 else None
    return {"income": income, "expense": expense, "net": net, "rate": rate}

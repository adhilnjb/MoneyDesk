"""Money maths in one place so views and tests agree."""
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction as db_tx
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Borrow, BorrowPayment, Category, Transaction, Wallet

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
    """All-time balance per wallet: opening + income - expense - transfers out + transfers in
    + borrowed money in - borrow money out (lent / repaid)."""
    inc, exp, out, inn, lin, lout = (defaultdict(lambda: ZERO) for _ in range(6))
    buckets = {"income": inc, "expense": exp, "transfer": out, "loan_in": lin, "loan_out": lout}
    for row in Transaction.objects.filter(owner=user).values("wallet_id", "kind").annotate(t=Sum("amount")):
        buckets[row["kind"]][row["wallet_id"]] += row["t"]
    for row in (Transaction.objects.filter(owner=user, kind=Transaction.TRANSFER)
                .values("to_wallet_id").annotate(t=Sum("amount"))):
        inn[row["to_wallet_id"]] += row["t"]
    result = []
    for w in Wallet.objects.filter(owner=user):
        result.append({
            "wallet": w, "income": inc[w.id], "expense": exp[w.id],
            "sent": out[w.id], "received": inn[w.id], "loan_in": lin[w.id], "loan_out": lout[w.id],
            "balance": w.opening_balance + inc[w.id] - exp[w.id] - out[w.id] + inn[w.id] + lin[w.id] - lout[w.id],
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


# ------------------------------------------------------------------ borrow / lend
def _entry_kind(direction, repayment):
    """Which way the money moves in the wallet.
    borrowed: money comes in, repaying sends it out.   lent: money goes out, getting it back brings it in."""
    money_in = (direction == Borrow.BORROWED) != repayment
    return Transaction.LOAN_IN if money_in else Transaction.LOAN_OUT


def _entry_note(borrow, repayment):
    who = borrow.person
    if borrow.direction == Borrow.BORROWED:
        return f"Repaid to {who}" if repayment else f"Borrowed from {who}"
    return f"Received back from {who}" if repayment else f"Lent to {who}"


def sync_borrow_entry(borrow):
    """Create / update / remove the wallet entry for the original amount. No wallet chosen = no entry."""
    with db_tx.atomic():
        for pay in borrow.payments.select_related("entry") if borrow.pk else []:
            if pay.entry_id and pay.entry.note != _entry_note(borrow, True):
                pay.entry.note = _entry_note(borrow, True)
                pay.entry.save(update_fields=["note"])
        if borrow.wallet_id is None:
            if borrow.entry_id:
                old, borrow.entry = borrow.entry, None
                borrow.save(update_fields=["entry"])
                old.delete()
            return
        fields = dict(kind=_entry_kind(borrow.direction, False), wallet=borrow.wallet, amount=borrow.amount,
                      date=borrow.date, note=_entry_note(borrow, False), category=None, to_wallet=None)
        if borrow.entry_id:
            for k, v in fields.items():
                setattr(borrow.entry, k, v)
            borrow.entry.save()
        else:
            borrow.entry = Transaction.objects.create(owner=borrow.owner, **fields)
            borrow.save(update_fields=["entry"])


def refresh_cleared(borrow):
    """Stamp / clear the cleared date from the real payments."""
    borrow = Borrow.objects.prefetch_related("payments").get(pk=borrow.pk)
    done = borrow.is_cleared
    if done and borrow.cleared_on is None:
        last = borrow.payments.first()
        borrow.cleared_on = last.date if last else timezone.localdate()
    elif not done:
        borrow.cleared_on = None
    else:
        return borrow
    borrow.save(update_fields=["cleared_on"])
    return borrow


def record_payment(borrow, amount, date, wallet=None, note=""):
    """Add a repayment. If a wallet is given, the matching wallet entry is created automatically."""
    with db_tx.atomic():
        payment = BorrowPayment.objects.create(borrow=borrow, amount=amount, date=date, note=note)
        if wallet is not None:
            payment.entry = Transaction.objects.create(
                owner=borrow.owner, kind=_entry_kind(borrow.direction, True), wallet=wallet, amount=amount,
                date=date, note=_entry_note(borrow, True))
            payment.save(update_fields=["entry"])
        refresh_cleared(borrow)
    return payment


def clear_borrow(borrow):
    """One-tap 'Cleared': settle whatever is left, using the borrow's own wallet (if it has one)."""
    borrow = Borrow.objects.prefetch_related("payments").select_related("wallet").get(pk=borrow.pk)
    if borrow.balance <= 0:
        return None
    return record_payment(borrow, borrow.balance, timezone.localdate(), borrow.wallet, "Cleared")


def borrow_totals(user):
    """What you owe and what is owed to you, from open borrows only."""
    owe = owed = ZERO
    open_count = 0
    for b in Borrow.objects.filter(owner=user, cleared_on__isnull=True).prefetch_related("payments"):
        if b.is_cleared:
            continue
        open_count += 1
        if b.direction == Borrow.BORROWED:
            owe += b.balance
        else:
            owed += b.balance
    return {"owe": owe, "owed": owed, "net": owed - owe, "open": open_count}

import csv
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Max, Q, Sum
from django.db.models.deletion import ProtectedError
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services as svc
from .forms import BudgetForm, CategoryForm, TransactionForm, TransferForm, WalletForm
from .models import Budget, Category, Transaction, Wallet

ZERO = Decimal("0")
INC_EXP = [Transaction.INCOME, Transaction.EXPENSE]


def _month_choices():
    today = timezone.localdate().replace(day=1)
    return [(svc.month_add(today, -i).strftime("%Y-%m"), svc.month_add(today, -i).strftime("%B %Y"))
            for i in range(0, 18)]


def _warn_if_negative(request, wallet):
    balance = svc.wallet_balance(wallet)
    if balance < 0:
        messages.warning(request, f"{wallet.name} is now below zero. Check the entries or add an opening balance.")


# ---------------------------------------------------------------- dashboard
@login_required
def dashboard(request):
    user = request.user
    if not Wallet.objects.filter(owner=user).exists():
        svc.seed_defaults(user)

    latest = Transaction.objects.filter(owner=user).aggregate(m=Max("date"))["m"] or timezone.localdate()
    month = request.GET.get("month") or latest.strftime("%Y-%m")
    start, end = svc.parse_month(month)
    if month != "all" and start is None:
        month = latest.strftime("%Y-%m")
        start, end = svc.parse_month(month)

    period = Transaction.objects.filter(owner=user)
    if start:
        period = period.filter(date__gte=start, date__lt=end)
    totals = svc.income_expense(period)
    ref = start or latest.replace(day=1)  # month used for trend and budgets

    # wallet cards: all-time balance + this period's movement
    moved = {}
    for row in period.filter(kind__in=INC_EXP).values("wallet_id", "kind").annotate(t=Sum("amount")):
        moved.setdefault(row["wallet_id"], {})[row["kind"]] = row["t"]
    summary = [s for s in svc.wallet_summary(user) if not s["wallet"].archived]
    for s in summary:
        s["p_income"] = moved.get(s["wallet"].id, {}).get("income", ZERO)
        s["p_expense"] = moved.get(s["wallet"].id, {}).get("expense", ZERO)
    total_balance = sum((s["balance"] for s in summary), ZERO)
    positive_total = sum((s["balance"] for s in summary if s["balance"] > 0), ZERO)
    for s in summary:
        s["share"] = float(s["balance"] / positive_total * 100) if positive_total > 0 and s["balance"] > 0 else 0

    # expense by category
    cats = list(period.filter(kind=Transaction.EXPENSE).values("category__name")
                .annotate(t=Sum("amount")).order_by("-t"))
    top = cats[0]["t"] if cats else ZERO
    for c in cats:
        c["name"] = c["category__name"] or "Uncategorised"
        c["width"] = float(c["t"] / top * 100) if top else 0
        c["share"] = float(c["t"] / totals["expense"] * 100) if totals["expense"] else 0

    # six month trend
    first = svc.month_add(ref, -5)
    trend_rows = (Transaction.objects.filter(owner=user, kind__in=INC_EXP, date__gte=first, date__lt=svc.month_add(ref, 1))
                  .annotate(m=TruncMonth("date")).values("m", "kind").annotate(t=Sum("amount")))
    grid = {svc.month_add(first, i): {"income": 0.0, "expense": 0.0} for i in range(6)}
    for r in trend_rows:
        grid[r["m"]][r["kind"]] = float(r["t"])
    trend = {"labels": [m.strftime("%b %y") for m in grid],
             "income": [v["income"] for v in grid.values()], "expense": [v["expense"] for v in grid.values()]}

    # budgets for the reference month
    spent = {r["category_id"]: r["t"] for r in Transaction.objects.filter(
        owner=user, kind=Transaction.EXPENSE, date__gte=ref, date__lt=svc.month_add(ref, 1))
        .values("category_id").annotate(t=Sum("amount"))}
    budgets = []
    for b in Budget.objects.filter(owner=user).select_related("category"):
        used = spent.get(b.category_id, ZERO)
        p = float(used / b.amount * 100)
        budgets.append({"budget": b, "used": used, "pct": p, "bar": min(p, 100), "over": p > 100, "near": 80 <= p <= 100})

    salary = next((s for s in summary if s["wallet"].kind == Wallet.SALARY), None)
    savings = next((s for s in summary if s["wallet"].kind == Wallet.SAVINGS), None)
    recent = Transaction.objects.filter(owner=user).select_related("wallet", "to_wallet", "category")[:8]

    return render(request, "ledger/dashboard.html", {
        "month": month, "months": _month_choices(), "period_label": ref.strftime("%B %Y") if start else "All time",
        "totals": totals, "summary": summary, "total_balance": total_balance, "cats": cats, "trend": trend,
        "budgets": budgets, "recent": recent, "salary": salary, "savings": savings, "ref_label": ref.strftime("%B %Y"),
    })


# ------------------------------------------------------------- transactions
def _filtered(request):
    qs = Transaction.objects.filter(owner=request.user).select_related("wallet", "to_wallet", "category")
    g = request.GET
    if g.get("wallet", "").isdigit():
        qs = qs.filter(Q(wallet_id=g["wallet"]) | Q(to_wallet_id=g["wallet"]))
    if g.get("kind") in {"income", "expense", "transfer"}:
        qs = qs.filter(kind=g["kind"])
    if g.get("category", "").isdigit():
        qs = qs.filter(category_id=g["category"])
    start, end = svc.parse_month(g.get("month"))
    if start:
        qs = qs.filter(date__gte=start, date__lt=end)
    for key, op in (("from", "date__gte"), ("to", "date__lte")):
        try:
            qs = qs.filter(**{op: date.fromisoformat(g.get(key, ""))})
        except ValueError:
            pass
    q = g.get("q", "").strip()
    if q:
        qs = qs.filter(Q(note__icontains=q) | Q(category__name__icontains=q) | Q(wallet__name__icontains=q))
    return qs


@login_required
def transaction_list(request):
    qs = _filtered(request)
    totals = svc.income_expense(qs)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "ledger/transactions.html", {
        "page": page, "totals": totals, "months": _month_choices(), "querystring": params.urlencode(),
        "wallets": Wallet.objects.filter(owner=request.user), "categories": Category.objects.filter(owner=request.user),
        "f": request.GET,
    })


def _csv_safe(text):
    text = str(text or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@login_required
def export_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="moneydesk-transactions.csv"'
    writer = csv.writer(response)
    writer.writerow(["Date", "Type", "Wallet", "To wallet", "Category", "Amount", "Note"])
    for t in _filtered(request):
        writer.writerow([t.date.isoformat(), t.kind, _csv_safe(t.wallet.name), _csv_safe(t.to_wallet.name if t.to_wallet else ""),
                         _csv_safe(t.category.name if t.category else ""), t.amount, _csv_safe(t.note)])
    return response


@login_required
def transaction_form(request, pk=None):
    instance = get_object_or_404(Transaction, pk=pk, owner=request.user) if pk else None
    if instance and instance.kind == Transaction.TRANSFER:
        return redirect("ledger:transfer_edit", pk=pk)
    initial = {}
    if not instance:
        if request.GET.get("kind") in {"income", "expense"}:
            initial["kind"] = request.GET["kind"]
        if request.GET.get("wallet", "").isdigit():
            initial["wallet"] = request.GET["wallet"]
        initial.setdefault("kind", "expense")
    form = TransactionForm(request.POST or None, instance=instance, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        messages.success(request, "Entry saved.")
        _warn_if_negative(request, obj.wallet)
        return redirect("ledger:transactions")
    kinds = {c.id: c.kind for c in Category.objects.filter(owner=request.user)}
    return render(request, "ledger/transaction_form.html", {"form": form, "instance": instance, "category_kinds": kinds})


@login_required
def transfer_form(request, pk=None):
    instance = get_object_or_404(Transaction, pk=pk, owner=request.user, kind=Transaction.TRANSFER) if pk else None
    initial = {}
    if not instance and request.GET.get("preset") == "salary_withdrawal":
        wallets = Wallet.objects.filter(owner=request.user, archived=False)
        src, dst = wallets.filter(kind=Wallet.SALARY).first(), wallets.filter(kind=Wallet.SAVINGS).first()
        initial = {"wallet": src, "to_wallet": dst, "note": "Salary withdrawal"}
    form = TransferForm(request.POST or None, instance=instance, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner, obj.kind, obj.category = request.user, Transaction.TRANSFER, None
        obj.save()
        messages.success(request, "Transfer saved.")
        _warn_if_negative(request, obj.wallet)
        return redirect("ledger:transactions")
    return render(request, "ledger/transfer_form.html", {"form": form, "instance": instance})


@login_required
def transaction_delete(request, pk):
    obj = get_object_or_404(Transaction, pk=pk, owner=request.user)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Entry deleted.")
        return redirect("ledger:transactions")
    return render(request, "ledger/confirm_delete.html", {"title": "Delete this entry?", "object": str(obj), "back": "ledger:transactions"})


# ------------------------------------------------ wallets / categories / budgets
def _crud(request, model, form_class, pk, template_title, list_name):
    instance = get_object_or_404(model, pk=pk, owner=request.user) if pk else None
    form = form_class(request.POST or None, instance=instance, user=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.owner = request.user
        obj.save()
        messages.success(request, "Saved.")
        return redirect(list_name)
    return render(request, "ledger/form.html", {"form": form, "title": template_title, "back": list_name})


@login_required
def wallet_list(request):
    return render(request, "ledger/wallets.html", {"summary": svc.wallet_summary(request.user)})


@login_required
def wallet_form(request, pk=None):
    return _crud(request, Wallet, WalletForm, pk, "Edit wallet" if pk else "New wallet", "ledger:wallets")


@login_required
@require_POST
def wallet_archive(request, pk):
    wallet = get_object_or_404(Wallet, pk=pk, owner=request.user)
    wallet.archived = not wallet.archived
    wallet.save(update_fields=["archived"])
    messages.success(request, f"{wallet.name} {'archived' if wallet.archived else 'restored'}.")
    return redirect("ledger:wallets")


@login_required
def wallet_delete(request, pk):
    wallet = get_object_or_404(Wallet, pk=pk, owner=request.user)
    if request.method == "POST":
        try:
            wallet.delete()
            messages.success(request, "Wallet deleted.")
        except ProtectedError:
            messages.error(request, "This wallet has entries. Archive it instead.")
        return redirect("ledger:wallets")
    return render(request, "ledger/confirm_delete.html", {"title": "Delete this wallet?", "object": wallet.name, "back": "ledger:wallets"})


@login_required
def category_list(request):
    return render(request, "ledger/categories.html", {"categories": Category.objects.filter(owner=request.user)})


@login_required
def category_form(request, pk=None):
    return _crud(request, Category, CategoryForm, pk, "Edit category" if pk else "New category", "ledger:categories")


@login_required
def category_delete(request, pk):
    obj = get_object_or_404(Category, pk=pk, owner=request.user)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Category deleted. Its entries are now uncategorised.")
        return redirect("ledger:categories")
    return render(request, "ledger/confirm_delete.html", {"title": "Delete this category?", "object": obj.name, "back": "ledger:categories"})


@login_required
def budget_list(request):
    return render(request, "ledger/budgets.html", {"budgets": Budget.objects.filter(owner=request.user).select_related("category")})


@login_required
def budget_form(request, pk=None):
    return _crud(request, Budget, BudgetForm, pk, "Edit budget" if pk else "New monthly budget", "ledger:budgets")


@login_required
def budget_delete(request, pk):
    obj = get_object_or_404(Budget, pk=pk, owner=request.user)
    if request.method == "POST":
        obj.delete()
        return redirect("ledger:budgets")
    return render(request, "ledger/confirm_delete.html", {"title": "Delete this budget?", "object": str(obj), "back": "ledger:budgets"})


# ------------------------------------------------------------------ reports
@login_required
def reports(request):
    today = timezone.localdate()
    default_fy = today.year if today.month >= 4 else today.year - 1
    latest = Transaction.objects.filter(owner=request.user).aggregate(m=Max("date"))["m"]
    if latest and "fy" not in request.GET:
        default_fy = latest.year if latest.month >= 4 else latest.year - 1
    try:
        fy = int(request.GET.get("fy", default_fy))
    except ValueError:
        fy = default_fy
    start, end = date(fy, 4, 1), date(fy + 1, 4, 1)
    qs = Transaction.objects.filter(owner=request.user, kind__in=INC_EXP, date__gte=start, date__lt=end)

    grid = {svc.month_add(start, i): {"income": ZERO, "expense": ZERO} for i in range(12)}
    for r in qs.annotate(m=TruncMonth("date")).values("m", "kind").annotate(t=Sum("amount")):
        grid[r["m"]][r["kind"]] = r["t"]
    months = [{"label": m.strftime("%B %Y"), "income": v["income"], "expense": v["expense"], "net": v["income"] - v["expense"]}
              for m, v in grid.items()]

    by_wallet = {}
    for r in qs.values("wallet__name", "kind").annotate(t=Sum("amount")):
        by_wallet.setdefault(r["wallet__name"], {"income": ZERO, "expense": ZERO})[r["kind"]] = r["t"]
    wallets = [{"name": n, **v, "net": v["income"] - v["expense"]} for n, v in by_wallet.items()]

    by_cat = list(qs.filter(kind=Transaction.EXPENSE).values("category__name").annotate(t=Sum("amount")).order_by("-t"))
    for c in by_cat:
        c["name"] = c["category__name"] or "Uncategorised"

    chart = {"labels": [m["label"][:3] for m in months], "income": [float(m["income"]) for m in months],
             "expense": [float(m["expense"]) for m in months]}
    return render(request, "ledger/reports.html", {
        "fy": fy, "fy_label": f"Apr {fy} – Mar {fy + 1}", "years": range(default_fy + 1, default_fy - 5, -1),
        "months": months, "wallets": wallets, "by_cat": by_cat, "totals": svc.income_expense(qs), "chart": chart,
    })

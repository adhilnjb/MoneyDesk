from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


def money(**kwargs):
    return models.DecimalField(max_digits=12, decimal_places=2, **kwargs)


class Wallet(models.Model):
    """One pot of money: business, job salary, offline cash, in-hand savings..."""
    BUSINESS, SALARY, OFFLINE, SAVINGS = "business", "salary", "offline", "savings"
    KINDS = [
        (BUSINESS, "Business"),
        (SALARY, "Job salary"),
        (OFFLINE, "Offline / cash"),
        (SAVINGS, "In-hand savings"),
    ]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallets")
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=KINDS)
    opening_balance = money(default=Decimal("0"))
    color = models.CharField(
        max_length=7, default="#0F6B5A",
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use a colour like #0F6B5A.")],
    )
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["archived", "id"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_wallet_name_per_owner")]

    def __str__(self):
        return self.name


class Category(models.Model):
    INCOME, EXPENSE = "income", "expense"
    KINDS = [(INCOME, "Income"), (EXPENSE, "Expense")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=40)
    kind = models.CharField(max_length=7, choices=KINDS)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(fields=["owner", "name", "kind"], name="uniq_category_per_owner")]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    INCOME, EXPENSE, TRANSFER = "income", "expense", "transfer"
    # Borrow / lend money moves a wallet balance but is never income or expense.
    LOAN_IN, LOAN_OUT = "loan_in", "loan_out"
    KINDS = [(INCOME, "Income"), (EXPENSE, "Expense"), (TRANSFER, "Transfer"),
             (LOAN_IN, "Borrow in"), (LOAN_OUT, "Borrow out")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=8, choices=KINDS)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    to_wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, null=True, blank=True, related_name="incoming")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    amount = money(validators=[MinValueValidator(Decimal("0.01"))])
    date = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["owner", "date"]), models.Index(fields=["owner", "kind"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} on {self.date}"

    @property
    def is_loan(self):
        return self.kind in (self.LOAN_IN, self.LOAN_OUT)

    @property
    def linked_borrow(self):
        """The Borrow this auto entry belongs to (None for normal entries)."""
        if not self.is_loan:
            return None
        origin = Borrow.objects.filter(entry=self).first()
        if origin:
            return origin
        pay = BorrowPayment.objects.filter(entry=self).select_related("borrow").first()
        return pay.borrow if pay else None

    def clean(self):
        if self.kind == self.TRANSFER:
            if not self.to_wallet_id:
                raise ValidationError({"to_wallet": "Choose where the money goes."})
            if self.to_wallet_id == self.wallet_id:
                raise ValidationError({"to_wallet": "Pick a different wallet."})
            self.category = None
        else:
            self.to_wallet = None
            if self.category_id and self.category.kind != self.kind:
                raise ValidationError({"category": f"Pick a {self.kind} category."})


class Budget(models.Model):
    """Monthly spending limit for one expense category."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budgets")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="budgets")
    amount = money(validators=[MinValueValidator(Decimal("1"))])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "category"], name="uniq_budget_per_category")]
        ordering = ["category__name"]

    def __str__(self):
        return f"{self.category} ≤ {self.amount}"


class Borrow(models.Model):
    """Money borrowed from someone (you owe) or lent to someone (they owe you)."""
    BORROWED, LENT = "borrowed", "lent"
    DIRECTIONS = [(BORROWED, "I borrowed"), (LENT, "I lent")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="borrows")
    direction = models.CharField(max_length=8, choices=DIRECTIONS, default=BORROWED)
    person = models.CharField(max_length=80)
    amount = money(validators=[MinValueValidator(Decimal("0.01"))])
    date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    # Optional: the wallet that receives / gives the money. Empty = no wallet entry is made.
    wallet = models.ForeignKey(Wallet, on_delete=models.SET_NULL, null=True, blank=True, related_name="borrows")
    entry = models.OneToOneField("Transaction", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cleared_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["owner", "cleared_on"])]
        verbose_name_plural = "borrows"

    def __str__(self):
        return f"{self.get_direction_display()} {self.amount} · {self.person}"

    @property
    def paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0"))

    @property
    def balance(self):
        return max(self.amount - self.paid, Decimal("0"))

    @property
    def is_cleared(self):
        return self.balance <= 0

    @property
    def progress(self):
        return float(min(self.paid / self.amount * 100, 100)) if self.amount else 0.0

    @property
    def overdue(self):
        return bool(self.due_date and not self.is_cleared and self.due_date < timezone.localdate())


class BorrowPayment(models.Model):
    """One repayment (partial or full) against a Borrow."""
    borrow = models.ForeignKey(Borrow, on_delete=models.CASCADE, related_name="payments")
    amount = money(validators=[MinValueValidator(Decimal("0.01"))])
    date = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)
    entry = models.OneToOneField(Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.amount} on {self.date}"

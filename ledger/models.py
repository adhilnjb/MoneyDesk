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
    KINDS = [(INCOME, "Income"), (EXPENSE, "Expense"), (TRANSFER, "Transfer")]

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

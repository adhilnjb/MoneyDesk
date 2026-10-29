from django import forms

from decimal import Decimal

from django.utils import timezone

from .models import Borrow, BorrowPayment, Budget, Category, Transaction, Wallet


class UserModelForm(forms.ModelForm):
    """ModelForm that knows the current user, so every choice list is limited to their own data."""

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.RadioSelect, forms.CheckboxInput)):
                field.widget.attrs.setdefault("class", "input")

    def _unique_or_error(self, field, **lookup):
        qs = self._meta.model.objects.filter(owner=self.user, **lookup)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            self.add_error(field, "You already have one with this name.")


class WalletForm(UserModelForm):
    class Meta:
        model = Wallet
        fields = ["name", "kind", "opening_balance", "color"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}

    def clean(self):
        data = super().clean()
        if data.get("name"):
            self._unique_or_error("name", name=data["name"])
        return data


class CategoryForm(UserModelForm):
    class Meta:
        model = Category
        fields = ["name", "kind"]

    def clean(self):
        data = super().clean()
        if data.get("name") and data.get("kind"):
            self._unique_or_error("name", name=data["name"], kind=data["kind"])
        return data


class BudgetForm(UserModelForm):
    class Meta:
        model = Budget
        fields = ["category", "amount"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(owner=self.user, kind=Category.EXPENSE)

    def clean(self):
        data = super().clean()
        if data.get("category"):
            self._unique_or_error("category", category=data["category"])
        return data


class _WalletChoiceMixin:
    def _limit_wallets(self, *names):
        qs = Wallet.objects.filter(owner=self.user, archived=False)
        if self.instance.pk:  # keep the wallet already used, even if archived later
            qs = Wallet.objects.filter(owner=self.user).filter(
                id__in=[w.id for w in qs] + [self.instance.wallet_id, self.instance.to_wallet_id])
        for name in names:
            self.fields[name].queryset = qs
            self.fields[name].empty_label = "Choose wallet" if name == "wallet" else "Choose destination wallet"


class TransactionForm(_WalletChoiceMixin, UserModelForm):
    class Meta:
        model = Transaction
        fields = ["kind", "wallet", "category", "amount", "date", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal", "class": "input amount"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [(Transaction.INCOME, "Income"), (Transaction.EXPENSE, "Expense")]
        self.fields["category"].queryset = Category.objects.filter(owner=self.user)
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Choose category"
        self._limit_wallets("wallet")


class TransferForm(_WalletChoiceMixin, UserModelForm):
    """Move money between wallets, e.g. salary withdrawn into in-hand savings."""

    class Meta:
        model = Transaction
        fields = ["wallet", "to_wallet", "amount", "date", "note"]
        labels = {"wallet": "From", "to_wallet": "To"}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal", "class": "input amount"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.kind = Transaction.TRANSFER
        self.fields["to_wallet"].required = True
        self._limit_wallets("wallet", "to_wallet")


class BorrowForm(UserModelForm):
    """Borrow from / lend to someone. Pick a wallet and the amount is entered there automatically."""

    class Meta:
        model = Borrow
        fields = ["direction", "person", "amount", "date", "due_date", "wallet", "note"]
        labels = {"person": "Person", "due_date": "Due date (optional)", "wallet": "Add to wallet (auto entry)",
                  "note": "Note (optional)"}
        widgets = {
            "direction": forms.RadioSelect,
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal", "class": "input amount"}),
            "person": forms.TextInput(attrs={"list": "people", "autocomplete": "off", "placeholder": "Name"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["direction"].choices = Borrow.DIRECTIONS
        self.fields["wallet"].required = False
        self.fields["wallet"].empty_label = "Don't add to any wallet"
        self.fields["due_date"].required = False
        self._limit_wallets("wallet")
        if self.instance.pk:  # who owes whom cannot flip once repayments exist
            self.fields["direction"].disabled = self.instance.payments.exists()

    def _limit_wallets(self, *names):  # Borrow has no to_wallet, so build the list here
        qs = Wallet.objects.filter(owner=self.user, archived=False)
        if self.instance.pk and self.instance.wallet_id:
            qs = Wallet.objects.filter(owner=self.user).filter(
                id__in=[w.id for w in qs] + [self.instance.wallet_id])
        for name in names:
            self.fields[name].queryset = qs

    def clean_person(self):
        return self.cleaned_data["person"].strip()

    def clean(self):
        data = super().clean()
        amount, due, date = data.get("amount"), data.get("due_date"), data.get("date")
        if self.instance.pk and amount is not None and amount < self.instance.paid:
            self.add_error("amount", f"Already repaid {self.instance.paid:,.2f}. The amount cannot be lower.")
        if due and date and due < date:
            self.add_error("due_date", "Due date is before the borrow date.")
        return data


class BorrowPaymentForm(UserModelForm):
    """Repay (or collect) any amount up to the balance. The wallet is optional."""
    wallet = forms.ModelChoiceField(queryset=Wallet.objects.none(), required=False,
                                    empty_label="Don't add to any wallet", label="Add to wallet (auto entry)")

    class Meta:
        model = BorrowPayment
        fields = ["amount", "date", "wallet", "note"]
        labels = {"amount": "Amount (optional: leave the full balance or enter less)", "note": "Note (optional)"}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal", "class": "input amount"}),
        }

    def __init__(self, *args, borrow, **kwargs):
        super().__init__(*args, **kwargs)
        self.borrow = borrow
        self.fields["wallet"].queryset = Wallet.objects.filter(owner=self.user, archived=False)
        if not self.is_bound:
            self.initial.setdefault("amount", borrow.balance)
            self.initial.setdefault("date", timezone.localdate())
            self.initial.setdefault("wallet", borrow.wallet_id)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount > self.borrow.balance:
            raise forms.ValidationError(f"Only {self.borrow.balance:,.2f} is left to settle.")
        return amount

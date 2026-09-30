from django import forms

from .models import Budget, Category, Transaction, Wallet


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


class TransactionForm(_WalletChoiceMixin, UserModelForm):
    class Meta:
        model = Transaction
        fields = ["kind", "wallet", "category", "amount", "date", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [(Transaction.INCOME, "Income"), (Transaction.EXPENSE, "Expense")]
        self.fields["category"].queryset = Category.objects.filter(owner=self.user)
        self.fields["category"].required = False
        self._limit_wallets("wallet")


class TransferForm(_WalletChoiceMixin, UserModelForm):
    """Move money between wallets, e.g. salary withdrawn into in-hand savings."""

    class Meta:
        model = Transaction
        fields = ["wallet", "to_wallet", "amount", "date", "note"]
        labels = {"wallet": "From", "to_wallet": "To"}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.kind = Transaction.TRANSFER
        self.fields["to_wallet"].required = True
        self._limit_wallets("wallet", "to_wallet")

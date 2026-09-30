from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import services as svc
from .models import Category, Transaction, Wallet

User = get_user_model()


class LedgerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("adhi", "a@example.com", "s3cure-pass-123")
        svc.seed_defaults(self.user)
        self.salary = Wallet.objects.get(owner=self.user, kind="salary")
        self.savings = Wallet.objects.get(owner=self.user, kind="savings")
        self.client.force_login(self.user)

    def test_salary_withdrawal_moves_money_without_changing_income(self):
        cat = Category.objects.get(owner=self.user, name="Salary")
        Transaction.objects.create(owner=self.user, kind="income", wallet=self.salary, category=cat, amount=50000, date=date(2026, 4, 1))
        resp = self.client.post(reverse("ledger:transfer_new"), {
            "wallet": self.salary.id, "to_wallet": self.savings.id, "amount": "20000", "date": "2026-04-05", "note": "Salary withdrawal"})
        self.assertEqual(resp.status_code, 302)
        bal = {s["wallet"].kind: s["balance"] for s in svc.wallet_summary(self.user)}
        self.assertEqual(bal["salary"], Decimal("30000"))
        self.assertEqual(bal["savings"], Decimal("20000"))
        totals = svc.income_expense(Transaction.objects.filter(owner=self.user))
        self.assertEqual((totals["income"], totals["expense"]), (Decimal("50000"), Decimal("0")))

    def test_transfer_to_same_wallet_is_rejected(self):
        resp = self.client.post(reverse("ledger:transfer_new"), {
            "wallet": self.salary.id, "to_wallet": self.salary.id, "amount": "10", "date": "2026-04-05"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_category_kind_must_match(self):
        exp_cat = Category.objects.get(owner=self.user, name="Food")
        resp = self.client.post(reverse("ledger:transaction_new"), {
            "kind": "income", "wallet": self.salary.id, "category": exp_cat.id, "amount": "10", "date": "2026-04-05"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_other_users_data_is_invisible(self):
        other = User.objects.create_user("eve", "e@example.com", "s3cure-pass-123")
        svc.seed_defaults(other)
        w = Wallet.objects.filter(owner=other).first()
        t = Transaction.objects.create(owner=other, kind="expense", wallet=w, amount=5, date=date(2026, 4, 1))
        self.assertEqual(self.client.get(reverse("ledger:transaction_edit", args=[t.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("ledger:transaction_delete", args=[t.pk])).status_code, 404)
        # cannot post an entry into someone else's wallet
        cat = Category.objects.filter(owner=self.user, kind="expense").first()
        resp = self.client.post(reverse("ledger:transaction_new"), {
            "kind": "expense", "wallet": w.id, "category": cat.id, "amount": "5", "date": "2026-04-01"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Transaction.objects.filter(owner=self.user).count(), 0)

    def test_every_page_renders(self):
        Transaction.objects.create(owner=self.user, kind="expense", wallet=self.salary, amount=5, date=date(2026, 4, 1),
                                   category=Category.objects.get(owner=self.user, name="Food"))
        for name in ["dashboard", "transactions", "transaction_new", "transfer_new", "wallets", "wallet_new",
                     "categories", "category_new", "budgets", "budget_new", "reports", "export"]:
            self.assertEqual(self.client.get(reverse(f"ledger:{name}")).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("ledger:dashboard") + "?month=all").status_code, 200)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("ledger:dashboard")).status_code, 302)

    def test_csv_export_neutralises_formulas(self):
        Transaction.objects.create(owner=self.user, kind="expense", wallet=self.salary, amount=5, date=date(2026, 4, 1), note="=HYPERLINK(1)")
        body = self.client.get(reverse("ledger:export")).content.decode()
        self.assertIn("'=HYPERLINK(1)", body)

    def test_indian_number_format(self):
        from .templatetags.money import inr
        self.assertEqual(inr(Decimal("1234567.5")), "₹12,34,567.50")
        self.assertEqual(inr(Decimal("-999")), "-₹999")

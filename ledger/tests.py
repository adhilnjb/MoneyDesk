from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import services as svc
from .models import Borrow, Category, Transaction, Wallet

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


class BorrowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("adhi", "a@example.com", "s3cure-pass-123")
        svc.seed_defaults(self.user)
        self.cash = Wallet.objects.get(owner=self.user, kind="offline")
        self.client.force_login(self.user)

    def bal(self):
        return {s["wallet"].id: s["balance"] for s in svc.wallet_summary(self.user)}[self.cash.id]

    def make(self, direction="borrowed", amount="1000", wallet=True, **extra):
        data = {"direction": direction, "person": "Ravi", "amount": amount, "date": "2026-10-01",
                "wallet": self.cash.id if wallet else "", **extra}
        resp = self.client.post(reverse("ledger:borrow_new"), data)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors)
        return Borrow.objects.get(owner=self.user)

    def test_borrowed_adds_money_in_and_is_not_income(self):
        b = self.make("borrowed", "1000")
        self.assertEqual(self.bal(), Decimal("1000"))
        self.assertEqual(b.entry.kind, "loan_in")
        totals = svc.income_expense(Transaction.objects.filter(owner=self.user))
        self.assertEqual((totals["income"], totals["expense"]), (Decimal("0"), Decimal("0")))

    def test_lent_takes_money_out(self):
        self.make("lent", "400")
        self.assertEqual(self.bal(), Decimal("-400"))

    def test_no_wallet_means_no_entry(self):
        b = self.make("borrowed", "500", wallet=False)
        self.assertIsNone(b.entry)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.bal(), Decimal("0"))

    def test_partial_payment_then_one_tap_cleared(self):
        b = self.make("borrowed", "1000")
        resp = self.client.post(reverse("ledger:borrow_pay", args=[b.pk]),
                                {"amount": "300", "date": "2026-10-05", "wallet": self.cash.id})
        self.assertEqual(resp.status_code, 302)
        b = Borrow.objects.prefetch_related("payments").get(pk=b.pk)
        self.assertEqual((b.paid, b.balance, b.is_cleared), (Decimal("300"), Decimal("700"), False))
        self.assertEqual(self.bal(), Decimal("700"))
        self.client.post(reverse("ledger:borrow_clear", args=[b.pk]))
        b = Borrow.objects.prefetch_related("payments").get(pk=b.pk)
        self.assertTrue(b.is_cleared)
        self.assertIsNotNone(b.cleared_on)
        self.assertEqual(self.bal(), Decimal("0"))  # borrowed 1000, repaid 300 + 700

    def test_lent_money_comes_back_in_when_cleared(self):
        b = self.make("lent", "250")
        self.client.post(reverse("ledger:borrow_clear", args=[b.pk]))
        self.assertEqual(self.bal(), Decimal("0"))
        self.assertEqual(Transaction.objects.filter(kind="loan_in").count(), 1)

    def test_cannot_pay_more_than_balance(self):
        b = self.make("borrowed", "100")
        resp = self.client.post(reverse("ledger:borrow_pay", args=[b.pk]),
                                {"amount": "100.01", "date": "2026-10-05", "wallet": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b.payments.count(), 0)

    def test_pay_without_wallet_changes_only_the_balance_owed(self):
        b = self.make("borrowed", "100")
        self.client.post(reverse("ledger:borrow_pay", args=[b.pk]), {"amount": "40", "date": "2026-10-05", "wallet": ""})
        self.assertEqual(self.bal(), Decimal("100"))
        self.assertEqual(Borrow.objects.prefetch_related("payments").get(pk=b.pk).balance, Decimal("60"))

    def test_undo_payment_reopens_and_removes_its_entry(self):
        b = self.make("borrowed", "100")
        self.client.post(reverse("ledger:borrow_clear", args=[b.pk]))
        pay = b.payments.get()
        self.client.post(reverse("ledger:borrow_payment_delete", args=[pay.pk]))
        b = Borrow.objects.prefetch_related("payments").get(pk=b.pk)
        self.assertFalse(b.is_cleared)
        self.assertIsNone(b.cleared_on)
        self.assertEqual(self.bal(), Decimal("100"))

    def test_deleting_a_borrow_removes_all_its_entries(self):
        b = self.make("borrowed", "100")
        self.client.post(reverse("ledger:borrow_pay", args=[b.pk]), {"amount": "30", "date": "2026-10-05", "wallet": self.cash.id})
        self.client.post(reverse("ledger:borrow_delete", args=[b.pk]))
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.bal(), Decimal("0"))

    def test_editing_amount_updates_the_wallet_entry_but_not_below_paid(self):
        b = self.make("borrowed", "100")
        self.client.post(reverse("ledger:borrow_pay", args=[b.pk]), {"amount": "60", "date": "2026-10-05", "wallet": ""})
        base = {"direction": "borrowed", "person": "Ravi", "date": "2026-10-01", "wallet": self.cash.id}
        self.assertEqual(self.client.post(reverse("ledger:borrow_edit", args=[b.pk]), {**base, "amount": "50"}).status_code, 200)
        self.assertEqual(self.client.post(reverse("ledger:borrow_edit", args=[b.pk]), {**base, "amount": "200"}).status_code, 302)
        self.assertEqual(self.bal(), Decimal("200"))

    def test_auto_entries_are_managed_from_borrow_page(self):
        b = self.make("borrowed", "100")
        for name in ("transaction_edit", "transaction_delete"):
            resp = self.client.post(reverse(f"ledger:{name}", args=[b.entry_id]))
            self.assertRedirects(resp, reverse("ledger:borrow_list"), fetch_redirect_response=False)
        self.assertTrue(Transaction.objects.filter(pk=b.entry_id).exists())

    def test_other_users_borrows_are_invisible(self):
        b = self.make("borrowed", "100")
        self.client.logout()
        eve = User.objects.create_user("eve", "e@example.com", "s3cure-pass-123")
        self.client.force_login(eve)
        for name in ("borrow_edit", "borrow_pay", "borrow_delete"):
            self.assertEqual(self.client.get(reverse(f"ledger:{name}", args=[b.pk])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse("ledger:borrow_clear", args=[b.pk])).status_code, 404)

    def test_borrow_pages_render(self):
        b = self.make("lent", "100", due_date="2026-10-10")
        self.client.post(reverse("ledger:borrow_pay", args=[b.pk]), {"amount": "10", "date": "2026-10-05", "wallet": ""})
        for url in (reverse("ledger:borrow_list"), reverse("ledger:borrow_list") + "?status=all&who=lent",
                    reverse("ledger:borrow_new"), reverse("ledger:borrow_edit", args=[b.pk]),
                    reverse("ledger:borrow_pay", args=[b.pk]), reverse("ledger:dashboard"),
                    reverse("ledger:transactions") + "?kind=loan", reverse("ledger:wallets")):
            self.assertEqual(self.client.get(url).status_code, 200, url)

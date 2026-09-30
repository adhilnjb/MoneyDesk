"""Import the old Money_Tracker_Phone.xlsx (Entries + Settings sheets) into MoneyDesk.

    python manage.py import_xlsx Money_Tracker_Phone.xlsx --user adhi
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from openpyxl import load_workbook

from ledger import services
from ledger.models import Category, Transaction, Wallet


class Command(BaseCommand):
    help = "Import entries from the Money Tracker spreadsheet."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--user", required=True, help="Username that will own the data")
        parser.add_argument("--business-wallet", default="Milky Way", help="Wallet for the 'Milky Way' source")
        parser.add_argument("--personal-wallet", default="Offline Cash", help="Wallet for the 'ME' source")
        parser.add_argument("--force", action="store_true", help="Import even if an import was already done")

    @db_transaction.atomic
    def handle(self, *args, **opts):
        User = get_user_model()
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"No user named {opts['user']!r}. Create it with createsuperuser or sign up first.")

        if not opts["force"] and Transaction.objects.filter(owner=user, note__startswith="Imported").exists():
            raise CommandError("This user already has imported entries. Use --force to import again.")

        wb = load_workbook(opts["file"], data_only=True)
        if "Entries" not in wb.sheetnames:
            raise CommandError("The workbook has no 'Entries' sheet.")

        # Category -> Income/Expense, taken from the Settings sheet (columns A and B).
        kinds = {}
        if "Settings" in wb.sheetnames:
            for name, kind in wb["Settings"].iter_rows(min_row=2, max_col=2, values_only=True):
                if name and kind in ("Income", "Expense"):
                    kinds[str(name).strip()] = kind.lower()

        services.seed_categories(user)
        wallets = {
            "Milky Way": self._wallet(user, opts["business_wallet"], Wallet.BUSINESS, "#2563EB"),
            "ME": self._wallet(user, opts["personal_wallet"], Wallet.OFFLINE, "#C98A0B"),
        }
        services.seed_wallets(user)  # adds Job Salary + In-Hand Savings if missing

        created = skipped = 0
        for row in wb["Entries"].iter_rows(min_row=2, max_col=5, values_only=True):
            when, source, category, amount, note = row
            if not (source and category) or amount in (None, ""):
                continue
            try:
                amount = Decimal(str(amount))
            except InvalidOperation:
                skipped += 1
                continue
            source, category = str(source).strip(), str(category).strip()
            kind = kinds.get(category)
            if source not in wallets or kind is None or amount <= 0:
                skipped += 1
                continue
            if isinstance(when, datetime):
                when = when.date()
            elif not isinstance(when, date):
                skipped += 1
                continue
            cat, _ = Category.objects.get_or_create(owner=user, name=category, kind=kind)
            Transaction.objects.create(owner=user, kind=kind, wallet=wallets[source], category=cat, amount=amount,
                                       date=when, note=f"Imported: {note}"[:200] if note else "Imported")
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Imported {created} entries, skipped {skipped} empty or invalid rows."))

    @staticmethod
    def _wallet(user, name, kind, color):
        wallet, _ = Wallet.objects.get_or_create(owner=user, name=name, defaults={"kind": kind, "color": color})
        return wallet

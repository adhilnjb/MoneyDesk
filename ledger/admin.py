from django.contrib import admin

from .models import Borrow, BorrowPayment, Budget, Category, Transaction, Wallet

admin.site.register(Wallet, list_display=("name", "kind", "owner", "opening_balance", "archived"))
admin.site.register(Category, list_display=("name", "kind", "owner"))
admin.site.register(Budget, list_display=("category", "amount", "owner"))
admin.site.register(Transaction, list_display=("date", "kind", "wallet", "category", "amount", "owner"),
                    list_filter=("kind", "wallet"))
admin.site.register(Borrow, list_display=("person", "direction", "amount", "date", "due_date", "cleared_on", "owner"),
                    list_filter=("direction",))
admin.site.register(BorrowPayment, list_display=("borrow", "amount", "date"))

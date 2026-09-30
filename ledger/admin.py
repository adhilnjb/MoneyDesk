from django.contrib import admin

from .models import Budget, Category, Transaction, Wallet

admin.site.register(Wallet, list_display=("name", "kind", "owner", "opening_balance", "archived"))
admin.site.register(Category, list_display=("name", "kind", "owner"))
admin.site.register(Budget, list_display=("category", "amount", "owner"))
admin.site.register(Transaction, list_display=("date", "kind", "wallet", "category", "amount", "owner"),
                    list_filter=("kind", "wallet"))

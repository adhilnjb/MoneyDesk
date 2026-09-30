from django.urls import path

from . import views

app_name = "ledger"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("transactions/", views.transaction_list, name="transactions"),
    path("transactions/export.csv", views.export_csv, name="export"),
    path("transactions/new/", views.transaction_form, name="transaction_new"),
    path("transactions/<int:pk>/edit/", views.transaction_form, name="transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete, name="transaction_delete"),
    path("transfers/new/", views.transfer_form, name="transfer_new"),
    path("transfers/<int:pk>/edit/", views.transfer_form, name="transfer_edit"),
    path("wallets/", views.wallet_list, name="wallets"),
    path("wallets/new/", views.wallet_form, name="wallet_new"),
    path("wallets/<int:pk>/edit/", views.wallet_form, name="wallet_edit"),
    path("wallets/<int:pk>/archive/", views.wallet_archive, name="wallet_archive"),
    path("wallets/<int:pk>/delete/", views.wallet_delete, name="wallet_delete"),
    path("categories/", views.category_list, name="categories"),
    path("categories/new/", views.category_form, name="category_new"),
    path("categories/<int:pk>/edit/", views.category_form, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
    path("budgets/", views.budget_list, name="budgets"),
    path("budgets/new/", views.budget_form, name="budget_new"),
    path("budgets/<int:pk>/edit/", views.budget_form, name="budget_edit"),
    path("budgets/<int:pk>/delete/", views.budget_delete, name="budget_delete"),
    path("reports/", views.reports, name="reports"),
]

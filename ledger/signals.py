"""Keep wallet balances honest: when a Borrow or a repayment is deleted, so is its auto entry."""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Borrow, BorrowPayment, Transaction


def _drop_entry(instance, **kwargs):
    if instance.entry_id:
        Transaction.objects.filter(pk=instance.entry_id).delete()


receiver(post_delete, sender=Borrow)(_drop_entry)
receiver(post_delete, sender=BorrowPayment)(_drop_entry)

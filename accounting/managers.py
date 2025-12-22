"""
Accounting Managers
"""

# Standard Library
from datetime import datetime, timedelta

# Third Party
import yaml
from corptools.models import Notification

# Django
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

# Alliance Auth
from allianceauth.eveonline.models import EveCorporationInfo


class AccountManager(models.Manager):
    """
    Manager for Account models
    """

    def outstanding(self):
        """
        Return a queryset of all accounts with a balance less than 0.
        """
        return self.get_queryset().filter(balance__lt=0)

    def total_balance(self):
        """
        Return the total balance of all accounts.
        """
        return self.get_queryset().aggregate(total=Sum("balance"))["total"] or 0

    def overdue(self, days=30):
        """
        Return a queryset of all accounts with a outstanding balance and older than the given number of days.
        """
        cutoff = timezone.now() - timedelta(days=days)
        return self.get_queryset().filter(
            balance__lt=0, ledger_entries__created__lt=cutoff
        )

    def prefetch_ledgers(self):
        """
        Return a queryset with ledger entries prefetched.
        """
        return self.get_queryset().prefetch_related("ledger_entries")


class CorpTaxHistoryManager(models.Manager):
    """
    Manager for CorpTaxHistory models
    """

    def get_corp_tax_list(self, corp_id: int):
        """
        Return a list of tax rates for the given corporation.
        """
        return list(
            self.filter(corp__corporation_id=corp_id)
            .values("start_date", "tax_rate")
            .order_by("start_date")
        )

    def find_corp_tax_changes(self, corp_id: int):
        """
        Find tax rate changes for the given corporation from notifications.
        """
        notes = (
            Notification.objects.filter(
                character__character__corporation_id=corp_id,
                notification_type="CorpTaxChangeMsg",
            )
            .order_by("timestamp", "notification_id")
            .values(
                "notification_id",
                "timestamp",
                "notification_text__notification_text",
            )
            .distinct()
        )

        changes = {}

        for n in notes:
            data = yaml.safe_load(n["notification_text__notification_text"])

            if data.get("corpID") != corp_id:
                continue

            # Ignore non-ISK currencies
            if data.get("currencyNameLabel") not in (None, "UI/Common/ISK"):
                continue

            ts = datetime.timestamp(n["timestamp"])
            changes[ts] = {
                "start_date": n["timestamp"],
                "tax_rate": data["newTaxRate"],
            }

        return list(changes.values())

    @transaction.atomic
    def sync_corp_tax_changes(self, corp_id: int, flush_first: bool = False):
        """
        Sync tax rate changes for the given corporation from notifications.
        If flush_first is True, existing records for the corporation will be deleted first.
        Returns the number of records created.
        """
        if flush_first:
            self.filter(corp__corporation_id=corp_id).delete()

        corp = EveCorporationInfo.objects.get(corporation_id=corp_id)
        taxes = self.find_corp_tax_changes(corp_id)

        models_to_create = [
            self.model(
                corp=corp,
                start_date=t["start_date"],
                tax_rate=t["tax_rate"],
            )
            for t in taxes
        ]

        created = self.bulk_create(models_to_create, ignore_conflicts=True)
        return len(created)

    def sync_and_get_corp_tax_list(self, corp_id: int, flush_first: bool = False):
        """
        Sync tax rate changes for the given corporation from notifications.
        Returns a list of tax rates for the corporation.
        """
        self.sync_corp_tax_changes(corp_id, flush_first=flush_first)
        return self.get_corp_tax_list(corp_id)

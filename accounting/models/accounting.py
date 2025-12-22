"""Main app models."""

# Third Party
from solo.models import SingletonModel

# Django
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.framework.api.evecharacter import get_user_from_evecharacter

# Accounting
from accounting.managers import AccountManager


class General(models.Model):
    """A meta model for app permissions."""

    class Meta:
        """Meta definitions."""

        managed = False
        default_permissions = ()
        permissions = (
            # gives access to the module for the user and any corps they are CEO of
            ("basic_access", _("Can access the Accounting app")),
            # gives access to a users own corp thay aren't a ceo of
            ("view_own_corp", _("Can view own corp")),
            # gives access to view the all characters and corps accounts as well as the admin dashboard
            ("view_all", _("Can view all characters and corps")),
            # gives access to everything, plus the ability to manually add a bill/invoice
            ("finance_manager", _("Can view everything, plus submit bills/invoices")),
        )


# Global entry types
LEDGER_ENTRY_TYPES = [
    ("deposit", "Deposit"),
    ("tax", "Tax"),
    ("fine", "Fine"),
    ("adjustment", "Adjustment"),
    ("charge", "Charge"),
]


class AccountingConfiguration(SingletonModel):
    """
    App Configs
    """

    bank_corp = models.OneToOneField(
        EveCorporationInfo,
        help_text="The Corporation that ISK gets sent to.",
        on_delete=models.PROTECT,
        related_name="bank_corp",
        null=True,
    )
    ignored_corp = models.ManyToManyField(
        EveCorporationInfo,
        blank=True,
        help_text="Corps to ignore deposits from",
        related_name="ignored_corps",
    )

    last_payment_datetime = models.DateTimeField(
        default=timezone.now, help_text="Timestamp of the last processed payment."
    )

    def __str__(self) -> str:
        return "Accounting Configuration"

    def ignored_corp_qs(self):
        """
        Get the ignored corporations as a queryset.
        """
        return self.ignored_corp.all()


class UserAccount(models.Model):
    """
    User Accounts
    """

    objects = AccountManager()
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="account")
    balance = models.DecimalField(max_digits=20, decimal_places=2, default="0.00")
    created = models.DateTimeField(auto_now_add=True)

    def add_ledger_entry(
        self, amount, description, entry_type="deposit", date=None, character=None
    ):
        """
        Add a ledger entry and automatically update balance.
        """
        if date is None:
            date = timezone.now()

        entry = UserLedgerEntry.objects.create(
            account=self,
            amount=amount,
            description=description,
            entry_type=entry_type,
            character=character,
            created=date,
        )
        # Atomic balance update
        UserAccount.objects.filter(pk=self.pk).update(
            balance=models.F("balance") + amount
        )
        # Reload THIS instance so balance is correct + Decimal typed
        self.refresh_from_db(fields=["balance"])

        # Refresh entry to store the new balance
        entry.balance = self.balance
        entry.save(update_fields=["balance"])
        return entry


class UserLedgerEntry(models.Model):
    """
    Ledger Entries
    """

    account = models.ForeignKey(
        UserAccount, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    balance = models.DecimalField(max_digits=20, decimal_places=2, default="0.00")
    description = models.TextField()
    entry_type = models.CharField(
        max_length=20, choices=LEDGER_ENTRY_TYPES, default="deposit"
    )
    created = models.DateTimeField()
    character = models.ForeignKey(
        EveCharacter, on_delete=models.SET_NULL, null=True, blank=True
    )


class CorpAccount(models.Model):
    """
    Corporation Accounts
    """

    objects = AccountManager()
    corporation = models.OneToOneField(
        EveCorporationInfo, on_delete=models.CASCADE, related_name="account"
    )
    balance = models.DecimalField(max_digits=20, decimal_places=2, default="0.00")
    created = models.DateTimeField(auto_now_add=True)

    def add_ledger_entry(
        self, amount, description, entry_type="deposit", character=None
    ):
        """
        Add a ledger entry and automatically update balance.
        """
        entry = CorpLedgerEntry.objects.create(
            account=self,
            amount=amount,
            description=description,
            entry_type=entry_type,
            character=character,
        )
        # Atomic balance update
        CorpAccount.objects.filter(pk=self.pk).update(
            balance=models.F("balance") + amount
        )
        # Reload THIS instance so balance is correct + Decimal typed
        self.refresh_from_db(fields=["balance"])

        # Refresh entry to store the new balance
        entry.balance = self.balance
        entry.save(update_fields=["balance"])
        return entry


class CorpLedgerEntry(models.Model):
    """
    Ledger Entries
    """

    account = models.ForeignKey(
        CorpAccount, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    balance = models.DecimalField(max_digits=20, decimal_places=2, default="0.00")
    description = models.TextField()
    entry_type = models.CharField(
        max_length=20, choices=LEDGER_ENTRY_TYPES, default="deposit"
    )
    created = models.DateTimeField(auto_now_add=True)
    character = models.ForeignKey(
        EveCharacter, on_delete=models.SET_NULL, null=True, blank=True
    )


class UnclaimedTax(models.Model):
    """
    Unclaimed Taxes
    """

    character = models.ForeignKey(
        EveCharacter, on_delete=models.CASCADE, related_name="unclaimed_taxes"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=20, choices=LEDGER_ENTRY_TYPES, default="charge")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]

    def _reconcile_to_user(self):
        """
        Reconcile an unclaimed tax to a user's account.
        Returns:
            bool: True if reconciliation was successful, False otherwise.
        """
        user = get_user_from_evecharacter(self.character)
        if not user:
            return False

        user_account = UserAccount.objects.get_or_create(user=user)

        reconcile_note = (
            f"\n[Reconciled from unclaimed entry: {self.created.isoformat()}]"
        )
        full_description = (self.description or "") + reconcile_note

        user_account.add_ledger_entry(
            amount=self.amount,
            description=full_description,
            entry_type=self.type,
            character=self.character,
        )

        # Delete this entry after successful reconciliation
        self.delete()
        return True

    @classmethod
    def reconcile_all(cls):
        """
        Reconcile all unreconciled taxes to their respective users.

        Returns:
            int: The number of successfully reconciled taxes.
        """
        unreconciled = cls.objects.filter(reconciled=False)
        count = 0
        for tax in unreconciled:
            if tax._reconcile_to_user():
                count += 1
        return count

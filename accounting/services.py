"""
Services for accounting app
"""

# Django
from django.contrib.auth.models import User
from django.utils import timezone

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.framework.api.evecharacter import get_user_from_evecharacter

from .models.accounting import (
    LEDGER_ENTRY_TYPES,
    CorpAccount,
    CorpLedgerEntry,
    UnclaimedTax,
    UserAccount,
    UserLedgerEntry,
)


def post_ledger_entry(
    target: User | EveCharacter | EveCorporationInfo,
    amount: float,
    description: str,
    entry_type: str = "charge",  # enforce allowed types
    date: timezone.datetime | None = None,
) -> UserLedgerEntry | CorpLedgerEntry | UnclaimedTax | None:
    """
    Add a ledger entry and automatically update balance.
    Returns the created ledger entry.
    """

    if entry_type not in [t[0] for t in LEDGER_ENTRY_TYPES]:
        raise ValueError(f"Invalid entry_type {entry_type}")

    if amount <= 0:
        raise ValueError("Amount must be entered as a positive number")

    # Determine amount direction, assume anything other than a deposit is negative
    if entry_type == "deposit":
        ledger_amount = amount
    else:
        ledger_amount = -amount

        date = date or timezone.now()

    # Handle User
    if isinstance(target, User):
        account, _ = UserAccount.objects.get_or_create(user=target)
        return account.add_ledger_entry(
            amount=ledger_amount,
            description=description,
            entry_type=entry_type,
        )

    # Handle EveCharacter
    if isinstance(target, EveCharacter):
        user = get_user_from_evecharacter(target)
        # if we can't find a user for that character
        if not user or user.username == "deleted":
            # Store as unclaimed tax
            return UnclaimedTax.objects.create(
                character=target,
                amount=ledger_amount,
                description=description,
                type=entry_type,
            )
        # if that character has a user
        account, _ = UserAccount.objects.get_or_create(user=user)
        return account.add_ledger_entry(
            amount=ledger_amount,
            description=description,
            entry_type=entry_type,
            character=target,
        )

    # Handle EveCorporationInfo
    if isinstance(target, EveCorporationInfo):
        account, _ = CorpAccount.objects.get_or_create(corporation=target)
        return account.add_ledger_entry(
            amount=ledger_amount,
            description=description,
            entry_type=entry_type,
        )

    raise TypeError(
        "Target must be of type django.contrib.auth.modelsUser, allianceauth.eveonline.modelsEveCharacter, or allianceauth.eveonline.models.EveCorporationInfo"
    )

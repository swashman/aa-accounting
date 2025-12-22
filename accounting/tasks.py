"""Tasks."""

# Third Party
from celery import chain, shared_task
from corptools.models import CorporationWalletJournalEntry

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter
from allianceauth.framework.api.evecharacter import get_user_from_evecharacter
from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

# Accounting
from accounting.models import (
    AccountingConfiguration,
    CorpTaxConfiguration,
    CorpTaxHistory,
)
from accounting.services import post_ledger_entry
from accounting.utils import get_or_create_character, get_or_create_corporation_info

logger = get_extension_logger(__name__)


@shared_task(bind=True, base=QueueOnce)
def check_for_payments(self):
    """
    Periodically checks for new payments in the journal entries.

    :return: None
    """
    logger.info("Checking for payments")
    refs = [
        "corporation_account_withdrawal",
        "player_donation",
    ]  # we only care about these types

    # get the last ID we processed so we can only grab the new stuff
    config = AccountingConfiguration.get_solo()
    last_time = config.last_payment_datetime
    payment_corp = config.bank_corp.corporation_id
    ignored_corp_ids = list(
        config.ignored_corp_qs().values_list("corporation_id", flat=True)
    )

    # grab the new journal entries
    payments = (
        CorporationWalletJournalEntry.objects.filter(
            division__corporation__corporation__corporation_id=payment_corp,
            ref_type__in=refs,
            amount__gt=1,
            date__gt=last_time,
        )
        .exclude(first_party_id__in=ignored_corp_ids)
        .order_by("date")
    )
    # TODO: we can probably shrink this a bit instead of repeating in the IF's
    # if we have any, process them
    if payments.exists():
        newest_payment = payments.last()
        logger.debug("Newest payment date: %s", newest_payment.date)
        config.last_payment_datetime = newest_payment.date
        config.save()
        for payment in payments:
            logger.debug("Ref Type: %s", payment.ref_type)

            # if its a corp account withdrawal, then it process as a corp payment
            if payment.ref_type == "corporation_account_withdrawal":
                logger.info(
                    "Processing corp account payment from %s for %s",
                    payment.first_party_id,
                    payment.amount,
                )
                # get the corp
                corp = get_or_create_corporation_info(
                    corporation_id=payment.first_party_id
                )
                # get the character who made the payment
                char = get_or_create_character(character_id=payment.context_id)

                # create description
                desc = f"Corporation Payment made by {char.character_name}"
                if payment.reason is not None:
                    desc += f"\n Note: {payment.reason}"
                # add the entry
                _ = post_ledger_entry(
                    corp, payment.amount, desc, "deposit", payment.date
                )
            else:
                # it must be a player donation
                logger.info(
                    "Processing player donation payment from %s for %s",
                    payment.first_party_id,
                    payment.amount,
                )

                try:
                    # Attempt to get the character; skip if it does not exist
                    eve_character = EveCharacter.objects.get(
                        character_id=payment.first_party_id
                    )
                except EveCharacter.DoesNotExist:
                    logger.warning(
                        "Skipping payment %s: no EveCharacter for character_id %s",
                        payment.id,
                        payment.first_party_id,
                    )
                    return

                user = get_user_from_evecharacter(eve_character)

                if user is None or user.username == "deleted":
                    logger.warning(
                        "Skipping payment %s: user not found for character %s",
                        payment.id,
                        eve_character.character_name,
                    )
                    return

                # create description
                desc = f"Player Payment made by {eve_character.character_name}"
                if payment.reason is not None:
                    desc += f"\n Note: {payment.reason}"
                # Add the ledger entry
                _ = post_ledger_entry(
                    target=user,
                    amount=payment.amount,
                    description=desc,
                    entry_type="deposit",
                    date=payment.date,
                )

    else:
        logger.info("No new payments found!")


@shared_task(bind=True, base=QueueOnce)
def send_invoices_for_config_id(self, config_id=1):
    """
    Send invoices.
    """
    logger.info(f"Sending invoices for CorpTaxConfiguration id={config_id}")
    tc = CorpTaxConfiguration.objects.get(id=config_id)
    logger.info(tc)
    tax = tc.send_invoices()
    return tax["taxes"]


@shared_task(bind=True, base=QueueOnce)
def sync_all_corp_tax_rates(self):
    """
    Sync the tax rates.
    """
    return CorpTaxHistory.sync_all_corps()


@shared_task(bind=True, base=QueueOnce)
def send_taxes(self, config_id=1):
    """
    Sync all and send the invoices.
    """
    tasks = []
    tasks.append(sync_all_corp_tax_rates.si())
    tasks.append(send_invoices_for_config_id.si(config_id=config_id))

    chain(tasks).apply_async(priority=4)

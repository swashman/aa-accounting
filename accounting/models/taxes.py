"""Tax Models.
The majority of this file is from
https://github.com/Solar-Helix-Independent-Transport/allianceauth-corp-tools-tax-tools
with edits as necessary to fit this project and clean up some parts.
"""

# Standard Library
import decimal
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import floor, log

# Third Party
from corptools.models import (
    CharacterWalletJournalEntry,
    CorporationAudit,
    CorporationWalletJournalEntry,
    EveItemType,
    EveName,
    MapRegion,
    MapSystem,
    Structure,
    StructureService,
)

# Django
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Count, ExpressionWrapper, F
from django.db.models.functions import Coalesce
from django.forms import model_to_dict
from django.utils import timezone as tzone

# Alliance Auth
from allianceauth.authentication.models import State
from allianceauth.eveonline.models import (
    EveAllianceInfo,
    EveCharacter,
    EveCorporationInfo,
)
from allianceauth.services.hooks import get_extension_logger

# Accounting
from accounting.managers import CorpTaxHistoryManager
from accounting.providers import esi
from accounting.services import post_ledger_entry

logger = get_extension_logger(__name__)

MIN_DATE = datetime.min.replace(tzinfo=timezone.utc)
MAX_DATE = datetime.max.replace(tzinfo=timezone.utc)
OVERLAP_DAYS = 2  # how many days back to overlap incase of esi delays


class TaxBase:
    """
    Defines what the tax percentage is applied to.
    """

    TOTAL = "total"
    CORP_TAX = "corp_tax"

    CHOICES = (
        (TOTAL, "Percent of total earnings"),
        (CORP_TAX, "Percent of tax taken by corporation"),
    )


class TaxBaseMixin:
    """
    Mixin to provide tax base calculation.
    """

    def calculate_tax_due(self, gross: Decimal, net: Decimal, tax_rate: Decimal):
        """
        Calculate tax due.
        """
        corp_tax = gross - net

        if self.tax_base == TaxBase.CORP_TAX:
            taxable = corp_tax
        else:
            taxable = gross

        return taxable * (tax_rate / Decimal(100))


class CharacterRattingTaxConfiguration(models.Model):
    """Character ratting tax configuration."""

    name = models.CharField(max_length=50)

    tax = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)

    include_ess_section = models.BooleanField(default=True)

    region_filter = models.ManyToManyField(
        MapRegion,
        blank=True,
        related_name="character_ratting_tax_regions",
        help_text="Regions to limit this tax to.",
    )

    class Meta:
        verbose_name = "Tax: Character Ratting"
        verbose_name_plural = "Tax: Character Ratting"

    def __str__(self) -> str:
        regions = "`, `".join(self.region_filter.all().values_list("name", flat=True))
        if not len(regions):
            regions = "Everywhere"
        return f"{self.name}: {self.tax:,.2f}% in:{regions}"

    def __str_discord__(self) -> str:
        regions = "`, `".join(self.region_filter.all().values_list("name", flat=True))
        if not len(regions):
            regions = "Everywhere"
        return f"**{self.name}** `{self.tax:,.2f}`% in:\n`{regions}`"

    def __str_console__(self) -> str:
        regions = "`, `".join(self.region_filter.all().values_list("name", flat=True))
        if not len(regions):
            regions = "Everywhere"
        return (
            f"{self.name} \033[31m{self.tax:,.2f}%\033[39m in:\033[32m{regions}\033[32m"
        )

    def get_payment_data(
        self, start_date=MIN_DATE, end_date=MAX_DATE, alliance_filter=None
    ):
        query = CharacterWalletJournalEntry.objects.filter(
            date__gte=start_date, date__lte=end_date, ref_type__in=["bounty_prizes"]
        )
        if alliance_filter:
            query = query.filter(
                character__character__character_ownership__user__profile__main_character__alliance_id__in=alliance_filter
            )
        if self.region_filter.all().count():
            query = query.filter(
                context_id__in=MapSystem.objects.filter(
                    constellation__region__in=self.region_filter.all()
                )
            )
        return query.exclude(taxed__processed=True)

    def process_character_aggregates(self, data):
        output = {}
        trans_ids = set()
        bad_transactions = []
        for d in data:
            if d["entry_id"] not in trans_ids:
                cid = d["char"]
                if d["main"]:
                    cid = d["main"]

                if cid not in output:
                    output[cid] = {
                        "characters": [],
                        "corp": d["main_corp"],
                        "trans_ids": [],
                        "tax_rates_used": [],
                        "sum_earn": 0,
                        "pre_tax_total": 0,
                        "tax_to_pay": 0,
                        "cnt": 0,
                        "end": MIN_DATE,
                        "start": MAX_DATE,
                    }

                try:
                    total_value = d["total_ratted"] * Decimal(0.95)
                    # minus the 5% Reserve ESS cut
                    if not self.include_ess_section:
                        total_value -= d["ess_cut"]

                except Exception as e:  # prob cause none or something
                    # prob bad data from ccp we need to do math here...
                    # need more data to math this...
                    logger.warning(f"NO TAX or ISK Data:{d} {e}")
                    bad_transactions.append(d["entry_id"])
                    continue

                output[cid]["sum_earn"] += d["amount"]
                output[cid]["pre_tax_total"] += total_value
                output[cid]["tax_to_pay"] += total_value * (self.tax / 100)

                output[cid]["cnt"] += 1

                output[cid]["trans_ids"].append(d["entry_id"])

                trans_ids.add(d["entry_id"])

                if d["char_name"] not in output[cid]["characters"]:
                    output[cid]["characters"].append(d["char_name"])

                if d["date"] < output[cid]["start"]:
                    output[cid]["start"] = d["date"]

                if d["date"] > output[cid]["end"]:
                    output[cid]["end"] = d["date"]

        logger.warning(f"Bad Transactions: {bad_transactions}")
        return output

    def get_character_aggregates(
        self, start_date=MIN_DATE, end_date=MAX_DATE, alliance_filter=None
    ):
        data = self.get_payment_data(start_date, end_date, alliance_filter).values(
            "amount",  # Player Payment
            "tax",  # Tax Amount
            "tax_receiver_id",  # corp that got taxed
            "entry_id",  # Unique to not double charge
            "date",
            char=F("character__character__character_id"),
            corp=F("character__character__corporation_id"),
            char_name=F("character__character__character_name"),
            total_ratted=ExpressionWrapper(
                ((Coalesce("amount", 0) + Coalesce("tax", 0)) / 0.6),
                output_field=models.DecimalField(),
            ),  # Value before ESS
            ess_cut=ExpressionWrapper(
                ((Coalesce("amount", 0) + Coalesce("tax", 0)) / 0.6) * 0.35,
                output_field=models.DecimalField(),
            ),  # Value ESS Returned to player
            main=F(
                "character__character__character_ownership__user__profile__main_character__character_id"
            ),
            main_corp=F(
                "character__character__character_ownership__user__profile__main_character__corporation_id"
            ),
        )
        return self.process_character_aggregates(data)

    def process_character_aggregates_corp_level(self, data, full=True):
        output = {}
        for id, t in data.items():
            cid = t["corp"]
            if cid not in output:
                output[cid] = {
                    "characters": [],
                    "trans_ids": [],
                    "tax_rates_used": [],
                    "sum_earn": 0,
                    "pre_tax_total": 0,
                    "tax_to_pay": 0,
                    "cnt": 0,
                    "end": MIN_DATE,
                    "start": MAX_DATE,
                }
            output[cid]["characters"] += t["characters"]
            if full:
                output[cid]["trans_ids"] += t["trans_ids"]
            for tr in t["tax_rates_used"]:
                if tr not in output[cid]["tax_rates_used"]:
                    output[cid]["tax_rates_used"].append(tr)
            output[cid]["sum_earn"] += t["sum_earn"]
            output[cid]["pre_tax_total"] += t["pre_tax_total"]
            output[cid]["tax_to_pay"] += t["tax_to_pay"]
            output[cid]["cnt"] += t["cnt"]
            if t["start"] < output[cid]["start"]:
                output[cid]["start"] = t["start"]

            if t["end"] > output[cid]["end"]:
                output[cid]["end"] = t["start"]
        return output

    def get_character_aggregates_corp_level(
        self, start_date=MIN_DATE, end_date=MAX_DATE, full=True, alliance_filter=None
    ):
        logger.debug(
            f"Started get_character_aggregates_corp_level {self.__str_discord__()}"
        )
        data = self.get_character_aggregates(start_date, end_date, alliance_filter)
        return self.process_character_aggregates_corp_level(data, full)


class CharacterPayoutTaxConfiguration(models.Model):
    """Character payout tax configuration."""

    name = models.CharField(max_length=50)

    corporation = models.ForeignKey(
        EveName,
        on_delete=models.CASCADE,
        limit_choices_to={"category": "corporation"},
        blank=True,
        null=True,
        default=None,
        related_name="character_tax_corp",
        help_text="Corporation that sent isk to character, Blank for Any Corporation",
    )

    wallet_transaction_type = models.CharField(
        max_length=150,
        help_text="Transaction types to tax. eg bounty_prizes,corporate_reward_payout",
    )

    tax = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)

    class Meta:
        verbose_name = "Tax: Character Wallet"
        verbose_name_plural = "Tax: Character Wallet"

    def __str__(self) -> str:
        return f"{self.name} {self.tax:,.2f}% of {self.wallet_transaction_type} from {self.corporation.name if self.corporation else 'all'}"

    def __str_discord__(self) -> str:
        return f"**{self.name}**\n`{self.tax:,.2f}`% of `{self.wallet_transaction_type}` from `{self.corporation.name if self.corporation else 'all'}`"

    def __str_console__(self) -> str:
        return f"{self.name} \033[31m{self.tax:,.2f}%\033[39m of \033[32m{self.wallet_transaction_type}\033[39m from \033[32m{self.corporation.name if self.corporation else 'all'}\033[39m"

    def get_payment_data(
        self, start_date=MIN_DATE, end_date=MAX_DATE, alliance_filter=None
    ):
        ref_types = self.wallet_transaction_type.split(",")
        query = CharacterWalletJournalEntry.objects.filter(
            date__gte=start_date, date__lte=end_date, ref_type__in=ref_types
        )
        if self.corporation_id:
            query = query.filter(first_party_name_id=self.corporation_id)
        if alliance_filter:
            query = query.filter(
                character__character__character_ownership__user__profile__main_character__alliance_id__in=alliance_filter
            )
        return query.exclude(taxed__processed=True)

    def process_character_aggregates(self, data):
        output = {}
        tax_cache = {}
        trans_ids = set()
        bad_transactions = []
        for d in data:
            if d["entry_id"] not in trans_ids:
                cid = d["char"]
                if d["main"]:
                    cid = d["main"]
                crpid = d["corp"]
                if crpid not in tax_cache:
                    tax_cache[crpid] = CorpTaxHistory.objects.get_corp_tax_list(crpid)
                corp_details = esi.client.Corporation.GetCorporationsCorporationId(
                    corporation_id=crpid
                ).result(use_etag=False)
                logger.debug(f"Corp Details for Tax Rate Lookup: {corp_details}")
                current_rate = Decimal(corp_details.tax_rate)
                rate = CorpTaxHistory.get_tax_rate(
                    cid,
                    d["date"],
                    tax_rates=tax_cache[crpid],
                    default=current_rate * 100,
                )

                if cid not in output:
                    output[cid] = {
                        "characters": [],
                        "corp": d["main_corp"],
                        "trans_ids": [],
                        "tax_rates_used": [],
                        "sum_earn": 0,
                        "pre_tax_total": 0,
                        "tax_to_pay": 0,
                        "cnt": 0,
                        "end": MIN_DATE,
                        "start": MAX_DATE,
                    }
                logger.debug(f"Processing Transaction Data: {d} with Tax Rate: {rate}%")
                logger.debug(f"Amount: {d['amount']}")
                try:
                    total_value = d["amount"] / (100 - Decimal(rate)) * 100
                except (ZeroDivisionError, decimal.InvalidOperation):  # 100% tax
                    # take the tax amount from the transaction. This has been flakey tho. SO YMMV

                    if d["tax"]:
                        total_value = d["tax"]
                    else:
                        logger.debug(f"NO TAX or ISK Tax:{rate}% Data:{d}")
                        bad_transactions.append(d["entry_id"])
                        continue

                output[cid]["sum_earn"] += d["amount"]
                output[cid]["pre_tax_total"] += total_value
                output[cid]["tax_to_pay"] += total_value * (self.tax / 100)
                logger.debug(
                    f"Computed Total Value: {total_value}, Tax to Pay: {total_value * (self.tax / 100)}"
                )

                output[cid]["cnt"] += 1

                output[cid]["trans_ids"].append(d["entry_id"])

                trans_ids.add(d["entry_id"])

                if rate not in output[cid]["tax_rates_used"]:
                    output[cid]["tax_rates_used"].append(rate)

                if d["char_name"] not in output[cid]["characters"]:
                    output[cid]["characters"].append(d["char_name"])

                if d["date"] < output[cid]["start"]:
                    output[cid]["start"] = d["date"]

                if d["date"] > output[cid]["end"]:
                    output[cid]["end"] = d["date"]

        # print(bad_transactions)
        return output

    def get_character_aggregates(
        self, start_date=MIN_DATE, end_date=MAX_DATE, alliance_filter=None
    ):
        logger.debug(f"Started get_character_aggregates {self.__str_console__()}")
        data = self.get_payment_data(start_date, end_date, alliance_filter).values(
            "amount",
            "entry_id",
            "date",
            "tax",
            char=F("character__character__character_id"),
            corp=F("character__character__corporation_id"),
            char_name=F("character__character__character_name"),
            main=F(
                "character__character__character_ownership__user__profile__main_character__character_id"
            ),
            main_corp=F(
                "character__character__character_ownership__user__profile__main_character__corporation_id"
            ),
        )
        return self.process_character_aggregates(data)

    def process_character_aggregates_corp_level(self, data, full=True):
        output = {}
        for id, t in data.items():
            cid = t["corp"]
            if cid not in output:
                output[cid] = {
                    "characters": [],
                    "trans_ids": [],
                    "tax_rates_used": [],
                    "sum_earn": 0,
                    "pre_tax_total": 0,
                    "tax_to_pay": 0,
                    "cnt": 0,
                    "end": MIN_DATE,
                    "start": MAX_DATE,
                }
            output[cid]["characters"] += t["characters"]
            if full:
                output[cid]["trans_ids"] += t["trans_ids"]
            for tr in t["tax_rates_used"]:
                if tr not in output[cid]["tax_rates_used"]:
                    output[cid]["tax_rates_used"].append(tr)
            output[cid]["sum_earn"] += t["sum_earn"]
            output[cid]["pre_tax_total"] += t["pre_tax_total"]
            output[cid]["tax_to_pay"] += t["tax_to_pay"]
            output[cid]["cnt"] += t["cnt"]
            if t["start"] < output[cid]["start"]:
                output[cid]["start"] = t["start"]

            if t["end"] > output[cid]["end"]:
                output[cid]["end"] = t["start"]
            logger.debug(f"Processed Corp Level Data: {output[cid]}")
        return output

    def get_character_aggregates_corp_level(
        self, start_date=MIN_DATE, end_date=MAX_DATE, full=True, alliance_filter=None
    ):
        logger.debug(
            f"Started get_character_aggregates_corp_level {self.__str_console__()}"
        )
        data = self.get_character_aggregates(start_date, end_date, alliance_filter)
        logger.debug(f"Data Retrieved: {data}")
        return self.process_character_aggregates_corp_level(data, full=full)


# CorpTaxChangeMsg
class CorpTaxHistory(models.Model):
    """Corporation Tax History Model."""

    corp = models.ForeignKey(
        EveCorporationInfo, on_delete=models.CASCADE, related_name="tax_history"
    )
    start_date = models.DateTimeField()
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)

    objects = CorpTaxHistoryManager()

    class Meta:
        unique_together = [["corp", "start_date"]]

    @classmethod
    def get_tax_rate(cls, corp_id, date, tax_rates: list = None, default=10):
        """
        Pure business logic:
        given a date, resolve the effective tax rate.
        """
        if not tax_rates:
            tax_rates = cls.objects.get_corp_tax_list(corp_id)

        rate = default
        tax_rates.sort(key=lambda i: i["start_date"])

        for tr in tax_rates:
            if tr["start_date"] < date:
                rate = tr["tax_rate"]
            else:
                break

        return rate

    @classmethod
    def sync_all_corps(cls, flush_first: bool = True):
        """
        Batch operation across all audited corporations.
        """
        output = {}

        for c in CorporationAudit.objects.all():
            created = cls.objects.sync_corp_tax_changes(
                c.corporation.corporation_id,
                flush_first=flush_first,
            )
            output[c.corporation.corporation_name] = created

        return output


class CorpTaxPayoutTaxConfiguration(models.Model):
    """Corporation payout tax configuration."""

    name = models.CharField(max_length=50)

    corporation = models.ForeignKey(
        EveName,
        on_delete=models.CASCADE,
        limit_choices_to={"category": "corporation"},
        blank=True,
        null=True,
        default=None,
        related_name="tax_corp_payout",
        help_text="Corporation that sent isk to character, Blank for Any Corporation",
    )

    wallet_transaction_type = models.CharField(
        max_length=150,
        help_text="Transaction types to tax. eg bounty_prizes,corporate_reward_payout",
    )

    tax = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)

    class Meta:
        verbose_name = "Tax: Corporate Wallet"
        verbose_name_plural = "Tax: Corporate Wallet"

    def __str__(self) -> str:
        return f"{self.name} {self.tax:,.2f}% of {self.wallet_transaction_type} from {self.corporation.name if self.corporation else 'all'}"

    def __str_discord__(self) -> str:
        return f"**{self.name}**\n`{self.tax:,.2f}`% of `{self.wallet_transaction_type}` from `{self.corporation.name if self.corporation else 'all'}`"

    def __str_console__(self) -> str:
        return f"{self.name} \033[31m{self.tax:,.2f}%\033[39m of \033[32m{self.wallet_transaction_type}\033[39m from \033[32m{self.corporation.name if self.corporation else 'all'}\033[39m"

    def get_payment_data(
        self, start_date=MIN_DATE, end_date=MAX_DATE, alliance_filter=None
    ):
        return (
            CorporationWalletJournalEntry.objects.filter(
                date__gte=start_date,
                date__lte=end_date,
                ref_type=self.wallet_transaction_type,
                first_party_name_id=self.corporation_id,
            )
            .exclude(taxed__processed=True)
            .select_related(
                "division__corporation__corporation",
                "first_party_name",
                "second_party_name",
            )
        )

    def get_aggregates(
        self,
        start_date=MIN_DATE,
        end_date=MAX_DATE,
        full=True,
        alliance_filter=None,
    ):
        output = {}
        tax_cache = {}
        trans_ids = set()
        for w in self.get_payment_data(start_date=start_date, end_date=end_date):
            if w.entry_id not in trans_ids:
                cid = w.division.corporation.corporation.corporation_id
                if cid not in tax_cache:
                    tax_cache[cid] = CorpTaxHistory.objects.get_corp_tax_list(cid)
                corp_details = esi.client.Corporation.GetCorporationsCorporationId(
                    corporation_id=cid
                ).result()
                current_rate = Decimal(corp_details.tax_rate)
                rate = CorpTaxHistory.get_tax_rate(
                    cid, w.date, tax_rates=tax_cache[cid], default=current_rate * 100
                )

                trans_ids.add(w.entry_id)
                if cid not in output:
                    output[cid] = {
                        "characters": [],
                        "trans_ids": [],
                        "tax_rates_used": [],
                        "tax_rates": tax_cache[cid],
                        "sum_earn": 0,
                        "pre_tax_total": 0,
                        "tax_to_pay": 0,
                        "cnt": 0,
                        "end": MIN_DATE,
                        "start": MAX_DATE,
                    }
                total_value = w.amount

                if rate > 0:
                    total_value = w.amount / (Decimal(rate / 100))

                output[cid]["sum_earn"] += w.amount
                output[cid]["pre_tax_total"] += total_value
                output[cid]["tax_to_pay"] += total_value * (self.tax / 100)

                output[cid]["cnt"] += 1

                if full:
                    output[cid]["trans_ids"].append(w.entry_id)

                if rate not in output[cid]["tax_rates_used"]:
                    output[cid]["tax_rates_used"].append(rate)

                if w.second_party_name.name not in output[cid]["characters"]:
                    output[cid]["characters"].append(w.second_party_name.name)

                if w.date < output[cid]["start"]:
                    output[cid]["start"] = w.date

                if w.date > output[cid]["end"]:
                    output[cid]["end"] = w.date

        return output


class CorpTaxPerMemberTaxConfiguration(models.Model):
    state = models.ForeignKey(
        State,
        on_delete=models.CASCADE,
        help_text="State to assign this member tax rate to.",
        related_name="corp_member_tax_state",
    )

    isk_per_main = models.IntegerField(default=20000000)

    class Meta:
        verbose_name = "Tax: Corp Member Main"
        verbose_name_plural = "Tax: Corp Member Main"

    def __str__(self) -> str:
        return f"{self.state} @ ${self.isk_per_main:,.2f} per main"

    def __str_discord__(self) -> str:
        return f"**{self.state}** @ `${self.isk_per_main:,.2f}` per main"

    def __str_console__(self) -> str:
        return f"\033[32m{self.state}\033[39m @ \033[31m${self.isk_per_main:,.2f}\033[39m per main"

    def get_main_counts(self):
        characters = (
            EveCharacter.objects.filter(
                character_ownership__user__profile__state=self.state,
                character_id=F(
                    "character_ownership__user__profile__main_character__character_id"
                ),
            )
            .values(
                "character_ownership__user__profile__main_character__corporation_id"
            )
            .annotate(
                Count("character_id"),
                corp_name=F(
                    "character_ownership__user__profile__main_character__corporation_name"
                ),
            )
        )
        return characters

    def get_invoice_data(self):
        logger.debug(f"Started get_invoice_data {self.__str_discord__()}")
        corp_list = self.get_main_counts()
        corp_info = {}
        output = {}
        corps = EveCorporationInfo.objects.filter(
            corporation_id__in=corp_list.values_list(
                "character_ownership__user__profile__main_character__corporation_id"
            )
        )

        for c in corps:
            corp_info[c.corporation_id] = {"ceo": c.ceo_id, "members": c.member_count}

        for corp in corp_list:
            cid = corp[
                "character_ownership__user__profile__main_character__corporation_id"
            ]
            if cid in corp_info:
                output[cid] = {
                    "character_count": corp_info[cid]["members"],
                    "ceo": corp_info[cid]["ceo"],
                    "main_count": corp["character_id__count"],
                    "corp": corp["corp_name"],
                    "tax_to_pay": corp["character_id__count"] * self.isk_per_main,
                }
        return output

    def get_invoice_stats(self):
        corp_list = self.get_invoice_data()
        output = {"corps": {}, "total": 0}

        for key, corp in corp_list.items():
            output["corps"][corp["corp"]] = corp["main_count"]
            output["total"] += corp["tax_to_pay"]

        return output


class CorpTaxPerServiceModuleConfiguration(models.Model):
    isk_per_service = models.IntegerField(default=20000000)

    module_filters = models.TextField(
        help_text="Comma Delimited list of service module types to Tax eg, Manufacturing (Standard),Manufacturing (Capitals),Manufacturing (Super Capitals)"
    )

    structure_type_filter = models.ManyToManyField(
        EveItemType,
        limit_choices_to={"group__category_id": 65},
        blank=True,
        related_name="corp_structure_type_tax_structures",
    )

    region_filter = models.ManyToManyField(
        MapRegion,
        blank=True,
        help_text="Regions to limit this tax to.",
        related_name="corp_structure_service_tax_regions",
    )

    def __str__(self) -> str:
        regions = ", ".join(self.region_filter.all().values_list("name", flat=True))
        structures = self.structure_type_filter.all().values_list("name", flat=True)
        if len(structures):
            structures = ", ".join(structures)
        else:
            structures = "All"

        return f"{self.isk_per_service:,.2f} per:{self.module_filters} For structures ({structures}) in: {regions}"

    def __str_discord__(self) -> str:
        regions = "`, `".join(self.region_filter.all().values_list("name", flat=True))
        if not len(regions):
            regions = "All"
        return f"`{self.isk_per_service:,.2f}` per:\n`{self.module_filters}`\nFor structures in:\n`{regions}`"

    def __str_console__(self) -> str:
        regions = "`, `".join(self.region_filter.all().values_list("name", flat=True))
        if not len(regions):
            regions = "All"
        return f"\033[31m{self.isk_per_service:,.2f}\033[39m per:\033[32m{self.module_filters}\033[39m For structures in: \033[32m{regions}\033[39m"

    class Meta:
        verbose_name = "Tax: Structure Service"
        verbose_name_plural = "Tax: Structure Service"

    def get_service_counts(self):  # TODO update??
        services = self.module_filters.split(",")
        structure_services = StructureService.objects.filter(name__in=services)

        if self.structure_type_filter.all().count():
            structure_services = structure_services.filter(
                structure__type_name__in=self.structure_type_filter.all()
            )

        update_time_filter = tzone.now() - timedelta(days=7)
        structures = Structure.objects.filter(
            pk__in=structure_services.values_list("structure_id"),
            corporation__last_update_structures__gte=update_time_filter,
        )
        if self.region_filter.count() > 0:
            structures = structures.filter(
                system_name__constellation__region__in=self.region_filter.all()
            )

        structures = (
            structures.values(corp=F("corporation__corporation__corporation_id"))
            .distinct()
            .annotate(
                total_structures=Count("structure_id"),
            )
        )
        return structures

    def get_invoice_data(self):  # TODO update??
        logger.debug(f"Started get_invoice_data {self.__str_discord__()}")
        corp_list = self.get_service_counts()
        output = {}

        for corp in corp_list:
            cid = corp["corp"]
            output[cid] = {
                "services_count": corp["total_structures"],
                "tax_to_pay": corp["total_structures"] * self.isk_per_service,
            }

        return output

    def get_invoice_stats(self):
        corp_list = self.get_invoice_data()
        output = {"corps": {}, "total": 0}

        for key, corp in corp_list.items():
            output["corps"][key] = corp["services_count"]
            output["total"] += corp["tax_to_pay"]

        return output


class CorpTaxRecord(models.Model):
    name = models.CharField(max_length=50)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    json_dump = models.TextField()
    total_tax = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, default=None
    )

    class Meta:
        verbose_name = "Records: Corporate"
        verbose_name_plural = "Records: Corporate"


class ExtendedJsonEncoder(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, User):
            return {"user_id": o.pk}
        if isinstance(o, models.Model):
            return model_to_dict(o)
        if isinstance(o, set):
            return list(o)
        return super().default(o)


class CorpTaxConfiguration(models.Model):
    Name = models.CharField(max_length=50)

    character_taxes_included = models.ManyToManyField(
        CharacterPayoutTaxConfiguration, blank=True
    )
    character_ratting_included = models.ManyToManyField(
        CharacterRattingTaxConfiguration, blank=True
    )
    corporate_taxes_included = models.ManyToManyField(
        CorpTaxPayoutTaxConfiguration, blank=True
    )
    corporate_member_tax_included = models.ManyToManyField(
        CorpTaxPerMemberTaxConfiguration, blank=True
    )
    corporate_structure_tax_included = models.ManyToManyField(
        CorpTaxPerServiceModuleConfiguration, blank=True
    )

    exempted_corps = models.ManyToManyField(
        EveCorporationInfo, blank=True, related_name="corp_tax_exempted_corps"
    )

    included_alliances = models.ManyToManyField(
        EveAllianceInfo,
        blank=True,
        related_name="corp_tax_included_alliances",
        help_text="Only include corporations in these alliances. Leave blank to include all.",
    )

    def __str__(self) -> str:
        return f"{self.Name}"

    class Meta:
        verbose_name = "Config: Corporate"
        verbose_name_plural = "Config: Corporate"

    @classmethod
    def get_last_processing_date(cls):
        try:
            return CorpTaxRecord.objects.all().order_by("-end_date").first().end_date
        except (ObjectDoesNotExist, AttributeError):
            return MIN_DATE + timedelta(days=5)

    @staticmethod
    def human_format(number):

        units = ["", "K", "M", "B", "T"]
        k = 1000.0
        magnitude = int(floor(log(number, k)))
        return f"{float(number) / k**magnitude:.2f}{units[magnitude]}"

    def calculate_tax(  # noqa: C901
        self, start_date=MIN_DATE, end_date=MAX_DATE, alliance_filter=None
    ):
        logger.debug("Starting calculate_tax")
        excluded_cids = self.exempted_corps.all().values_list(
            "corporation_id", flat=True
        )
        tax_invoices = {}
        char_trans_ids = []
        corp_trans_ids = []

        logger.debug("Starting character_ratting_included")
        for tax in self.character_ratting_included.all():
            _taxes = tax.get_character_aggregates_corp_level(
                start_date=start_date,
                end_date=end_date,
                alliance_filter=alliance_filter,
            )
            for cid, data in _taxes.items():
                if cid not in excluded_cids:
                    amount = data["tax_to_pay"]
                    if amount > 0:
                        if cid not in tax_invoices:
                            tax_invoices[cid] = {
                                "total_tax": 0,
                                "messages": [],
                            }
                        tax_invoices[cid]["total_tax"] += amount
                        tax_invoices[cid]["messages"].append(
                            f"{tax.name}: {self.human_format(amount)} ({tax.tax:,.1f}% of Total Earnings)"
                        )
                    char_trans_ids += data["trans_ids"]

        logger.debug("Starting character_taxes_included")
        for tax in self.character_taxes_included.all():
            _taxes = tax.get_character_aggregates_corp_level(
                start_date=start_date,
                end_date=end_date,
                alliance_filter=alliance_filter,
            )
            for cid, data in _taxes.items():
                if cid not in excluded_cids:
                    amount = data["tax_to_pay"]
                    if amount > 0:
                        if cid not in tax_invoices:
                            tax_invoices[cid] = {
                                "total_tax": 0,
                                "messages": [],
                            }
                        tax_invoices[cid]["total_tax"] += amount
                        tax_invoices[cid]["messages"].append(
                            f"{tax.name}: {self.human_format(amount)} ({tax.tax:,.1f}% of Total Earnings)"
                        )
                    logger.debug(f"Amount: {amount}")
                    char_trans_ids += data["trans_ids"]

        logger.debug("Starting corporate_taxes_included")
        for tax in self.corporate_taxes_included.all():
            _taxes = tax.get_aggregates(
                start_date=start_date,
                end_date=end_date,
                alliance_filter=alliance_filter,
            )
            for cid, data in _taxes.items():
                if cid not in excluded_cids:
                    amount = data["tax_to_pay"]
                    if amount > 0:
                        if cid not in tax_invoices:
                            tax_invoices[cid] = {
                                "total_tax": 0,
                                "messages": [],
                            }
                        tax_invoices[cid]["total_tax"] += amount
                        tax_invoices[cid]["messages"].append(
                            f"{tax.name}: {self.human_format(amount)} ({tax.tax:,.1f}% of Total Earnings)"
                        )
                    corp_trans_ids += data["trans_ids"]

        logger.debug("Starting corporate_member_tax_included")
        for tax in self.corporate_member_tax_included.all():
            _taxes = tax.get_invoice_data()
            for cid, data in _taxes.items():
                if cid not in excluded_cids:
                    amount = data["tax_to_pay"]
                    if amount > 0:
                        if cid not in tax_invoices:
                            tax_invoices[cid] = {
                                "total_tax": 0,
                                "messages": [],
                            }

                        tax_invoices[cid]["total_tax"] += amount
                        tax_invoices[cid]["messages"].append(
                            f"Main Character Tax: ${self.human_format(amount)} ({tax.state.name}: {data['main_count']} Mains @ {self.human_format(tax.isk_per_main)} Per)"
                        )
        logger.debug("Starting corporate_structure_tax_included")
        for tax in self.corporate_structure_tax_included.all():
            _taxes = tax.get_invoice_data()
            for cid, data in _taxes.items():
                if cid not in excluded_cids:
                    amount = data["tax_to_pay"]
                    if amount > 0:
                        if cid not in tax_invoices:
                            tax_invoices[cid] = {
                                "total_tax": 0,
                                "messages": [],
                            }
                        tax_invoices[cid]["total_tax"] += amount

                        tax_invoices[cid]["messages"].append(
                            f"Industry Structures Tax: ${self.human_format(amount)} ({data['services_count']} Structure @ {self.human_format(tax.isk_per_service)} Per)"
                        )
        logger.debug("Done corporate_structure_tax_included")
        return {
            "taxes": tax_invoices,
            "char_trans_ids": char_trans_ids,
            "corp_trans_ids": corp_trans_ids,
        }

    @classmethod
    def sanitize_date(cls, date):
        return datetime(
            year=date.year,
            month=date.month,
            day=date.day,
            tzinfo=date.tzinfo,
            hour=0,
            minute=0,
            second=0,
        )

    @classmethod
    def generate_charge_for_corp(cls, corp_id, amount, message):
        # generate a charge for the corp and return it
        eve_corporation = EveCorporationInfo.objects.get(corporation_id=corp_id)
        # post the entry
        entry = post_ledger_entry(eve_corporation, amount, message, "tax")
        return entry

    def get_charge_data(self):
        start_date = self.sanitize_date(
            # allow for esi delays in the wallets
            self.get_last_processing_date()
            - timedelta(days=OVERLAP_DAYS)
        )
        end_date = self.sanitize_date(tzone.now())
        alliances = None
        if self.included_alliances.all().count():
            alliances = self.included_alliances.all().values_list(
                "alliance_id", flat=True
            )

        return (
            start_date,
            end_date,
            self.calculate_tax(
                start_date=start_date, end_date=end_date, alliance_filter=alliances
            ),
        )

    def send_invoices(self):
        logger.debug("Starting to charge the corps")
        start_date, end_date, taxes = self.get_charge_data()  # go get all the data
        total_tax = 0
        for id, tax in taxes["taxes"].items():
            msg = "\n".join(tax["messages"])
            charge = self.generate_charge_for_corp(id, tax["total_tax"], msg)
            _ = charge
            total_tax += tax["total_tax"]

            # TODO: reimplement notificaitons
            # try:
            #     invoice.notify(message=invoice.note, title="Alliance Taxes")
            # except ObjectDoesNotExist:
            #     pass

        record = CorpTaxRecord.objects.create(
            name=f"Alliance Taxes {end_date}",
            start_date=start_date,
            end_date=end_date,
            total_tax=total_tax,
            json_dump=json.dumps(taxes, cls=ExtendedJsonEncoder),
        )
        char_obs = []
        char_ids = CharacterWalletJournalEntry.objects.filter(
            entry_id__in=taxes["char_trans_ids"]
        ).values_list("id", flat=True)
        for tid in char_ids:
            char_obs.append(CharacterPayoutTaxRecord(entry_id=tid, record=record))
        CharacterPayoutTaxRecord.objects.bulk_create(char_obs)

        corp_obs = []
        corp_ids = CorporationWalletJournalEntry.objects.filter(
            entry_id__in=taxes["corp_trans_ids"]
        ).values_list("id", flat=True)
        for tid in corp_ids:
            corp_obs.append(CorporatePayoutTaxRecord(entry_id=tid, record=record))
        CorporatePayoutTaxRecord.objects.bulk_create(corp_obs)

        return taxes


class CorporatePayoutTaxRecord(models.Model):
    entry = models.OneToOneField(
        CorporationWalletJournalEntry,
        on_delete=models.CASCADE,
        related_name="corp_payout_tax_record",
        related_query_name="corp_taxed",
    )

    processed = models.BooleanField(default=True)
    record = models.ForeignKey(CorpTaxRecord, on_delete=models.CASCADE)


class CharacterPayoutTaxRecord(models.Model):
    entry = models.OneToOneField(
        CharacterWalletJournalEntry,
        on_delete=models.CASCADE,
        related_name="character_payout_tax_record",
    )

    processed = models.BooleanField(default=True)
    record = models.ForeignKey(CorpTaxRecord, on_delete=models.CASCADE)

"""Admin site."""

# Third Party
from solo.admin import SingletonModelAdmin

# Django
from django.contrib import admin

# Accounting
from accounting import models


@admin.register(models.AccountingConfiguration)
class ConfigAdmin(SingletonModelAdmin):
    """
    config for the account config model
    """

    # Display updated fields in the list view
    list_display = ("bank_corp", "last_payment_datetime")
    search_fields = ("bank_corp__corporation_name",)
    filter_horizontal = ("ignored_corp",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "bank_corp",
                    "ignored_corp",
                    "last_payment_datetime",
                )
            },
        ),
    )

    # Make fields read-only
    readonly_fields = (
        # Uncomment this line when you want last_payment_datetime to be read-only
        # "last_payment_datetime",
    )


@admin.register(models.CharacterRattingTaxConfiguration)
class CharacterRattingTaxConfigurationAdmin(admin.ModelAdmin):
    """
    Config for character ratting tax model
    """

    list_display = ["__str__", "tax"]
    filter_horizontal = ["region_filter"]


@admin.register(models.CharacterPayoutTaxConfiguration)
class CharacterPayoutTaxConfigurationAdmin(admin.ModelAdmin):
    """
    Config for character tax model
    """

    # filter_horizontal = []
    autocomplete_fields = ["corporation"]
    list_display = ["name", "corporation", "wallet_transaction_type", "tax"]


@admin.register(models.CorpTaxPayoutTaxConfiguration)
class CorpTaxPayoutTaxConfigurationAdmin(admin.ModelAdmin):
    """
    Config for corp tax model
    """

    # filter_horizontal = []
    autocomplete_fields = ["corporation"]
    list_display = ["name", "corporation", "wallet_transaction_type", "tax"]


@admin.register(models.CorpTaxPerMemberTaxConfiguration)
class CorpTaxPerMemberTaxConfigurationAdmin(admin.ModelAdmin):
    """
    Config for corp tax model
    """

    # filter_horizontal = []
    list_display = ["state", "isk_per_main"]


@admin.register(models.CorpTaxConfiguration)
class CorpTaxConfigurationAdmin(admin.ModelAdmin):
    """
    Config for corp tax model
    """

    filter_horizontal = [
        "character_taxes_included",
        "corporate_taxes_included",
        "corporate_member_tax_included",
        "corporate_structure_tax_included",
        "exempted_corps",
        "character_ratting_included",
        "included_alliances",
    ]


@admin.register(models.CorpTaxPerServiceModuleConfiguration)
class CorpTaxPerServiceModuleConfigurationAdmin(admin.ModelAdmin):
    """
    Config for corp tax model
    """

    filter_horizontal = ["region_filter", "structure_type_filter"]


def generate_formatter(name, str_format):
    """
    Generate a formatter for admin list display.
    """

    def formatter(o):
        return str_format.format(getattr(o, name) or 0)

    formatter.short_description = name
    formatter.admin_order_field = name
    return formatter


@admin.register(models.CorpTaxRecord)
class CorpTaxRecordAdmin(admin.ModelAdmin):
    """
    Config for corp tax model
    """

    list_display = ["name", "start_date", "end_date", ("total_tax", "{:,}")]

    # generate a custom formater cause i am lazy...
    def __init__(self, *args, **kwargs):
        all_fields = []
        for f in self.list_display:
            if isinstance(f, str):
                all_fields.append(f)
            else:
                new_field_name = "_" + f[0]
                setattr(self, new_field_name, generate_formatter(f[0], f[1]))
                all_fields.append(new_field_name)
        self.list_display = all_fields

        super().__init__(*args, **kwargs)

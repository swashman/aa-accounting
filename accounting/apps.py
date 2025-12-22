"""App configuration"""

# Django
from django.apps import AppConfig
from django.utils.text import format_lazy

# Accounting
# Fleet Dash
# AA Accounting
from accounting import __title_translated__, __version__


class AccountingConfig(AppConfig):
    """App config"""

    name = "accounting"
    label = "accounting"
    verbose_name = format_lazy(
        "{app_title} v{version}", app_title=__title_translated__, version=__version__
    )

"""Routes."""

# Django
from django.urls import path

from . import __app_name__
from .views import admin, ajax, general

app_name: str = __app_name__

urlpatterns = [
    # Personal dashboard (default landing page)
    path("", general.character, name="default_dashboard"),
    # Character detail page, requires character id
    path(
        "character/<int:charid>/",
        general.character,
        name="character_dashboard",
    ),
    # Corporation pages
    path("corporation/", general.corporation, name="corporation_dashboard"),
    path(
        "corporation/<int:corpid>/",
        general.corporation,
        name="corporation_dashboard",
    ),
    # Admin section
    path("admin/dashboard/", admin.dashboard, name="admin_dashboard"),
    path("admin/corporations/", admin.corporations, name="admin_corporations"),
    path("admin/characters/", admin.characters, name="admin_characters"),
    path("admin/manual/", admin.manual, name="admin_manual"),
    # AJAX
    path(
        "ajax/character-ledger/<int:charid>",
        ajax.character_ledger,
        name="ajax_character_ledger",
    ),
    path(
        "ajax/corporation-ledger/<int:corpid>",
        ajax.corporation_ledger,
        name="ajax_corporation_ledger",
    ),
    path(
        "ajax/outstanding/",
        ajax.outstanding,
        name="ajax_outstanding",
    ),
]

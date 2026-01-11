"""General Views."""

# Django
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import redirect, render

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.framework.api.evecharacter import get_user_from_evecharacter
from allianceauth.framework.api.user import get_all_characters_from_user
from allianceauth.services.hooks import get_extension_logger

# Accounting
from accounting.models import AccountingConfiguration, CorpAccount, UserAccount

logger = get_extension_logger(__name__)


def get_bank_corp():
    """Get the bank corp"""
    config = AccountingConfiguration.get_solo()
    if config.bank_corp is not None:
        return config.bank_corp.corporation_name
    return "Not Set!"


@login_required
@permission_required("accounting.basic_access")
def character(request: WSGIRequest, charid: int = None) -> HttpResponse:
    """
    Displays a character's details to the user.

    Args:
        request: WSGIRequest object containing the user's request data.
        charid: int, optional. The character ID to display. Defaults to the user's main character.

    Returns:
        HttpResponse: The rendered HTML page containing the character's details.
    """

    if charid is None:
        charid = request.user.profile.main_character.character_id

    eve_character = EveCharacter.objects.get(character_id=charid)

    target_user = get_user_from_evecharacter(character=eve_character)

    # Character used for permission checks (viewer)
    viewer_main_char = request.user.profile.main_character

    # ---- Access checks (based on viewer) ----

    # 1) Viewer is viewing their own dashboard
    is_own_dashboard = request.user == target_user

    # 2) Viewer is CEO of the target user's corporation
    is_ceo_of_corp = viewer_main_char.character_id == eve_character.corporation.ceo_id

    # 3) Viewer is in the same corp AND has permission
    is_same_corp_with_perm = (
        viewer_main_char.corporation_id == eve_character.corporation_id
        and request.user.has_perm("accounting.view_own_corp")
    )

    # 4) Viewer has global permissions
    has_global_perm = request.user.has_perm(
        "accounting.view_all"
    ) or request.user.has_perm("accounting.finance_manager")

    # ---- Final decision ----
    if not (
        is_own_dashboard or is_ceo_of_corp or is_same_corp_with_perm or has_global_perm
    ):
        messages.error(request, "You do not have permission to view this dashboard.")
        return redirect("accounting:dashboard")

    logger.debug("Displaying page for: %s", target_user)
    account, created = UserAccount.objects.get_or_create(user=target_user)
    context = {
        "char_id": charid,
        "character": eve_character,
        "balance": account.balance,
        "corporation_name": get_bank_corp(),
    }

    return render(request, "accounting/dashboard.html", context)


@login_required
@permission_required("accounting.basic_access")
def corporation(request: WSGIRequest, corpid: int = None) -> HttpResponse:
    """
    Displays a corporation's details to the user.

    Args:
        request: WSGIRequest object containing the user's request data.
        corpid: int, optional. The corporation ID to display. Defaults to the user's main character's corporation.

    Returns:
        HttpResponse: The rendered HTML page containing the corporation's details.
    """

    if corpid is None:
        corpid = request.user.profile.main_character.corporation_id

    # Get user characters
    characters = get_all_characters_from_user(user=request.user, main_first=False)

    # Fetch the corporation
    eve_corporation = EveCorporationInfo.objects.get(corporation_id=corpid)

    # Pre-build sets for fast lookups
    character_ids = {char.character_id for char in characters}
    character_corp_ids = {char.corporation_id for char in characters}

    # ---- Access checks ----

    # 1) User is the CEO of the corporation
    is_ceo = eve_corporation.ceo_id in character_ids

    # 2) User has a character in the corporation AND has permission
    is_member_with_perm = (
        eve_corporation.corporation_id in character_corp_ids
        and request.user.has_perm("accounting.view_own_corp")
    )

    # 3) User has global accounting permissions
    has_global_perm = request.user.has_perm(
        "accounting.view_all"
    ) or request.user.has_perm("accounting.finance_manager")

    # ---- Final decision ----
    if not (is_ceo or is_member_with_perm or has_global_perm):

        # Inform the user why access was denied
        messages.error(request, "You do not have permission to view this corporation.")

        # Redirect to a safe fallback page
        return redirect("accounting:default_dashboard")

    account, _ = CorpAccount.objects.get_or_create(corporation=eve_corporation)
    context = {
        "corp_id": corpid,
        "corporation": eve_corporation,
        "balance": account.balance,
        "corporation_name": get_bank_corp(),
    }

    return render(request, "accounting/dashboard.html", context)

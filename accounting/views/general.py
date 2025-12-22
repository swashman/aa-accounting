"""General Views."""

# Django
from django.contrib.auth.decorators import login_required, permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import render

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
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

    # TODO: add checks to ensure user can access what they are asking for

    if charid is None:
        charid = request.user.profile.main_character.character_id

    eve_character = EveCharacter.objects.get(character_id=charid)
    logger.debug("Displaying page for: %s", request.user)
    account, created = UserAccount.objects.get_or_create(user=request.user)
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

    # TODO: add checks to ensure user can access what they are asking for

    if corpid is None:
        corpid = request.user.profile.main_character.corporation_id

    eve_corporation = EveCorporationInfo.objects.get(corporation_id=corpid)
    account, _ = CorpAccount.objects.get_or_create(corporation=eve_corporation)
    context = {
        "corp_id": corpid,
        "corporation": eve_corporation,
        "balance": account.balance,
        "corporation_name": get_bank_corp(),
    }

    return render(request, "accounting/dashboard.html", context)

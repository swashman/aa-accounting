"""Ajax Views"""

# Django
from django.contrib.auth.decorators import permission_required
from django.core.handlers.wsgi import WSGIRequest
from django.http import JsonResponse
from django.utils import timezone

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.framework.api.evecharacter import get_user_from_evecharacter
from allianceauth.services.hooks import get_extension_logger

# Accounting
from accounting.models import CorpAccount, UserAccount

logger = get_extension_logger(__name__)


@permission_required("accounting.basic_access")
def character_ledger(request: WSGIRequest, charid: int) -> JsonResponse:
    # Get the user's account
    try:
        character = EveCharacter.objects.get(character_id=charid)
        logger.debug("getting ledger for: %s", character)
        user = get_user_from_evecharacter(character)
        account = UserAccount.objects.get(user=user)

    except UserAccount.DoesNotExist:
        return JsonResponse({"error": "User account not found"}, status=404)

    # Pull ledger entries and order by newest first
    ledger_entries = account.ledger_entries.order_by("-created")
    logger.debug("ledger_entries: %s", ledger_entries)
    # Convert to JSON-friendly list
    data = [
        {
            "amount": float(entry.amount),
            "balance": float(entry.balance),
            "description": entry.description,
            "entry_type": entry.entry_type,
            "character_name": (
                entry.character.character_name if entry.character else None
            ),
            "created": entry.created.isoformat(),
        }
        for entry in ledger_entries
    ]
    logger.debug("data: %s", data)
    # Return the prepared data as a JSON response
    return JsonResponse(data=data, safe=False)


@permission_required("accounting.basic_access")
def corporation_ledger(request: WSGIRequest, corpid: int) -> JsonResponse:

    # Get the user's account
    try:
        corp = EveCorporationInfo.objects.get(corporation_id=corpid)
        account = CorpAccount.objects.get(corporation=corp)
    except UserAccount.DoesNotExist:
        return JsonResponse({"error": "Corp account not found"}, status=404)

    # Pull ledger entries and order by newest first
    ledger_entries = account.ledger_entries.order_by("-created")

    # Convert to JSON-friendly list
    data = [
        {
            "amount": float(entry.amount),
            "balance": float(entry.balance),
            "description": entry.description,
            "entry_type": entry.entry_type,
            "character_name": (
                entry.character.character_name if entry.character else None
            ),
            "created": entry.created.isoformat(),
        }
        for entry in ledger_entries
    ]
    # Return the prepared data as a JSON response
    return JsonResponse(data=data, safe=False)


@permission_required("accounting.basic_access")
def outstanding(request: WSGIRequest) -> JsonResponse:
    today = timezone.now()
    rows = []

    # Users
    for account in UserAccount.objects.outstanding():
        latest = max(
            account.ledger_entries.all(),
            key=lambda e: e.created,
            default=None,
        )
        days_outstanding = (today - latest.created).days if latest else 0

        rows.append(
            {
                "id": account.user.profile.main_character.character_id,
                "name": account.user.profile.main_character.character_name,
                "kind": "user",
                "amount": float(account.balance),
                "days_outstanding": days_outstanding,
            }
        )

    # Corps
    for account in CorpAccount.objects.outstanding():
        latest = max(
            account.ledger_entries.all(),
            key=lambda e: e.created,
            default=None,
        )
        days_outstanding = (today - latest.created).days if latest else 0

        rows.append(
            {
                "id": account.corporation.corporation_id,
                "name": account.corporation.corporation_name,
                "kind": "corp",
                "amount": float(account.balance),
                "days_outstanding": days_outstanding,
            }
        )

    return JsonResponse(rows, safe=False)

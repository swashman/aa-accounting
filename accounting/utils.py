# Alliance Auth
from allianceauth.eveonline.models import (
    EveAllianceInfo,
    EveCharacter,
    EveCorporationInfo,
)
from allianceauth.services.hooks import get_extension_logger

# Accounting
from accounting.providers import esi

logger = get_extension_logger(__name__)


class NoDataError(Exception):
    """
    NoDataError
    """

    def __init__(self, msg):
        Exception.__init__(self, msg)


# thank you to ppfeufer for this helper
def get_or_create_corporation_info(corporation_id: int) -> EveCorporationInfo:
    """
    Get or create corporation info

    :param corporation_id:
    :type corporation_id:
    :return:
    :rtype:
    """

    try:
        eve_corporation_info = EveCorporationInfo.objects.get(
            corporation_id=corporation_id
        )
    except EveCorporationInfo.DoesNotExist:
        eve_corporation_info = EveCorporationInfo.objects.create_corporation(
            corp_id=corporation_id
        )

        logger.info(
            msg=f"EveCorporationInfo object created: {eve_corporation_info.corporation_name}"
        )

    return eve_corporation_info


# thank you to ppfeufer for this helper
def get_or_create_character(
    name: str = None, character_id: int = None
) -> EveCharacter | None:
    """
    This function takes a name or id of a character and checks
    to see if the character already exists.
    If the character does not already exist, it will create the
    character object, and if needed the corp/alliance objects as well.

    :param name:
    :type name:
    :param character_id:
    :type character_id:
    :return:
    :rtype:
    """

    eve_character = None

    if name:
        # If a name is passed to this function, we have to check it on ESI
        operation = esi.client.Universe.PostUniverseIds(body=[name])
        result = operation.result()

        if not result or not result.characters:
            return None

        character_id = result.characters[0].id
        eve_character = EveCharacter.objects.filter(character_id=character_id)
    elif character_id:
        # If an ID is passed to this function, we can just check the db for it.
        eve_character = EveCharacter.objects.filter(character_id=character_id)
    elif not name and not character_id:
        raise NoDataError(msg="No character name or character id provided.")

    if eve_character is not None and len(eve_character) == 0:
        # Create character
        character = EveCharacter.objects.create_character(character_id=character_id)
        character = EveCharacter.objects.get(pk=character.pk)

        logger.info(msg=f"EveCharacter Object created: {character.character_name}")

        # Create alliance and corporation info objects if not already exists for
        # future sanity
        if character.alliance_id is not None:
            # Create alliance and corporation info objects if not already exists
            if not EveAllianceInfo.objects.filter(
                alliance_id=character.alliance_id
            ).exists():
                EveAllianceInfo.objects.create_alliance(
                    alliance_id=character.alliance_id
                )
        else:
            # Create corporation info object if not already exists
            if not EveCorporationInfo.objects.filter(
                corporation_id=character.corporation_id
            ).exists():
                EveCorporationInfo.objects.create_corporation(
                    corp_id=character.corporation_id
                )
    else:
        character = eve_character[0]

    return character

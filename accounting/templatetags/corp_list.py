# Django
from django import template

# Alliance Auth
from allianceauth.eveonline.models import EveCorporationInfo
from allianceauth.framework.api.user import get_all_characters_from_user
from allianceauth.services.hooks import get_extension_logger

register = template.Library()

logger = get_extension_logger(__name__)


@register.inclusion_tag(
    "accounting/partials/navigation/corp-list.html", takes_context=True
)
def corp_list(context):

    characters = get_all_characters_from_user(
        user=context.request.user, main_first=False
    )
    logger.debug("characters: %s", characters)
    character_ids = [c.character_id for c in characters]

    corps = EveCorporationInfo.objects.filter(ceo_id__in=character_ids)
    logger.debug("corps: %s", corps)
    return {
        "corps": corps,
        "request": context["request"],
    }

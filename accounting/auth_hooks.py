"""Hook into Alliance Auth"""

# Alliance Auth
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

# Accounting
# Fleet Dash
# AA Accounting
from accounting import __title_translated__

from . import urls


class ExampleMenuItem(MenuItemHook):
    """This class ensures only authorized users will see the menu entry"""

    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            __title_translated__,
            "fas fa-sack-dollar",
            "accounting:default_dashboard",
            navactive=["accounting:"],
        )

    def render(self, request):
        """Render the menu item"""
        if request.user.has_perm("accounting.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    """Register the menu item"""
    return ExampleMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register app urls"""
    return UrlHook(urls, namespace="accounting", base_url=r"^accounting/")

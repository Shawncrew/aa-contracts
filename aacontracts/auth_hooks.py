from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import urls


class ContractsMenuItem(MenuItemHook):
    def __init__(self):
        super().__init__(
            "Contracts",
            "fa-solid fa-file-contract",
            "aacontracts:index",
            navactive=["aacontracts:"],
        )

    def render(self, request):
        if request.user.has_perm("aacontracts.view_contracts"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return ContractsMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aacontracts", r"^contracts/")

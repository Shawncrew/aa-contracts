"""Carry the signed-in editor through the AA Fittings save call."""
from contextvars import ContextVar


_edit = ContextVar("aacontracts_fitting_edit", default=None)


def fitting_editor_name(fitting_id):
    edit = _edit.get()
    if edit is None or edit[0] != str(fitting_id):
        return None
    user = edit[1].user
    if not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    main = getattr(profile, "main_character", None)
    return main.character_name if main else None


class FittingEditorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _edit.set(None)
        try:
            return self.get_response(request)
        finally:
            _edit.reset(token)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method == "POST" and request.resolver_match.view_name == "fittings:edit_fit":
            _edit.set((str(view_kwargs["fit_id"]), request))

from django.utils.translation import gettext_lazy

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")

__version__ = "1.0.3"


class PluginApp(PluginConfig):
    name = "pretix_invoice_modification"
    verbose_name = "Pretix Invoice Modification"

    class PretixPluginMeta:
        name = gettext_lazy("Pretix Invoice Modification")
        author = "Markus Schmidl"
        description = gettext_lazy("Short description")
        visible = True
        version = __version__
        category = "CUSTOMIZATION"
        compatibility = "pretix>=2.7.0"

    def ready(self):
        from . import signals  # NOQA


default_app_config = "pretix_invoice_modification.PluginApp"

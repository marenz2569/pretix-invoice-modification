from django.dispatch import receiver

from pretix.base.signals import register_invoice_renderers

@receiver(register_invoice_renderers, dispatch_uid="invoice_renderer_modified")
def recv_modification(sender, **kwargs):
    from .invoice import ModifiedInvoiceRenderer
    return ModifiedInvoiceRenderer

from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal

class CustomerPortalExtended(CustomerPortal):

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        # puoi aggiungere dati generici se vuoi
        return values

    @http.route(['/my/orders/<int:order_id>'], type='http', auth="user", website=True)
    def portal_order_page(self, order_id, **kw):
        response = super().portal_order_page(order_id, **kw)
        order = request.env['sale.order'].browse(order_id)
        # qui aggiungi i campi personalizzati ai valori del template
        if response.qcontext:
            response.qcontext.update({
                'cassa_amount': order.cassa_amount,
                'cassa_percent': order.cassa_percent,
                'withholding_amount': order.withholding_amount,
                'withholding_percent': order.withholding_percent,
                'total_gross': order.total_gross,
            })
        return response


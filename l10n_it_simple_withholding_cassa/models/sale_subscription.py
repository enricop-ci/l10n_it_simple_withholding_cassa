from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.translate import _

class SaleSubscription(models.Model):
    _inherit = 'sale.subscription'

    # Flag e parametri
    apply_withholding = fields.Boolean(
        string="Applica Ritenuta d'acconto",
        default=lambda self: self.env.company.enable_withholding_tax,
    )
    withholding_percent = fields.Float(string="Ritenuta %", default=20.0)

    apply_cassa = fields.Boolean(
        string="Applica Cassa Previdenziale",
        default=lambda self: self.env.company.enable_cassa_previdenziale,
    )
    cassa_percent = fields.Float(string="Cassa %", default=4.0)

    # Totali personalizzati
    cassa_amount = fields.Monetary(
        string="Importo Cassa Previdenziale",
        compute="_compute_amounts", 
        store=True,
        currency_field='currency_id'
    )

    total_gross = fields.Monetary(
        string="Totale lordo",
        compute="_compute_amounts", 
        store=True,
        currency_field='currency_id'
    )

    withholding_amount = fields.Monetary(
        string="Importo Ritenuta",
        compute="_compute_amounts", 
        store=True,
        currency_field='currency_id'
    )

    net_amount = fields.Monetary(
        string='Netto a Pagare',
        compute="_compute_amounts", 
        store=True,
        currency_field='currency_id'
    )

    @api.depends(
        'order_line.price_subtotal',
        'apply_withholding',
        'withholding_percent',
        'apply_cassa',
        'cassa_percent',
        'recurring_total',
        'recurring_tax_total',
    )
    def _compute_amounts(self):
        for subscription in self:
            # Usa il recurring_total come base (già calcolato da Odoo)
            amount_untaxed = subscription.recurring_total - subscription.recurring_tax_total

            # Calcolo Cassa Previdenziale
            cassa_amount = 0.0
            if subscription.apply_cassa:
                cassa_amount = amount_untaxed * subscription.cassa_percent / 100.0

            # Totale lordo (con tasse e cassa)
            total_gross = subscription.recurring_total + cassa_amount

            # Calcolo Ritenuta d'acconto (su imponibile + cassa)
            withholding_amount = 0.0
            if subscription.apply_withholding:
                withholding_base = amount_untaxed + cassa_amount
                withholding_amount = withholding_base * subscription.withholding_percent / 100.0

            # Netto a pagare
            net_amount = total_gross - withholding_amount

            # Assegno i valori
            subscription.cassa_amount = cassa_amount
            subscription.total_gross = total_gross
            subscription.withholding_amount = withholding_amount
            subscription.net_amount = net_amount

    @api.model
    def _check_dependencies(self):
        """Check if required modules are installed"""
        module = self.env['ir.module.module'].search([('name', '=', 'sale_subscription')])
        if not module or module.state != 'installed':
            raise UserError(_("The sale_subscription module must be installed first"))
        return True

    def _prepare_renewal_values(self, **kwargs):
        self._check_dependencies()
        """Inherit renewal method to copy withholding and cassa values"""
        values = super()._prepare_renewal_values(**kwargs)
        values.update({
            'apply_cassa': self.apply_cassa,
            'cassa_percent': self.cassa_percent,
            'apply_withholding': self.apply_withholding,
            'withholding_percent': self.withholding_percent,
        })
        return values
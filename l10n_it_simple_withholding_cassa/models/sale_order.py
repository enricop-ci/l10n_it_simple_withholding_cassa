from odoo import models, fields, api
import logging
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

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

    # Valute
    currency_id = fields.Many2one(related='pricelist_id.currency_id', store=True)

    # Totali personalizzati (tutti calcolati in _amount_all)
    amount_untaxed = fields.Monetary(
        string='Imponibile',
        compute='_amount_all', store=True, readonly=True)

    cassa_amount = fields.Monetary(
        string="Importo Cassa Previdenziale",
        compute="_amount_all", store=True)

    amount_tax = fields.Monetary(
        string='IVA',
        compute='_amount_all', store=True, readonly=True)

    total_gross = fields.Monetary(
        string="Totale lordo",
        compute='_amount_all', store=True, readonly=True)

    withholding_amount = fields.Monetary(
        string="Importo Ritenuta",
        compute="_amount_all", store=True)

    net_amount = fields.Monetary(
        string='Netto a Pagare',
        compute='_amount_all', store=True, readonly=True)

    amount_total = fields.Monetary(
        string="Totale a pagare",
        compute='_amount_all', store=True, readonly=True)

    vat_label = fields.Char(string="Etichetta IVA", compute="_compute_vat_label", store=False)

    @api.depends('order_line.tax_id')
    def _compute_vat_label(self):
        for order in self:
            taxes = order.order_line.mapped('tax_id')
            if taxes:
                order.vat_label = f"IVA {taxes[0].amount:.0f}%"
            else:
                order.vat_label = "IVA"

    @api.depends(
        'order_line.price_subtotal',
        'order_line.tax_id',
        'apply_withholding',
        'withholding_percent',
        'apply_cassa',
        'cassa_percent',
    )
    def _amount_all(self):
        for order in self:
            amount_untaxed = sum(line.price_subtotal for line in order.order_line)

            # Calcolo Cassa
            cassa_amount = 0.0
            if order.apply_cassa:
                cassa_amount = float_round(amount_untaxed * order.cassa_percent / 100.0, precision_digits=2)

            # Base imponibile con cassa
            base_imponibile = amount_untaxed + cassa_amount

            # Calcolo IVA su base con cassa
            amount_tax = 0.0
            for line in order.order_line:
                base_line = line.price_subtotal
                if order.apply_cassa:
                    base_line += base_line * order.cassa_percent / 100.0
                line_taxes = line.tax_id.filtered(lambda t: t.amount_type == 'percent')
                line_tax_amount = sum(base_line * t.amount / 100.0 for t in line_taxes)
                amount_tax += line_tax_amount
            amount_tax = float_round(amount_tax, precision_digits=2)

            # Totale lordo (base + IVA)
            total_gross = base_imponibile + amount_tax

            # Ritenuta d'acconto
            withholding_amount = 0.0
            if order.apply_withholding:
                withholding_amount = float_round(base_imponibile * order.withholding_percent / 100.0, precision_digits=2)

            # Totale netto
            total_net = float_round(total_gross - withholding_amount, precision_digits=2)

            # Assegnazione ai campi
            order.amount_untaxed = amount_untaxed
            order.cassa_amount = cassa_amount
            order.amount_tax = amount_tax
            order.total_gross = total_gross
            order.withholding_amount = withholding_amount
            order.amount_total = total_net
            order.net_amount = total_net


from odoo import models, fields, api
from odoo.tools import float_round

class AccountMove(models.Model):
    _inherit = 'account.move'

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

    cassa_amount = fields.Monetary(
        string="Importo Cassa Previdenziale",
        compute="_compute_amounts", store=True)

    total_gross = fields.Monetary(
        string="Totale lordo",
        compute="_compute_amounts", store=True)

    withholding_amount = fields.Monetary(
        string="Importo Ritenuta",
        compute="_compute_amounts", store=True)

    net_amount = fields.Monetary(
        string='Netto a Pagare',
        compute="_compute_amounts", store=True)

    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.tax_ids',
        'apply_withholding',
        'withholding_percent',
        'apply_cassa',
        'cassa_percent',
    )
    def _compute_amounts(self):
        for move in self:
            amount_untaxed = sum(line.price_subtotal for line in move.invoice_line_ids)

            # Calcolo Cassa Previdenziale
            cassa_amount = 0.0
            if move.apply_cassa:
                cassa_amount = float_round(amount_untaxed * move.cassa_percent / 100.0, precision_rounding=move.currency_id.rounding)

            base_imponibile = amount_untaxed + cassa_amount

            # Calcolo IVA su base con cassa
            amount_tax = 0.0
            for line in move.invoice_line_ids:
                base_line = line.price_subtotal
                if move.apply_cassa:
                    base_line += base_line * move.cassa_percent / 100.0
                line_taxes = line.tax_ids.filtered(lambda t: t.amount_type == 'percent')
                line_tax_amount = sum(base_line * t.amount / 100.0 for t in line_taxes)
                amount_tax += line_tax_amount
            amount_tax = float_round(amount_tax, precision_rounding=move.currency_id.rounding)

            total_gross = base_imponibile + amount_tax

            # Calcolo Ritenuta d'acconto
            withholding_amount = 0.0
            if move.apply_withholding:
                withholding_amount = float_round(base_imponibile * move.withholding_percent / 100.0, precision_rounding=move.currency_id.rounding)

            total_net = float_round(total_gross - withholding_amount, precision_rounding=move.currency_id.rounding)

            # Assegno i valori calcolati ai campi
            move.cassa_amount = cassa_amount
            move.total_gross = total_gross
            move.withholding_amount = withholding_amount
            move.net_amount = total_net


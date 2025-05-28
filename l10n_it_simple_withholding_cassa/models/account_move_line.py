from odoo import api, models, fields

class AccountMove(models.Model):
    _inherit = 'account.move'

    apply_withholding = fields.Boolean(
        string="Applica Ritenuta d'acconto",
        default=lambda self: self.env.company.enable_withholding_tax
    )
    withholding_percent = fields.Float(string="Ritenuta %", default=20.0)

    apply_cassa = fields.Boolean(
        string="Applica Cassa Previdenziale",
        default=lambda self: self.env.company.enable_cassa_previdenziale
    )
    cassa_percent = fields.Float(string="Cassa %", default=4.0)

    @api.onchange('invoice_line_ids', 'apply_withholding', 'withholding_percent', 'apply_cassa', 'cassa_percent')
    def _onchange_withholding_cassa(self):
        if self.move_type not in ['out_invoice', 'out_refund'] or self.state != 'draft':
            return

        original_lines = self.invoice_line_ids.filtered(lambda l: not l.name.startswith('[AUTO]'))
        self.invoice_line_ids = original_lines

        base_total = sum(original_lines.mapped('price_subtotal'))
        new_lines = original_lines

        if self.apply_cassa and base_total:
            cassa_amount = base_total * self.cassa_percent / 100.0
            new_lines += self.env['account.move.line'].new({
                'name': f"[AUTO] Cassa Previdenziale {self.cassa_percent:.1f}%",
                'price_unit': cassa_amount,
                'quantity': 1.0,
                'account_id': self.journal_id.default_account_id.id,
            })

        if self.apply_withholding and base_total:
            ritenuta_amount = - base_total * self.withholding_percent / 100.0
            new_lines += self.env['account.move.line'].new({
                'name': f"[AUTO] Ritenuta d'acconto {self.withholding_percent:.1f}%",
                'price_unit': ritenuta_amount,
                'quantity': 1.0,
                'account_id': self.journal_id.default_account_id.id,
            })

        self.invoice_line_ids = new_lines

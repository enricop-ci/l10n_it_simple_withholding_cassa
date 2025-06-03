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

        # Calculate cassa first
        cassa_amount = 0
        if self.apply_cassa and base_total:
            # Trova l'imposta IVA 22%
            tax_22 = self.env['account.tax'].search([
                ('type_tax_use', '=', 'sale'),
                ('amount', '=', 22),
                ('company_id', '=', self.company_id.id)
            ], limit=1)

            # Trova il conto per cassa previdenziale (ricavo)
            cassa_account = self.env['account.account'].search([
                ('code', 'like', '701%'),  # Conto ricavi servizi
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            if not cassa_account:
                cassa_account = self.journal_id.default_account_id

            cassa_amount = base_total * self.cassa_percent / 100.0
            new_lines += self.env['account.move.line'].new({
                'name': f"[AUTO] Cassa Previdenziale {self.cassa_percent:.1f}%",
                'price_unit': cassa_amount,
                'quantity': 1.0,
                'account_id': cassa_account.id,
                'tax_ids': [(6, 0, [tax_22.id])] if tax_22 else [],  # Aggiunge IVA 22%
            })

        # Then calculate withholding including cassa
        if self.apply_withholding and base_total:
            # Trova il conto per ritenuta d'acconto (credito verso erario)
            withholding_account = self.env['account.account'].search([
                ('code', 'like', '144%'),  # Crediti verso erario per ritenute
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            if not withholding_account:
                withholding_account = self.env['account.account'].search([
                    ('code', 'like', '1440%'),
                    ('company_id', '=', self.company_id.id)
                ], limit=1)
            if not withholding_account:
                # Fallback su un conto di debito generico
                withholding_account = self.env['account.account'].search([
                    ('account_type', '=', 'asset_current'),
                    ('company_id', '=', self.company_id.id)
                ], limit=1)

            withholding_base = base_total + cassa_amount  # Include cassa in withholding base
            ritenuta_amount = - withholding_base * self.withholding_percent / 100.0
            new_lines += self.env['account.move.line'].new({
                'name': f"[AUTO] Ritenuta d'acconto {self.withholding_percent:.1f}%",
                'price_unit': ritenuta_amount,
                'quantity': 1.0,
                'account_id': withholding_account.id,
            })

        self.invoice_line_ids = new_lines

    @api.depends(
        'invoice_line_ids.price_subtotal',
        'invoice_line_ids.tax_ids',
        'apply_withholding',
        'withholding_percent',
        'apply_cassa',
        'cassa_percent',
    )
    def _compute_amount(self):
        super()._compute_amount()
        for move in self:
            if move.move_type not in ['out_invoice', 'out_refund']:
                continue

            # Separa le righe normali da quelle auto
            normal_lines = move.invoice_line_ids.filtered(lambda l: not (l.name and l.name.startswith('[AUTO]')))
            auto_lines = move.invoice_line_ids - normal_lines
            
            # Calcola imponibile base dalle righe normali
            amount_untaxed = sum(normal_lines.mapped('price_subtotal'))

            # Trova riga cassa e ritenuta
            cassa_line = auto_lines.filtered(lambda l: 'Cassa Previdenziale' in (l.name or ''))
            ritenuta_line = auto_lines.filtered(lambda l: 'Ritenuta' in (l.name or ''))

            # Prendi i valori dalle righe
            cassa_amount = sum(cassa_line.mapped('price_subtotal')) if cassa_line else 0.0
            withholding_amount = -sum(ritenuta_line.mapped('price_subtotal')) if ritenuta_line else 0.0

            # CORREZIONE: Calcola IVA totale usando il metodo corretto
            # Invece di price_tax (che non esiste), calcola la differenza
            amount_tax = 0.0
            for line in move.invoice_line_ids:
                if line.tax_ids:
                    # Calcola le tasse per ogni riga
                    tax_results = line.tax_ids.compute_all(
                        line.price_unit,
                        currency=move.currency_id,
                        quantity=line.quantity,
                        product=line.product_id,
                        partner=move.partner_id
                    )
                    amount_tax += sum(tax['amount'] for tax in tax_results['taxes'])

            # Calcola totali
            total_gross = amount_untaxed + cassa_amount + amount_tax
            total_net = total_gross - withholding_amount

            # Assegnazione ai campi
            move.amount_untaxed = amount_untaxed
            move.amount_tax = amount_tax
            move.amount_total = total_gross
            move.amount_residual = total_net
            move.cassa_amount = cassa_amount
            move.withholding_amount = withholding_amount
from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        """Override create per aggiornare le righe fiscali quando si aggiunge una riga"""
        # Se stiamo creando righe fiscali, non attivare l'aggiornamento
        if self.env.context.get('skip_fiscal_update'):
            return super().create(vals_list)

        results = super().create(vals_list)

        # Raccogli le fatture che necessitano aggiornamento
        moves_to_update = set()

        for result in results:
            # Se è una riga di una fattura cliente/fornitore, marca per aggiornamento
            if (result.move_id and
                result.move_id.move_type in ['out_invoice', 'out_refund'] and
                result.move_id.state == 'draft' and
                not result.move_id._is_fiscal_line(result)):  # Non è una riga fiscale

                moves_to_update.add(result.move_id)

        # Aggiorna tutte le fatture interessate una sola volta
        for move in moves_to_update:
            move._update_fiscal_lines()

        return results

    def write(self, vals):
        """Override write per aggiornare le righe fiscali quando si modifica una riga"""
        # Se stiamo aggiornando righe fiscali, non attivare l'aggiornamento
        if self.env.context.get('skip_fiscal_update'):
            return super().write(vals)

        result = super().write(vals)

        # Se si modificano campi che influenzano i calcoli
        fiscal_impact_fields = ['price_unit', 'quantity', 'tax_ids', 'product_id']
        if any(field in vals for field in fiscal_impact_fields):
            moves_to_update = set()

            for line in self:
                if (line.move_id and
                    line.move_id.move_type in ['out_invoice', 'out_refund'] and
                    line.move_id.state == 'draft' and
                    not line.move_id._is_fiscal_line(line)):  # Non è una riga fiscale

                    moves_to_update.add(line.move_id)

            # Aggiorna tutte le fatture interessate
            for move in moves_to_update:
                move._update_fiscal_lines()

        return result

    def unlink(self):
        """Override unlink per aggiornare le righe fiscali quando si elimina una riga"""
        # Se stiamo cancellando righe fiscali, non attivare l'aggiornamento
        if self.env.context.get('skip_fiscal_update'):
            return super().unlink()

        moves_to_update = set()

        for line in self:
            if (line.move_id and
                line.move_id.move_type in ['out_invoice', 'out_refund'] and
                line.move_id.state == 'draft' and
                not line.move_id._is_fiscal_line(line)):  # Non è una riga fiscale

                moves_to_update.add(line.move_id)

        result = super().unlink()

        # Aggiorna le fatture interessate
        for move in moves_to_update:
            move._update_fiscal_lines()

        return result


class AccountMoveWithFiscalLines(models.Model):
    """Estensione di AccountMove con la logica di aggiornamento delle righe fiscali"""
    _inherit = 'account.move'

    def _update_fiscal_lines(self):
        """Aggiorna le righe fiscali nella fattura"""
        self.ensure_one()

        if self.move_type not in ['out_invoice', 'out_refund'] or self.state != 'draft':
            return

        # Usa il context per evitare loop infiniti invece di attributi dinamici
        if self.env.context.get('updating_fiscal_lines'):
            return

        # Crea un nuovo context con il flag per evitare loop
        new_context = dict(self.env.context, updating_fiscal_lines=True, skip_fiscal_update=True)

        # Lavora con il nuovo context
        self_with_context = self.with_context(new_context)

        # Rimuovi righe fiscali esistenti
        fiscal_lines = self_with_context.invoice_line_ids.filtered(self._is_fiscal_line)
        if fiscal_lines:
            fiscal_lines.unlink()

        # Calcola la base per le righe fiscali (senza le righe fiscali)
        normal_lines = self_with_context.invoice_line_ids.filtered(lambda l: not self._is_fiscal_line(l))
        base_amount = sum(line.price_subtotal for line in normal_lines)

        if not base_amount:
            return

        # Trova il conto e le imposte per le righe fiscali
        default_account = self_with_context._get_default_account()
        main_tax_ids = self_with_context._get_main_tax_ids(normal_lines)

        # Crea le righe fiscali
        lines_to_create = []

        # Riga cassa previdenziale
        if self.apply_cassa and self.cassa_percent > 0:
            cassa_amount = base_amount * (self.cassa_percent / 100.0)
            cassa_account = self_with_context._get_fiscal_account('cassa') or default_account

            if cassa_account:
                lines_to_create.append({
                    'name': f'Cassa previdenziale {self.cassa_percent}%',
                    'account_id': cassa_account.id,
                    'quantity': 1,
                    'price_unit': cassa_amount,
                    'tax_ids': [(6, 0, main_tax_ids)],  # Stesse imposte del prodotto principale
                    'move_id': self.id,
                })

        # Riga ritenuta d'acconto
        if self.apply_withholding and self.withholding_percent > 0:
            # La ritenuta si calcola su base + cassa
            withholding_base = base_amount
            if self.apply_cassa:
                withholding_base += base_amount * (self.cassa_percent / 100.0)

            withholding_amount = withholding_base * (self.withholding_percent / 100.0)
            withholding_account = self_with_context._get_fiscal_account('withholding') or default_account

            if withholding_account:
                lines_to_create.append({
                    'name': f'Ritenuta d\'acconto {self.withholding_percent}%',
                    'account_id': withholding_account.id,
                    'quantity': 1,
                    'price_unit': -withholding_amount,  # Negativo per ridurre il totale
                    'tax_ids': [(6, 0, [])],  # Nessuna IVA sulla ritenuta
                    'move_id': self.id,
                })

        # Crea tutte le righe fiscali in una volta con il context di protezione
        if lines_to_create:
            self.env['account.move.line'].with_context(new_context).create(lines_to_create)

    def _get_default_account(self):
        """Restituisce un conto di default per le righe fiscali"""
        return self.journal_id.default_account_id

    def _get_main_tax_ids(self, normal_lines):
        """Restituisce le imposte del prodotto principale"""
        main_line = normal_lines.filtered(lambda l: l.product_id)[:1]
        return main_line.tax_ids.ids if main_line else []

    def _get_fiscal_account(self, fiscal_type):
        """Restituisce il conto fiscale configurato"""
        company = self.env.company

        if fiscal_type == 'cassa':
            # Conto cassa previdenziale
            if hasattr(company, 'cassa_account_id') and company.cassa_account_id:
                return company.cassa_account_id
            # Fallback: cerca il conto 310200
            return self.env['account.account'].search([
                ('code', '=', '310200'),
            ], limit=1)

        elif fiscal_type == 'withholding':
            # Conto ritenuta d'acconto
            if hasattr(company, 'withholding_account_id') and company.withholding_account_id:
                return company.withholding_account_id
            # Fallback: cerca il conto 160900
            return self.env['account.account'].search([
                ('code', '=', '160900'),
            ], limit=1)

        return None

    @api.onchange('apply_cassa', 'apply_withholding', 'cassa_percent', 'withholding_percent')
    def _onchange_fiscal_settings(self):
        """Aggiorna le righe fiscali quando cambiano le impostazioni"""
        if self.state == 'draft' and self.move_type in ['out_invoice', 'out_refund']:
            # Solo messaggio informativo, l'aggiornamento avverrà automaticamente
            if (self.apply_cassa or self.apply_withholding) and self.invoice_line_ids:
                return {
                    'warning': {
                        'title': 'Aggiornamento Automatico',
                        'message': 'Le righe fiscali verranno aggiornate automaticamente quando salvi o modifichi le righe prodotto.'
                    }
                }
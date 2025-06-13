from odoo import models, fields, api


class SaleSubscriptionLine(models.Model):
    _inherit = 'sale.subscription.line'

    @api.model_create_multi
    def create(self, vals_list):
        """Override create per aggiornare le righe fiscali quando si aggiunge una riga"""
        # Se stiamo creando righe fiscali, non attivare l'aggiornamento
        if self.env.context.get('skip_fiscal_update'):
            return super().create(vals_list)

        results = super().create(vals_list)

        # Raccogli gli abbonamenti che necessitano aggiornamento
        subscriptions_to_update = set()

        for result in results:
            # Se è una riga di un abbonamento, marca per aggiornamento
            if (result.analytic_account_id and
                result.analytic_account_id.state in ['draft', 'open'] and
                not result.analytic_account_id._is_fiscal_line(result)):  # Non è una riga fiscale

                subscriptions_to_update.add(result.analytic_account_id)

        # Aggiorna tutti gli abbonamenti interessati una sola volta
        for subscription in subscriptions_to_update:
            subscription._update_fiscal_lines()

        return results

    def write(self, vals):
        """Override write per aggiornare le righe fiscali quando si modifica una riga"""
        # Se stiamo aggiornando righe fiscali, non attivare l'aggiornamento
        if self.env.context.get('skip_fiscal_update'):
            return super().write(vals)

        result = super().write(vals)

        # Se si modificano campi che influenzano i calcoli
        fiscal_impact_fields = ['price_unit', 'quantity', 'uom_id', 'product_id']
        if any(field in vals for field in fiscal_impact_fields):
            subscriptions_to_update = set()

            for line in self:
                if (line.analytic_account_id and
                    line.analytic_account_id.state in ['draft', 'open'] and
                    not line.analytic_account_id._is_fiscal_line(line)):  # Non è una riga fiscale

                    subscriptions_to_update.add(line.analytic_account_id)

            # Aggiorna tutti gli abbonamenti interessati
            for subscription in subscriptions_to_update:
                subscription._update_fiscal_lines()

        return result

    def unlink(self):
        """Override unlink per aggiornare le righe fiscali quando si elimina una riga"""
        # Se stiamo cancellando righe fiscali, non attivare l'aggiornamento
        if self.env.context.get('skip_fiscal_update'):
            return super().unlink()

        subscriptions_to_update = set()

        for line in self:
            if (line.analytic_account_id and
                line.analytic_account_id.state in ['draft', 'open'] and
                not line.analytic_account_id._is_fiscal_line(line)):  # Non è una riga fiscale

                subscriptions_to_update.add(line.analytic_account_id)

        result = super().unlink()

        # Aggiorna gli abbonamenti interessati
        for subscription in subscriptions_to_update:
            subscription._update_fiscal_lines()

        return result


class SaleSubscriptionWithFiscalLines(models.Model):
    """Estensione di SaleSubscription con la logica di aggiornamento delle righe fiscali"""
    _inherit = 'sale.subscription'

    def _is_fiscal_line(self, line):
        """Identifica se una riga è una riga fiscale auto-generata"""
        if not line.name:
            return False
        return ('Cassa previdenziale' in line.name or
                'Ritenuta d\'acconto' in line.name)

    def _update_fiscal_lines(self):
        """Aggiorna le righe fiscali nell'abbonamento"""
        self.ensure_one()

        if self.state not in ['draft', 'open']:
            return

        # Usa il context per evitare loop infiniti
        if self.env.context.get('updating_fiscal_lines'):
            return

        # Crea un nuovo context con il flag per evitare loop
        new_context = dict(self.env.context, updating_fiscal_lines=True, skip_fiscal_update=True)

        # Lavora con il nuovo context
        self_with_context = self.with_context(new_context)

        # Rimuovi righe fiscali esistenti
        fiscal_lines = self_with_context.recurring_invoice_line_ids.filtered(self._is_fiscal_line)
        if fiscal_lines:
            fiscal_lines.unlink()

        # Calcola la base per le righe fiscali (senza le righe fiscali)
        normal_lines = self_with_context.recurring_invoice_line_ids.filtered(lambda l: not self._is_fiscal_line(l))
        base_amount = sum(line.price_subtotal for line in normal_lines)

        if not base_amount:
            return

        # Crea le righe fiscali
        lines_to_create = []

        # Riga cassa previdenziale
        if self.apply_cassa and self.cassa_percent > 0:
            cassa_amount = base_amount * (self.cassa_percent / 100.0)

            lines_to_create.append({
                'name': f'Cassa previdenziale {self.cassa_percent}%',
                'product_id': self_with_context._get_fiscal_product('cassa'),
                'quantity': 1,
                'price_unit': cassa_amount,
                'uom_id': self.env.ref('uom.product_uom_unit').id,
                'analytic_account_id': self.id,
            })

        # Riga ritenuta d'acconto
        if self.apply_withholding and self.withholding_percent > 0:
            # La ritenuta si calcola su base + cassa
            withholding_base = base_amount
            if self.apply_cassa:
                withholding_base += base_amount * (self.cassa_percent / 100.0)

            withholding_amount = withholding_base * (self.withholding_percent / 100.0)

            lines_to_create.append({
                'name': f'Ritenuta d\'acconto {self.withholding_percent}%',
                'product_id': self_with_context._get_fiscal_product('withholding'),
                'quantity': 1,
                'price_unit': -withholding_amount,  # Negativo per ridurre il totale
                'uom_id': self.env.ref('uom.product_uom_unit').id,
                'analytic_account_id': self.id,
            })

        # Crea tutte le righe fiscali in una volta con il context di protezione
        if lines_to_create:
            self.env['sale.subscription.line'].with_context(new_context).create(lines_to_create)

    def _get_fiscal_product(self, fiscal_type):
        """Restituisce il prodotto fiscale o crea uno generico"""
        company = self.env.company

        if fiscal_type == 'cassa':
            # Cerca un prodotto per la cassa previdenziale
            product = self.env['product.product'].search([
                ('name', 'ilike', 'cassa previdenziale'),
                ('type', '=', 'service')
            ], limit=1)

            if not product:
                # Crea un prodotto generico per la cassa
                product = self._create_fiscal_product(
                    'Cassa Previdenziale',
                    'Contributo cassa previdenziale'
                )
            return product.id

        elif fiscal_type == 'withholding':
            # Cerca un prodotto per la ritenuta
            product = self.env['product.product'].search([
                ('name', 'ilike', 'ritenuta'),
                ('type', '=', 'service')
            ], limit=1)

            if not product:
                # Crea un prodotto generico per la ritenuta
                product = self._create_fiscal_product(
                    'Ritenuta d\'Acconto',
                    'Ritenuta d\'acconto su prestazioni professionali'
                )
            return product.id

        return None

    def _create_fiscal_product(self, name, description):
        """Crea un prodotto fiscale generico"""
        return self.env['product.product'].create({
            'name': name,
            'description': description,
            'type': 'service',
            'invoice_policy': 'order',
            'list_price': 0.0,
            'taxes_id': [],  # Nessuna imposta di default
        })

    @api.onchange('apply_cassa', 'apply_withholding', 'cassa_percent', 'withholding_percent')
    def _onchange_fiscal_settings(self):
        """Aggiorna le righe fiscali quando cambiano le impostazioni"""
        if self.state in ['draft', 'open']:
            # Solo messaggio informativo, l'aggiornamento avverrà automaticamente
            if (self.apply_cassa or self.apply_withholding) and self.recurring_invoice_line_ids:
                return {
                    'warning': {
                        'title': 'Aggiornamento Automatico',
                        'message': 'Le righe fiscali verranno aggiornate automaticamente quando salvi o modifichi le righe prodotto.'
                    }
                }

    def _prepare_invoice_data(self):
        """Override per trasferire i dati fiscali all'invoice"""
        invoice_data = super()._prepare_invoice_data()

        # Trasferisci le impostazioni fiscali alla fattura
        invoice_data.update({
            'apply_cassa': self.apply_cassa,
            'cassa_percent': self.cassa_percent,
            'apply_withholding': self.apply_withholding,
            'withholding_percent': self.withholding_percent,
        })

        return invoice_data
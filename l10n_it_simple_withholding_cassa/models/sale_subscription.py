from odoo import models, fields, api
from odoo.tools import float_round


class SaleSubscription(models.Model):
    _inherit = "sale.subscription"

    # Campi per la Cassa Previdenziale
    apply_cassa = fields.Boolean(
        string="Applica Cassa Previdenziale",
        default=lambda self: self.env.company.enable_cassa_previdenziale,
        help="Applica la cassa previdenziale a questo abbonamento"
    )
    cassa_percent = fields.Float(
        string="Percentuale Cassa",
        default=4.0,
        help="Percentuale della cassa previdenziale"
    )
    cassa_amount = fields.Monetary(
        string="Importo Cassa",
        compute="_compute_fiscal_amounts",
        store=True,
        currency_field='currency_id'
    )

    # Campi per la Ritenuta d'Acconto
    apply_withholding = fields.Boolean(
        string="Applica Ritenuta d'Acconto",
        default=lambda self: self.env.company.enable_withholding_tax,
        help="Applica la ritenuta d'acconto a questo abbonamento"
    )
    withholding_percent = fields.Float(
        string="Percentuale Ritenuta",
        default=20.0,
        help="Percentuale della ritenuta d'acconto"
    )
    withholding_amount = fields.Monetary(
        string="Importo Ritenuta",
        compute="_compute_fiscal_amounts",
        store=True,
        currency_field='currency_id'
    )

    # Campi calcolati per i totali
    total_gross = fields.Monetary(
        string="Totale Lordo",
        compute="_compute_fiscal_amounts",
        store=True,
        currency_field='currency_id'
    )
    net_amount = fields.Monetary(
        string="Netto a Pagare",
        compute="_compute_fiscal_amounts",
        store=True,
        currency_field='currency_id'
    )

    @api.depends('recurring_total', 'apply_cassa', 'cassa_percent',
                 'apply_withholding', 'withholding_percent')
    def _compute_fiscal_amounts(self):
        """Calcola gli importi fiscali per l'abbonamento"""
        for subscription in self:
            # Base: totale ricorrente dell'abbonamento dalle righe normali
            normal_lines = subscription.recurring_invoice_line_ids.filtered(
                lambda l: not subscription._is_fiscal_line(l)
            )
            base_amount = sum(line.price_subtotal for line in normal_lines)

            # Calcolo Cassa Previdenziale
            cassa_amount = 0.0
            if subscription.apply_cassa:
                cassa_amount = float_round(
                    base_amount * subscription.cassa_percent / 100.0,
                    precision_rounding=subscription.currency_id.rounding
                )

            # Totale lordo (base + cassa)
            total_gross = base_amount + cassa_amount

            # Calcolo Ritenuta d'Acconto (applicata sul totale lordo)
            withholding_amount = 0.0
            if subscription.apply_withholding:
                withholding_amount = float_round(
                    total_gross * subscription.withholding_percent / 100.0,
                    precision_rounding=subscription.currency_id.rounding
                )

            # Netto a pagare (totale lordo - ritenuta)
            net_amount = float_round(
                total_gross - withholding_amount,
                precision_rounding=subscription.currency_id.rounding
            )

            # Assegnazione valori
            subscription.cassa_amount = cassa_amount
            subscription.withholding_amount = withholding_amount
            subscription.total_gross = total_gross
            subscription.net_amount = net_amount

    def _is_fiscal_line(self, line):
        """Identifica se una riga è una riga fiscale auto-generata"""
        if not line.name:
            return False
        return ('Cassa previdenziale' in line.name or
                'Ritenuta d\'acconto' in line.name)

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

    @api.model
    def create(self, vals):
        """Override create per applicare i default aziendali"""
        company = self.env.company

        # Applica default cassa se non specificato
        if 'cassa_percent' not in vals:
            vals['cassa_percent'] = getattr(company, 'default_cassa_percent', 4.0)

        # Applica default ritenuta se non specificato
        if 'withholding_percent' not in vals:
            vals['withholding_percent'] = getattr(company, 'default_withholding_percent', 20.0)

        return super().create(vals)
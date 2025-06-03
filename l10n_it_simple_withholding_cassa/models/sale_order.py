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

            # Ritenuta d'acconto (calcolata su imponibile + cassa)
            withholding_amount = 0.0
            if order.apply_withholding:
                withholding_base = amount_untaxed + cassa_amount  # Base include la cassa
                withholding_amount = float_round(withholding_base * order.withholding_percent / 100.0, precision_digits=2)

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

    def _get_or_create_auto_product(self):
        """Trova o crea un prodotto per le righe automatiche"""
        auto_product = self.env['product.product'].search([
            ('default_code', '=', 'AUTO_SERVICE')
        ], limit=1)
        
        if not auto_product:
            auto_product = self.env['product.product'].create({
                'name': 'Servizio Automatico - Calcoli Fiscali',
                'default_code': 'AUTO_SERVICE',
                'type': 'service',
                'list_price': 0.0,
                'sale_ok': True,
                'purchase_ok': False,
                'taxes_id': [(5, 0, 0)],  # Rimuove tutte le tasse di default
                'categ_id': self.env.ref('product.product_category_all').id,
            })
        
        return auto_product

    @api.onchange('order_line', 'apply_withholding', 'withholding_percent', 'apply_cassa', 'cassa_percent')
    def _onchange_withholding_cassa(self):
        if self.state != 'draft':
            return

        # Rimuovi righe automatiche esistenti
        original_lines = self.order_line.filtered(lambda l: not l.name.startswith('[AUTO]'))
        self.order_line = original_lines

        base_total = sum(original_lines.mapped('price_subtotal'))
        if not base_total:
            return

        # Ottieni il prodotto per le righe automatiche
        auto_product = self._get_or_create_auto_product()
        new_lines = original_lines

        # Aggiungi riga Cassa Previdenziale
        if self.apply_cassa:
            # Trova l'imposta IVA 22%
            tax_22 = self.env['account.tax'].search([
                ('type_tax_use', '=', 'sale'),
                ('amount', '=', 22),
                ('company_id', '=', self.company_id.id)
            ], limit=1)

            cassa_amount = base_total * self.cassa_percent / 100.0
            cassa_line = self.env['sale.order.line'].new({
                'order_id': self.id,
                'product_id': auto_product.id,  # IMPORTANTE: Prodotto obbligatorio
                'product_uom': auto_product.uom_id.id,  # IMPORTANTE: UoM obbligatorio
                'name': f"[AUTO] Cassa Previdenziale {self.cassa_percent:.1f}%",
                'price_unit': cassa_amount,
                'product_uom_qty': 1.0,
                'tax_id': [(6, 0, [tax_22.id])] if tax_22 else [(6, 0, [])],
                'sequence': 999,  # Metti alla fine
                'qty_delivered_method': 'manual',
            })
            new_lines += cassa_line

        # Aggiungi riga Ritenuta d'acconto
        if self.apply_withholding:
            ritenuta_amount = -base_total * self.withholding_percent / 100.0
            ritenuta_line = self.env['sale.order.line'].new({
                'order_id': self.id,
                'product_id': auto_product.id,  # IMPORTANTE: Prodotto obbligatorio
                'product_uom': auto_product.uom_id.id,  # IMPORTANTE: UoM obbligatorio
                'name': f"[AUTO] Ritenuta d'acconto {self.withholding_percent:.1f}%",
                'price_unit': ritenuta_amount,
                'product_uom_qty': 1.0,
                'tax_id': [(6, 0, [])],  # Nessuna IVA sulla ritenuta
                'sequence': 1000,  # Metti per ultimo
                'qty_delivered_method': 'manual',
            })
            new_lines += ritenuta_line

        self.order_line = new_lines

    @api.model_create_multi
    def create(self, vals_list):
        """Override create per gestire le righe automatiche al salvataggio - supporta batch creation"""
        orders = super().create(vals_list)
        
        # Processa ogni ordine creato
        for order in orders.filtered(lambda o: o.state == 'draft'):
            order._sync_auto_lines()
            
        return orders

    def write(self, vals):
        """Override write per gestire le righe automatiche al salvataggio"""
        result = super().write(vals)
        if any(key in vals for key in ['apply_withholding', 'withholding_percent', 'apply_cassa', 'cassa_percent', 'order_line']):
            for order in self.filtered(lambda o: o.state == 'draft'):
                order._sync_auto_lines()
        return result

    def _sync_auto_lines(self):
        """Sincronizza le righe automatiche (chiamata al salvataggio)"""
        if self.state != 'draft':
            return

        # Rimuovi righe automatiche esistenti
        auto_lines = self.order_line.filtered(lambda l: l.name and l.name.startswith('[AUTO]'))
        auto_lines.unlink()

        # Calcola base per righe normali
        normal_lines = self.order_line.filtered(lambda l: not (l.name and l.name.startswith('[AUTO]')))
        base_total = sum(normal_lines.mapped('price_subtotal'))
        
        if not base_total:
            return

        # Ottieni il prodotto per le righe automatiche
        auto_product = self._get_or_create_auto_product()

        # Crea nuove righe automatiche
        if self.apply_cassa:
            tax_22 = self.env['account.tax'].search([
                ('type_tax_use', '=', 'sale'),
                ('amount', '=', 22),
                ('company_id', '=', self.company_id.id)
            ], limit=1)

            cassa_amount = base_total * self.cassa_percent / 100.0
            self.env['sale.order.line'].create({
                'order_id': self.id,
                'product_id': auto_product.id,
                'product_uom': auto_product.uom_id.id,
                'name': f"[AUTO] Cassa Previdenziale {self.cassa_percent:.1f}%",
                'price_unit': cassa_amount,
                'product_uom_qty': 1.0,
                'tax_id': [(6, 0, [tax_22.id])] if tax_22 else [(6, 0, [])],
                'sequence': 999,
                'qty_delivered_method': 'manual',
            })

        if self.apply_withholding:
            ritenuta_amount = -base_total * self.withholding_percent / 100.0
            self.env['sale.order.line'].create({
                'order_id': self.id,
                'product_id': auto_product.id,
                'product_uom': auto_product.uom_id.id,
                'name': f"[AUTO] Ritenuta d'acconto {self.withholding_percent:.1f}%",
                'price_unit': ritenuta_amount,
                'product_uom_qty': 1.0,
                'tax_id': [(6, 0, [])],
                'sequence': 1000,
                'qty_delivered_method': 'manual',
            })
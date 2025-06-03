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
            # Separa le righe normali da quelle auto
            normal_lines = order.order_line.filtered(lambda l: not (l.name and l.name.startswith('[AUTO]')))
            auto_lines = order.order_line - normal_lines
            
            # Calcola imponibile base dalle righe normali
            amount_untaxed = sum(normal_lines.mapped('price_subtotal'))

            # Trova riga cassa e ritenuta
            cassa_line = auto_lines.filtered(lambda l: 'Cassa Previdenziale' in (l.name or ''))
            ritenuta_line = auto_lines.filtered(lambda l: 'Ritenuta' in (l.name or ''))

            # Prendi i valori dalle righe
            cassa_amount = sum(cassa_line.mapped('price_subtotal')) if cassa_line else 0.0
            withholding_amount = -sum(ritenuta_line.mapped('price_subtotal')) if ritenuta_line else 0.0

            # Calcola IVA totale
            amount_tax = sum(order.order_line.mapped('price_tax'))

            # Calcola totali
            total_gross = amount_untaxed + cassa_amount + amount_tax
            total_net = total_gross - withholding_amount

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

        # Calcola prima la cassa
        cassa_amount = 0
        if self.apply_cassa:
            tax_22 = self.env['account.tax'].search([
                ('type_tax_use', '=', 'sale'),
                ('amount', '=', 22),
                ('company_id', '=', self.company_id.id)
            ], limit=1)

            cassa_amount = base_total * self.cassa_percent / 100.0
            cassa_line = self.env['sale.order.line'].new({
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
            new_lines += cassa_line

        # Poi calcola la ritenuta includendo la cassa
        if self.apply_withholding:
            withholding_base = base_total + cassa_amount  # Include la cassa nella base
            ritenuta_amount = -withholding_base * self.withholding_percent / 100.0
            ritenuta_line = self.env['sale.order.line'].new({
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

        # Calcola prima la cassa
        cassa_amount = 0
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

        # Poi calcola la ritenuta includendo la cassa
        if self.apply_withholding:
            withholding_base = base_total + cassa_amount  # Include la cassa nella base
            ritenuta_amount = -withholding_base * self.withholding_percent / 100.0
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
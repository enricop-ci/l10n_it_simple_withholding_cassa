from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    enable_withholding_tax = fields.Boolean(string="Applica Ritenuta d'acconto di default")
    enable_cassa_previdenziale = fields.Boolean(string="Applica Cassa Previdenziale di default")

from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)

class ResCompany(models.Model):
    _inherit = "res.company"

    enable_withholding_tax = fields.Boolean(
        string="Abilita Ritenuta d'Acconto",
        default=False
    )

    enable_cassa_previdenziale = fields.Boolean(
        string="Abilita Cassa Previdenziale",
        default=False
    )

    cassa_account_id = fields.Many2one(
        'account.account',
        string="Conto Cassa Previdenziale"
    )

    withholding_account_id = fields.Many2one(
        'account.account',
        string="Conto Ritenuta d'Acconto"
    )

_logger.info("🔥 MODELLO RES.COMPANY CARICATO")
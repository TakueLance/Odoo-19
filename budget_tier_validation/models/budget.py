from odoo import models

class Budget(models.Model):
    _name = "budget.analytic"
    _inherit = ["budget.analytic", "tier.validation"]
    _state_from = ["draft"]
    _state_to = ["confirm", "done"]

    _tier_validation_manual_config = False
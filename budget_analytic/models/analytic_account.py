from odoo import models, _


class AnalyticAccount(models.Model):
    _inherit = "account.analytic.account"

    def _compute_display_name(self):
        for analytic in self:
            name = analytic.name
            if analytic.code:
                name = f"[{analytic.code}] {name}"
            if analytic.partner_id:
                name = _("%(name)s - %(partner)s") % {
                    "name": name,
                    "partner": analytic.partner_id.commercial_partner_id.name,
                }
            analytic.display_name = name


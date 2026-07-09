from odoo import models, api, _


class AnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    def _create_budget_report_lines(self):
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        self.env["budget.analytic.report"].create(
            {
                "account_id": self.account_id.id,
                "line_type": "actual",
                "user_id": self.create_uid.id or self.env.user.id,
                "company_id": self.company_id.id,
                "res_model": "account.analytic.line",
                "res_id": self.id,
                "currency_id": self.company_id.currency_id.id,
                "budget": 0,
                "committed": self.amount if self.amount < 0 else 0,
                "actual": abs(self.amount),  # Handle money going out as negative
                "date": self.date,
                "description": self.name,
                **{
                    plan._column_name(): self[plan._column_name()].id
                    for plan in other_plans[::-1]
                },
            }
        )

    @api.model
    def create(self, vals):
        # Create budget analytic report lines when creating analytic lines
        res = super().create(vals)
        res._create_budget_report_lines()
        return res

    def unlink(self, *args, **kwargs):
        # Remove budget analytic report lines when deleting analytic lines
        for line in self:
            self.env["budget.analytic.report"].search(
                [
                    ("res_model", "=", "account.analytic.line"),
                    ("res_id", "=", line.id),
                ]
            ).unlink()
        return super().unlink(*args, **kwargs)

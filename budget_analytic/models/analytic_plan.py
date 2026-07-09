from odoo import models

from odoo.tools import make_index_name, create_index


class AccountAnalyticPlan(models.Model):
    _inherit = "account.analytic.plan"

    def _find_budget_plan_column(self):
        return (
            self.env["ir.model.fields"]
            .sudo()
            .search(
                [
                    ("name", "in", [plan._strict_column_name() for plan in self]),
                    ("model", "=", "budget.analytic.line"),
                ]
            )
        )

    def _sync_plan_column(self, model=None):
        super()._sync_plan_column(model)
        # Create/delete a new field/column on budget analytic lines for this plan, and keep the name in sync.
        for plan in self:
            prev = plan._find_budget_plan_column()
            if plan.parent_id and prev:
                prev.unlink()
            elif prev:
                prev.field_description = plan.name
            elif not plan.parent_id:
                column = plan._strict_column_name()
                self.env["ir.model.fields"].with_context(
                    update_custom_fields=True
                ).sudo().create(
                    {
                        "name": column,
                        "field_description": plan.name,
                        "state": "manual",
                        "model": "budget.analytic.line",
                        "model_id": self.env["ir.model"]._get_id(
                            "budget.analytic.line"
                        ),
                        "ttype": "many2one",
                        "relation": "account.analytic.account",
                        "store": True,
                    }
                )
                tablename = self.env["budget.analytic.line"]._table
                indexname = make_index_name(tablename, column)
                create_index(
                    self.env.cr,
                    indexname,
                    tablename,
                    [column],
                    "btree",
                    f"{column} IS NOT NULL",
                )

                self.env["ir.model.fields"].with_context(
                    update_custom_fields=True
                ).sudo().create(
                    {
                        "name": column,
                        "field_description": plan.name,
                        "state": "manual",
                        "model": "budget.analytic.report",
                        "model_id": self.env["ir.model"]._get_id(
                            "budget.analytic.report"
                        ),
                        "ttype": "many2one",
                        "relation": "account.analytic.account",
                        "store": True,
                    }
                )
                tablename = self.env["budget.analytic.report"]._table
                indexname = make_index_name(tablename, column)
                create_index(
                    self.env.cr,
                    indexname,
                    tablename,
                    [column],
                    "btree",
                    f"{column} IS NOT NULL",
                )

    def unlink(self):
        # Remove the dynamic field created with the plan (see `_inverse_name`)
        self._find_budget_plan_column().unlink()
        return super().unlink()

from odoo import models, api, fields, _
from odoo.tools import frozendict, format_date, float_compare, Query

import logging

_logger = logging.getLogger(__name__)

class PurchaseOrderType(models.Model):
    _inherit = "purchase.order.type"

    is_contract = fields.Boolean()


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _create_budget_report_lines(self):
        # Create budget analytic report lines when approving purchase orders
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()

        currency_rate = self.env["res.currency"]._get_conversion_rate(
            from_currency=self.currency_id,
            to_currency=self.company_id.currency_id,
            company=self.company_id,
            date=self.date_approve,
        )

        for line in self.order_line:

            if line.analytic_distribution:

                amount = line.company_id.currency_id.round(
                    line.price_subtotal * currency_rate
                )
                balance = amount

                distribution_on_each_plan = {}
                account_field_values = {}
                budget_report_lines = []
                for account_ids, distribution in line.analytic_distribution.items():
                    distribution = float(distribution)
                    accounts = self.env["account.analytic.account"].browse(
                        map(int, account_ids.split(","))
                    )
                    for account in accounts:
                        distribution_plan = (
                            distribution_on_each_plan.get(account.root_plan_id, 0)
                            + distribution
                        )
                        if (
                            float_compare(distribution_plan, 100, precision_digits=2)
                            == 0
                        ):
                            balance = (
                                -amount
                                * (
                                    100
                                    - distribution_on_each_plan.get(
                                        account.root_plan_id, 0
                                    )
                                )
                                / 100.0
                            )
                        else:
                            balance = -amount * distribution / 100.0
                        distribution_on_each_plan[account.root_plan_id] = (
                            distribution_plan
                        )
                        account_field_values[account.plan_id._column_name()] = (
                            account.id
                        )
                    if not self.currency_id.is_zero(balance):
                        budget_report_lines.append(
                            {
                                "line_type": "committed",
                                "user_id": self.user_id.id,
                                "company_id": self.company_id.id,
                                "res_model": "purchase.order",
                                "res_id": self.id,
                                "currency_id": self.company_id.currency_id.id,
                                "budget": 0,
                                "committed": abs(
                                    balance
                                ),  # Committed should be positive
                                "actual": 0,  # No actuals at this point
                                "date": self.date_approve or fields.Date.today(),
                                "description": line.name,
                                **account_field_values,
                            }
                        )

                # Create budget analytic report lines in bulk
                if budget_report_lines:
                    self.env["budget.analytic.report"].create(budget_report_lines)

    def button_approve(self, force=False):
        self._create_budget_report_lines()
        return super().button_approve(force)

    def button_cancel(self):
        # Remove budget analytic report lines when cancelling purchase orders
        for order in self:
            self.env["budget.analytic.report"].search(
                [
                    ("res_model", "=", "purchase.order"),
                    ("res_id", "=", order.id),
                ]
            ).unlink()
        return super().button_cancel()

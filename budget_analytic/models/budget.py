from lxml.builder import E

from odoo import api, fields, models
from odoo.osv.expression import OR
from odoo.tools import SQL
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)



class Budget(models.Model):
    _name = "budget.analytic"
    _description = "Analytic Budget"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    active = fields.Boolean(default=True)

    name = fields.Char(string="Name", required=True)
    user_id = fields.Many2one("res.users", string="Responsible", required=True)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )
    budget_type = fields.Selection(
        [("revenue", "Revenue"), ("expense", "Expense"), ("both", "Both")],
        string="Budget Type",
        required=True,
    )
    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)

    line_ids = fields.One2many(
        "budget.analytic.line", "budget_id", string="Budget Lines", copy=True
    )

    project_account_id = fields.Many2one(
        "account.analytic.account", string="Project Account", required=True
    )  # Project

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirm", "Confirmed"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        string="State",
        default="draft",
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Currency",
        readonly=True,
        store=True,
    )

    def action_budget_draft(self):
        self.state = "draft"
        # Delete budget report lines for this budget
        self.env["budget.analytic.report"].search([
            ("res_model", "=", "budget.analytic"),
            ("res_id", "=", self.id)
        ]).unlink()

    def _create_budget_report_lines(self):
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        for line in self.line_ids:
            self.env["budget.analytic.report"].create({
                "account_id": line.account_id.id,
                "line_type": "budget",
                "user_id": self.user_id.id,
                "company_id": self.company_id.id,
                "date": line.budget_id.date_from,
                "description": line.budget_id.name,
                "currency_id": self.currency_id.id,
                "budget": line.budget_amount,
                "committed": 0,
                "actual": 0,
                "res_model": "budget.analytic",
                "res_id": self.id,
                **{
                    plan._column_name(): line[plan._column_name()].id
                    for plan in other_plans[::-1]
                },
            })

    def action_budget_confirm(self):
        self.state = "confirm"
        self._create_budget_report_lines()

    def action_budget_done(self):
        self.state = "done"

    def action_budget_cancel(self):
        self.state = "cancel"
        # Delete budget report lines for this budget
        self.env["budget.analytic.report"].search([
            ("res_model", "=", "budget.analytic"),
            ("res_id", "=", self.id)
        ]).unlink()

    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if self.env["account.analytic.plan"].check_access_rights(
            "read", raise_exception=False
        ):
            project_plan, other_plans = self.env[
                "account.analytic.plan"
            ]._get_all_plans()

            # Find main account nodes
            account_node = next(iter(arch.xpath('//field[@name="account_id"]')), None)
            account_filter_node = next(
                iter(arch.xpath('//filter[@name="account_id"]')), None
            )

            # Force domain on main account node as the fields_get doesn't do the trick
            if account_node is not None and view_type == "search":
                account_node.attrib["domain"] = (
                    f"[('plan_id', 'child_of', {project_plan.id})]"
                )

            # If there is a main node, append the ones for other plans
            if account_node is not None or account_filter_node is not None:
                for plan in other_plans[::-1]:
                    fname = plan._column_name()
                    if account_node is not None:
                        account_node.addnext(
                            E.field(
                                name=fname,
                                domain=f"[('plan_id', 'child_of', {plan.id})]",
                                readonly="budget_state != 'draft'",
                                optional="show",
                            )
                        )
                    if account_filter_node is not None:
                        account_filter_node.addnext(
                            E.filter(name=fname, context=f"{{'group_by': '{fname}'}}")
                        )
        return arch, view
    
    def action_budget_report(self):
        """Open the budget report for this budget."""
        return {
            "type": "ir.actions.act_window",
            "name": "Budget Report",
            "res_model": "budget.analytic.report",
            "view_mode": "list,form,pivot",
            "domain": [("account_id", "=", self.project_account_id.id)],
            "context": {},
        }
    
    def write(self, vals):
        if "active" in vals and not vals["active"]:
            # If the budget is being deactivated, we need to delete the budget report lines
            self.env["budget.analytic.report"].search([
                ("res_model", "=", "budget.analytic"),
                ("res_id", "=", self.id)
            ]).unlink()
        return super().write(vals)


class BudgetLine(models.Model):
    _name = "budget.analytic.line"
    _description = "Analytic Budget Line"

    budget_id = fields.Many2one(
        "budget.analytic", string="Budget", required=True, ondelete="cascade"
    )

    budget_type = fields.Selection(
        [("revenue", "Revenue"), ("expense", "Expense"), ("both", "Both")],
        related="budget_id.budget_type",
        string="Budget Type",
        readonly=True,
    )

    # Magic column that represents all the plans at the same time, except for the compute
    # where it is context dependent, and needs the id of the desired plan.
    # Used as a syntactic sugar for search views, and magic field for one2many relation
    auto_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Analytic Account",
        compute="_compute_auto_account",
        inverse="_inverse_auto_account",
        search="_search_auto_account",
    )

    account_id = fields.Many2one(
        "account.analytic.account",
        string="Account",
        compute="_compute_account_id",
        store=True,
        readonly=False,
    )

    # committed_amount = fields.Monetary(string="Committed Amount", required=True)

    currency_id = fields.Many2one(
        "res.currency",
        related="budget_id.company_id.currency_id",
        string="Currency",
        readonly=True,
    )

    date_from = fields.Date(related="budget_id.date_from", string="Start Date")
    date_to = fields.Date(related="budget_id.date_to", string="End Date")

    budget_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirm", "Confirmed"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        related="budget_id.state",
        string="State",
        readonly=True,
    )

    budget_amount = fields.Monetary(string="Amount", required=True)

    committed_amount = fields.Monetary(
        string="Committed Amount", compute="_compute_committed_amount"
    )
    committed_percentage = fields.Float(
        string="Committed Percentage", compute="_compute_committed_percentage"
    )

    achieved_amount = fields.Monetary(
        string="Achieved Amount", compute="_compute_achieved_amount"
    )
    achieved_percentage = fields.Float(
        string="Achieved Percentage", compute="_compute_achieved_percentage"
    )

    remaining_amount = fields.Monetary(
        string="Remaining Amount", compute="_compute_remaining_amount"
    )

    remaining_percentage = fields.Float(
        string="Remaining Percentage", compute="_compute_remaining_percentage"
    )

    theoretical_amount = fields.Monetary(
        string="Theoretical Amount", compute="_compute_theoretical_amount"
    )
    theoretical_percentage = fields.Float(
        string="Theoretical Percentage", compute="_compute_theoretical_percentage"
    )

    forecast_amount = fields.Monetary(string="Forecast Amount")

    def action_budget_report(self):
        """Open the budget report for this budget."""
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        domain = [("account_id", "=", self.account_id.id)]
        
        for plan in other_plans[::-1]:
            domain.append((plan._column_name(), "=", self[plan._column_name()].id))
        
        return {
            "type": "ir.actions.act_window",
            "name": "Budget Report",
            "res_model": "budget.analytic.report",
            "view_mode": "list,form,pivot",
            "domain": domain,
            "context": {},
        }

    @api.depends("budget_id.project_account_id")
    def _compute_account_id(self):
        for line in self:
            if line.budget_id.project_account_id:
                line.account_id = line.budget_id.project_account_id
            else:
                line.account_id = False

    def _query_analytic_accounts(self, table=False):
        return SQL(
            r"""regexp_split_to_array(jsonb_path_query_array(%s.analytic_distribution, '$.keyvalue()."key"')::text, '\D+')""",
            SQL(table or self._table),
        )

    def _get_committed_amount(self):
        self.ensure_one()
        return 0

    @api.depends("budget_id.date_from", "budget_id.date_to", "achieved_amount")
    def _compute_committed_amount(self):
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        for line in self:
            line.committed_amount = 0         

            domain = []
            if line[project_plan._column_name()].id:
                domain.append(
                    (project_plan._column_name(), "=", line[project_plan._column_name()].id)
                )
            for plan in other_plans[::-1]:
                if line[plan._column_name()].id:
                    domain.append((plan._column_name(), "=", line[plan._column_name()].id))

            reports = self.env['budget.analytic.report'].read_group(domain, ['committed'], [])
            if reports:
                line.committed_amount = reports[0].get('committed', 0)


    @api.depends("budget_amount", "committed_amount")
    def _compute_committed_percentage(self):
        for line in self:
            if line.budget_amount:
                line.committed_percentage = (
                    line.committed_amount / line.budget_amount * 100
                )
            else:
                line.committed_percentage = 0

    def _compute_achieved_amount(self):
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        for line in self:
            line.achieved_amount = 0
            domain = [
                ("account_id", "=", line.account_id.id),
                (
                    project_plan._column_name(),
                    "=",
                    line[project_plan._column_name()].id,
                ),
            ]
            for plan in other_plans[::-1]:
                domain.append((plan._column_name(), "=", line[plan._column_name()].id))

            # _logger.info(domain)

            if line.budget_id.budget_type == "revenue":
                domain.append(("amount", ">", 0))
            elif line.budget_id.budget_type == "expense":
                domain.append(("amount", "<", 0))

            analytic_lines = self.env["account.analytic.line"].search(domain)

            line.achieved_amount = abs(sum(analytic_lines.mapped("amount")))

            # if line.budget_id.budget_type == "expense":
            #     line.achieved_amount = -line.achieved_amount

    def _compute_achieved_percentage(self):
        for line in self:
            if line.budget_amount:
                line.achieved_percentage = (
                    line.achieved_amount / line.budget_amount * 100
                )
            else:
                line.achieved_percentage = 0

    def _compute_theoretical_amount(self):
        today = fields.Datetime.now()
        for line in self:
            # Used for the report

            if line.date_from and line.date_to:
                line_timedelta = line.date_to - line.date_from
                elapsed_timedelta = today.date() - line.date_from

                if elapsed_timedelta.days < 0:
                    # If the budget line has not started yet, theoretical
                    # amount should be zero
                    theo_amt = 0.00
                elif line_timedelta.days > 0 and today.date() < line.date_to:
                    # If today is between the budget line date_from and
                    # date_to
                    theo_amt = (
                        elapsed_timedelta.total_seconds()
                        / line_timedelta.total_seconds()
                    ) * line.budget_amount
                else:
                    theo_amt = line.budget_amount
            else:
                theo_amt = 0.00
            line.theoretical_amount = theo_amt

    def _compute_theoretical_percentage(self):
        for line in self:
            if line.budget_amount:
                line.theoretical_percentage = (
                    line.theoretical_amount / line.budget_amount * 100
                )
            else:
                line.theoretical_percentage = 0

    @api.depends("budget_amount", "achieved_amount")
    def _compute_remaining_amount(self):
        for line in self:
            line.remaining_amount = line.budget_amount - line.achieved_amount

    def _compute_remaining_percentage(self):
        for line in self:
            line.remaining_percentage = 100.0 - line.achieved_percentage

    @api.depends_context("analytic_plan_id")
    def _compute_auto_account(self):
        plan = self.env["account.analytic.plan"].browse(
            self.env.context.get("analytic_plan_id")
        )
        for line in self:
            line.auto_account_id = bool(plan) and line[plan._column_name()]

    def _inverse_auto_account(self):
        for line in self:
            line[line.auto_account_id.plan_id._column_name()] = line.auto_account_id

    def _search_auto_account(self, operator, value):
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        return OR(
            [
                [(plan._column_name(), operator, value)]
                for plan in project_plan + other_plans
            ]
        )

    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if self.env["account.analytic.plan"].check_access_rights(
            "read", raise_exception=False
        ):
            project_plan, other_plans = self.env[
                "account.analytic.plan"
            ]._get_all_plans()

            # Find main account nodes
            account_node = next(iter(arch.xpath('//field[@name="account_id"]')), None)
            account_filter_node = next(
                iter(arch.xpath('//filter[@name="account_id"]')), None
            )

            # Force domain on main account node as the fields_get doesn't do the trick
            if account_node is not None and view_type == "search":
                account_node.attrib["domain"] = (
                    f"[('plan_id', 'child_of', {project_plan.id})]"
                )

            # If there is a main node, append the ones for other plans
            if account_node is not None or account_filter_node is not None:
                for plan in other_plans[::-1]:
                    fname = plan._column_name()
                    if account_node is not None:
                        account_node.addnext(
                            E.field(
                                name=fname,
                                domain=f"[('plan_id', 'child_of', {plan.id})]",
                                optional="show",
                            )
                        )
                    if account_filter_node is not None:
                        account_filter_node.addnext(
                            E.filter(name=fname, context=f"{{'group_by': '{fname}'}}")
                        )
        return arch, view

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        fields = super().fields_get(allfields, attributes)
        if self.env["account.analytic.plan"].check_access_rights(
            "read", raise_exception=False
        ):
            project_plan, other_plans = self.env[
                "account.analytic.plan"
            ]._get_all_plans()
            for plan in project_plan + other_plans:
                fname = plan._column_name()
                if fname in fields:
                    fields[fname]["string"] = plan.name
                    fields[fname]["domain"] = f"[('plan_id', 'child_of', {plan.id})]"
        return fields


class BudgetReport(models.Model):
    _name = "budget.analytic.report"
    _description = "Analytic Budget Report"
    
    # Magic column that represents all the plans at the same time, except for the compute
    # where it is context dependent, and needs the id of the desired plan.
    # Used as a syntactic sugar for search views, and magic field for one2many relation
    auto_account_id = fields.Many2one(
        comodel_name="account.analytic.account",
        string="Analytic Account",
        compute="_compute_auto_account",
        inverse="_inverse_auto_account",
        search="_search_auto_account",
    )

    account_id = fields.Many2one(
        "account.analytic.account",
        string="Account"
    )
    
    res_model = fields.Char(
        string="Resource Model",
        default="budget.analytic.line",
    )

    res_id = fields.Integer(
        string="Resource ID",
    )

    category = fields.Selection(
        [('procurement','Procurement'), ('contract', 'Contract'), ('payroll', 'Payroll'), ('revenue', 'Revenue')],
        string="Category",
        compute="_compute_category",
        store=True,
    )

    line_type = fields.Selection(
        [("budget", "Budget"), ("committed", "Committed"), ("actual", "Actual")],
        string="Line Type",
        required=True,
    )

    user_id = fields.Many2one(
        "res.users", string="Responsible", required=True
    )
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )

    date = fields.Date(string="Date", required=True)

    description = fields.Char(string="Description")

    currency_id = fields.Many2one(
        "res.currency"
    )

    budget = fields.Monetary(
        string="Budget",
    )

    committed = fields.Monetary(
        string="Committed",
    )

    actual = fields.Monetary(
        string="Actual",
    )

    @api.depends('res_model', 'res_id')
    def _compute_category(self):
        for line in self:
            if line.res_model == "account.analytic.line":
                doc = self.env[line.res_model].browse(line.res_id)
                if doc.amount < 0:
                    is_contract = doc.move_line_id.purchase_order_id.order_type.is_contract
                    if is_contract:
                        line.category = "contract"
                    else:
                        line.category = "procurement"
                else:
                    line.category = "revenue"
            elif line.res_model == "purchase.order":
                doc = self.env[line.res_model].browse(line.res_id)
                if doc.order_type and doc.order_type.is_contract:
                    line.category = "contract"
                else:
                    line.category = "procurement"
            elif line.res_model == "hr.payslip":
                line.category = "payroll"
            else:
                line.category = False

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        fields = super().fields_get(allfields, attributes)
        if self.env["account.analytic.plan"].check_access_rights(
            "read", raise_exception=False
        ):
            project_plan, other_plans = self.env[
                "account.analytic.plan"
            ]._get_all_plans()
            for plan in project_plan + other_plans:
                fname = plan._column_name()
                if fname in fields:
                    fields[fname]["string"] = plan.name
                    fields[fname]["domain"] = f"[('plan_id', 'child_of', {plan.id})]"
        return fields
    
    @api.depends_context("analytic_plan_id")
    def _compute_auto_account(self):
        plan = self.env["account.analytic.plan"].browse(
            self.env.context.get("analytic_plan_id")
        )
        for line in self:
            line.auto_account_id = bool(plan) and line[plan._column_name()]

    def _inverse_auto_account(self):
        for line in self:
            line[line.auto_account_id.plan_id._column_name()] = line.auto_account_id

    def _search_auto_account(self, operator, value):
        project_plan, other_plans = self.env["account.analytic.plan"]._get_all_plans()
        return OR(
            [
                [(plan._column_name(), operator, value)]
                for plan in project_plan + other_plans
            ]
        )

    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if self.env["account.analytic.plan"].check_access_rights(
            "read", raise_exception=False
        ):
            project_plan, other_plans = self.env[
                "account.analytic.plan"
            ]._get_all_plans()

            # Find main account nodes
            account_node = next(iter(arch.xpath('//field[@name="account_id"]')), None)
            account_filter_node = next(
                iter(arch.xpath('//filter[@name="account_id"]')), None
            )

            # Force domain on main account node as the fields_get doesn't do the trick
            if account_node is not None and view_type == "search":
                account_node.attrib["domain"] = (
                    f"[('plan_id', 'child_of', {project_plan.id})]"
                )

            # If there is a main node, append the ones for other plans
            if account_node is not None or account_filter_node is not None:
                for plan in other_plans[::-1]:
                    fname = plan._column_name()
                    if account_node is not None:
                        account_node.addnext(
                            E.field(
                                name=fname,
                                domain=f"[('plan_id', 'child_of', {plan.id})]",
                                optional="show",
                            )
                        )
                    if account_filter_node is not None:
                        account_filter_node.addnext(
                            E.filter(name=fname, context=f"{{'group_by': '{fname}'}}")
                        )
        return arch, view
    
    def action_open_resource(self):
        """Open the resource (analytic line) associated with this report line."""
        return {
            "type": "ir.actions.act_window",
            "name": "Analytic Line",
            "res_model": self.res_model,
            "view_mode": "form",
            "res_id": self.res_id,
            "target": "current",
        }
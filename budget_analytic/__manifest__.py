{
    "name": "Analytical Budgets",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "Aviseo Services (Pty) Ltd",
    "website": "https://github.com/avierp/budget-analytic",
    "depends": ["account", "account_usability", "purchase", "account_analytic_parent", "purchase_order_type"],
    "excludes": ["account_budget"],
    "data": [
        "security/ir.model.access.csv",
        "views/budget.xml",
    ],
}

{
    "name": "FastAPI Connector Webhooks",
    "version": "17.0.1.0.0",
    "summary": "Post signed webhook events for partners and confirmed sale orders to the connector",
    "description": """
Sends HMAC-SHA256 signed JSON events (partner.created, partner.updated, sale_order.confirmed) to
the FastAPI connector's POST /webhooks/odoo endpoint. See README.md for installation.
""",
    "author": "conector-odoo",
    "category": "Technical",
    "license": "LGPL-3",
    "depends": ["base", "sale", "base_automation"],
    "data": [
        "data/ir_config_parameter.xml",
        "data/base_automation.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}

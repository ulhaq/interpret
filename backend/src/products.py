"""The modules installed in this deployment: optional foundation modules
(billing, marketing), then the product.

The only file in the assembly layer that names a product package. To replace
or add a product, change `PRODUCTS`; to run without plans and Stripe, drop
`BILLING`, and without the marketing site's endpoints, `MARKETING` (each with
its migration). `bootstrap`, the API, the worker and Alembic all
read `MODULES`. (The import-linter contracts in `pyproject.toml` name the
product packages too; see `docs/adding-a-domain-module.md`.)
"""

from src.billing.module import BILLING
from src.foundation.core.module import Module
from src.interpret.product import INTERPRET
from src.marketing.module import MARKETING

PRODUCTS: list[Module] = [INTERPRET]

MODULES: list[Module] = [BILLING, MARKETING, *PRODUCTS]

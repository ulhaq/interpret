"""The interpret product's manifest: everything it plugs into the foundation."""

from src.foundation.core.module import Module
from src.foundation.core.routing import RouterMount
from src.interpret import models
from src.interpret.enums import (
    INTERPRET_DEFAULT_ROLE_DESCRIPTIONS,
    INTERPRET_DEFAULT_ROLE_PERMISSIONS,
    INTERPRET_PERMISSION_DESCRIPTIONS,
    InterpretAuditAction,
    InterpretPermission,
)
from src.interpret.gdpr import export_user_data
from src.interpret.routers import conversations

INTERPRET = Module(
    name="interpret",
    models=models,
    permissions=list(InterpretPermission),
    permission_descriptions={**INTERPRET_PERMISSION_DESCRIPTIONS},
    audit_actions=list(InterpretAuditAction),
    default_role_permissions=INTERPRET_DEFAULT_ROLE_PERMISSIONS,
    default_role_descriptions=INTERPRET_DEFAULT_ROLE_DESCRIPTIONS,
    routers=[RouterMount(router=conversations.router, tags=["Interpret"])],
    user_data_export=export_user_data,
)

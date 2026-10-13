"""Composition root - wires the installed product modules into the generic
SaaS core.

The products are listed in `src.products`; each declares what it contributes
in a `Module` manifest. The core never imports domain code: it emits
hooks and consumes the composed permission/role sets defined here.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum

from src.foundation import enums as core_enums
from src.foundation.core import composition
from src.foundation.core.composition import Composition, RoleSpec
from src.foundation.core.entitlements import UNLIMITED
from src.foundation.core.hooks import Handler, HookEvent
from src.foundation.core.module import Module, NotificationCategory, NotificationRule
from src.foundation.services.notification import RuleHandler
from src.products import MODULES

ALL_PERMISSIONS: list[StrEnum] = [
    *core_enums.Permission,
    *(*product.permissions for product in MODULES),
]

PERMISSION_DESCRIPTIONS: dict[StrEnum, str] = {
    **core_enums.PERMISSION_DESCRIPTIONS,
    **{**product.permission_descriptions for product in MODULES},
}


# Every action the installed modules record, as one enum named like the
# foundation's: the audit log filters by it (`audit_log.build_router`).
AUDIT_ACTION: type[StrEnum] = StrEnum(
    "AuditAction",
    [
        (action.name, action.value)
        for action in [
            *core_enums.AuditAction,
            *(*product.audit_actions for product in MODULES),
        ]
    ],
)


def compose_default_roles(
    roles: Sequence[RoleSpec],
    products: Sequence[Module],
) -> list[RoleSpec]:
    """Add each product's grants to the foundation default roles, and apply its
    description overrides (a later product wins)."""
    composed = []
    for name, base_description, permissions in roles:
        description = base_description
        grants = [*permissions]
        for product in products:
            description = product.default_role_descriptions.get(name, description)
            grants.extend(product.default_role_permissions.get(name, []))
        composed.append((name, description, grants))
    return composed


def compose_hook_events(products: Sequence[Module]) -> dict[str, StrEnum]:
    """The foundation's hook events plus each module's, by value. Values must be
    unique: a `StrEnum` member compares equal to its value, so two events
    sharing one would share their handlers."""
    events: dict[str, StrEnum] = {event.value: event for event in HookEvent}
    for product in products:
        for event in product.hook_events:
            if event.value in events:
                raise ValueError(f"Hook event {event.value!r} is declared twice")
            events[event.value] = event
    return events


def _check_notification_rule(
    product: Module,
    rule: NotificationRule,
    hook_events: Mapping[str, StrEnum],
    categories: Mapping[str, NotificationCategory],
) -> None:
    if hook_events.get(rule.event.value) is not rule.event:
        raise ValueError(
            f"Module {product.name!r} notifies on hook event {rule.event!r}, "
            "which no installed module declares",
        )
    if rule.category not in categories:
        raise ValueError(
            f"Module {product.name!r} notifies under category {rule.category!r}, "
            "which no installed module declares",
        )


def compose(products: Sequence[Module]) -> Composition:
    """Merge what ``products`` add to the foundation (in list order) into one
    read-only `Composition`."""
    providers = [p.entitlements for p in products if p.entitlements is not None]
    if len(providers) > 1:
        raise ValueError("More than one installed module provides entitlements")
    hook_events = compose_hook_events(products)
    hook_handlers: dict[StrEnum, list[Handler]] = {}
    email_subjects: dict[str, dict[str, str]] = {}
    notification_categories: dict[str, NotificationCategory] = {}
    for product in products:
        for event, handlers in product.hooks.items():
            if hook_events.get(event.value) is not event:
                raise ValueError(
                    f"Module {product.name!r} handles hook event {event!r}, "
                    "which no installed module declares",
                )
            hook_handlers.setdefault(event, []).extend(handlers)
        for locale, subjects in product.email_subjects.items():
            email_subjects.setdefault(locale, {}).update(subjects)
        for category in product.notification_categories:
            if category.key in notification_categories:
                raise ValueError(
                    f"Notification category {category.key!r} is declared twice",
                )
            notification_categories[category.key] = category
    # After every module's categories are known: a rule may use another's.
    for product in products:
        for rule in product.notification_rules:
            _check_notification_rule(
                product,
                rule,
                hook_events,
                notification_categories,
            )
            hook_handlers.setdefault(rule.event, []).append(RuleHandler(rule))
    return Composition(
        default_roles=compose_default_roles(core_enums.DEFAULT_ROLES, products),
        hooks=frozendict(
            {event: tuple(handlers) for event, handlers in hook_handlers.items()},
        ),
        email_subjects=frozendict(
            {
                locale: frozendict(subjects)
                for locale, subjects in email_subjects.items()
            },
        ),
        template_directories=[
            product.template_directory
            for product in products
            if product.template_directory
        ],
        notification_categories=frozendict(notification_categories),
        entitlements=providers[0] if providers else UNLIMITED,
        user_data_exporters=frozendict(
            {
                product.name: product.user_data_export
                for product in products
                if product.user_data_export is not None
            },
        ),
        email_campaigns=frozendict(
            {**product.email_campaigns for product in products},
        ),
        email_link_keys=frozenset(*product.email_link_keys for product in products),
    )


def bootstrap() -> None:
    """Install the installed products' composition. Idempotent; called at
    process startup by both the API (`src.main`) and the worker (`worker.py`)."""
    composition.install(compose(MODULES))

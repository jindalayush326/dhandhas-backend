"""Role-Based Access Control — one table maps roles to permissions.

Roles are hierarchical in privilege but permissions are explicit per role
(no implicit inheritance) so it's always obvious, by reading this file,
exactly what a role can do. `owner` and `admin` get every permission by
convention (see ALL_PERMISSIONS) instead of listing them out.
"""

from __future__ import annotations

ALL_PERMISSIONS = {
    "company:manage",       # edit company, delete company, manage billing
    "members:invite",       # invite/revoke employees
    "members:manage",       # change roles/permissions of existing members
    "masters:write",        # ledgers, items, godowns, voucher types
    "masters:read",
    "vouchers:write",
    "vouchers:read",
    "reports:read",
    "gst:use",
    "sync:use",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": set(ALL_PERMISSIONS),
    "admin": set(ALL_PERMISSIONS) - {"company:manage"},
    "accountant": {
        "masters:write", "masters:read", "vouchers:write", "vouchers:read",
        "reports:read", "gst:use", "sync:use",
    },
    "employee": {
        "masters:read", "vouchers:write", "vouchers:read", "sync:use",
    },
    "viewer": {"masters:read", "vouchers:read", "reports:read"},
}


def permissions_for(role: str, extra: list[str] | None = None) -> set[str]:
    base = set(ROLE_PERMISSIONS.get(role, set()))
    if extra:
        base |= set(extra) & ALL_PERMISSIONS
    return base


def has_permission(role: str, extra: list[str] | None, permission: str) -> bool:
    return permission in permissions_for(role, extra)

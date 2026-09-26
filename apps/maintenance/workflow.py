"""Valid status transitions + who may perform them. Single source of truth for views and tests."""

TRANSITIONS = {
    "open": ["acknowledged"],
    "acknowledged": ["in_progress", "on_hold", "open"],
    "in_progress": ["on_hold", "resolved"],
    "on_hold": ["in_progress", "acknowledged"],
    "resolved": ["closed", "reopened"],
    "reopened": ["acknowledged", "in_progress"],
    "closed": ["reopened"],
}

MANAGERS = ("admin", "manager")


def is_manager(user):
    return user.is_superuser or user.role in MANAGERS


def is_requester(user, sr):
    return sr.requested_by_id and user.pk == sr.requested_by_id


def is_assignee(user, sr):
    return sr.assigned_to_id and user.pk == sr.assigned_to_id


def allowed_targets(status):
    return TRANSITIONS.get(status, [])


def can_transition(user, sr, target):
    """Server-side gate. Returns (ok, reason)."""
    if target not in allowed_targets(sr.status):
        return False, f"Cannot move from {sr.get_status_display()} to {target}."
    if not user.is_authenticated or not user.is_active:
        return False, "Authentication required."
    frm, to = sr.status, target
    if to == "acknowledged" and frm in ("open", "reopened", "on_hold"):
        return (True, "") if is_manager(user) else (False, "Only managers can assign technicians.")
    if to == "open":  # unassign back to pool
        return (True, "") if is_manager(user) else (False, "Only managers can unassign.")
    if to in ("in_progress", "on_hold"):
        if is_assignee(user, sr) or is_manager(user):
            return True, ""
        return False, "Only the assigned technician or a manager can do this."
    if to == "resolved":
        if is_assignee(user, sr) or is_manager(user):
            return True, ""
        return False, "Only the assigned technician or a manager can resolve."
    if to == "closed":
        if is_requester(user, sr) or is_manager(user):
            return True, ""
        return False, "Only the requester or a manager can close."
    if to == "reopened":
        if is_requester(user, sr) or is_manager(user):
            return True, ""
        return False, "Only the requester or a manager can reopen."
    return False, "Not permitted."

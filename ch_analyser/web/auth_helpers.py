"""Auth helper functions for page-level access control."""

from nicegui import app, ui


def require_auth() -> bool:
    """Check if user is authenticated, redirect to /login if not.

    Call at the top of every @ui.page that requires authentication.
    Returns True if authenticated, False otherwise.
    """
    if not app.storage.user.get('authenticated'):
        ui.navigate.to('/login')
        return False
    return True


def is_admin() -> bool:
    """Return True if the current user has admin role."""
    return app.storage.user.get('role') == 'admin'

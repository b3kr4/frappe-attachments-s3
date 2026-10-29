"""Cloud-safe website route for private S3 downloads."""

import frappe

from frappe_s3_attachment.controller import get_file_for_id, get_file_redirect_url


def get_context(context):
    """Authorise the file and resolve its current storage on every request."""
    context.no_cache = 1
    file_id = frappe.form_dict.file_id
    frappe.flags.redirect_location = get_file_redirect_url(get_file_for_id(file_id))
    raise frappe.Redirect(http_status_code=302)

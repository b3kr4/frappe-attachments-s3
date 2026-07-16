"""Cloud-safe website route for private S3 downloads."""

import frappe

from frappe_s3_attachment.controller import get_file_for_id, get_signed_url


def get_context(context):
    """Authorise the file request and redirect to a short-lived signed URL."""
    context.no_cache = 1
    file_id = frappe.form_dict.file_id
    frappe.redirect(get_signed_url(get_file_for_id(file_id)))

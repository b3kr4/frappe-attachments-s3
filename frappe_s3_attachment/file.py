"""Frappe ``File`` integration for files stored by this app in S3."""

from frappe.core.doctype.file.file import File


class S3File(File):
    """Handle the app's authenticated S3 route as remote file storage.

    Frappe reuses ``file_url`` for files with identical content.  Without this
    override, a reused ``/s3/...`` URL is checked as a local path while the new
    File document is being inserted and Frappe rejects it as unsafe.
    """

    @property
    def is_s3_file(self):
        return bool(self.file_url and self.file_url.startswith('/s3/'))

    @property
    def is_remote_file(self):
        return self.is_s3_file or super().is_remote_file

    @property
    def unique_url(self):
        """Give extracted editor images a stable URL before the upload commits.

        Keep file_url local for other File hooks. Frappe embeds unique_url in
        Text Editor HTML immediately after saving the new File document.
        """
        if self.flags.s3_upload_pending:
            from frappe_s3_attachment.controller import get_download_url

            return get_download_url(self.name, self.file_name)
        return super().unique_url

    def get_content(self):
        """Support Frappe's private-image PDF embedding without an HTTP fetch.

        Like File.get_content, this is an internal storage operation. Callers
        exposing contents must authorise the File first (as Frappe's PDF code
        and this app's download route do).
        """
        if not self.is_s3_file:
            return super().get_content()

        import frappe
        from frappe_s3_attachment.controller import S3Operations

        if not self.content_hash:
            frappe.throw(frappe._('S3 file has no content hash.'))
        storage = S3Operations()
        key = storage.key_generator(self.content_hash, '', '', '')
        body = storage.read_file_from_s3(key)['Body']
        try:
            return body.read()
        finally:
            body.close()

    def validate(self):
        """Keep the S3 object key when Frappe validates a remote route.

        Frappe intentionally clears ``content_hash`` for remote URLs because it
        cannot hash their contents.  Our ``/s3/`` URL is only an authenticated
        indirection, though: the hash is the key of the S3 object and must
        survive ordinary File updates such as changing its privacy setting.
        """
        content_hash = self.content_hash if self.is_s3_file else None
        super().validate()
        if self.is_s3_file:
            self.content_hash = content_hash

    def get_full_path(self):
        if self.is_s3_file:
            return self.file_url
        return super().get_full_path()

    def exists_on_disk(self):
        """An S3-backed duplicate is available although it is not local."""
        if self.is_s3_file:
            return True
        return super().exists_on_disk()

    def validate_file_on_disk(self):
        """S3 download routes have no corresponding local filesystem file."""
        if self.is_s3_file:
            return
        return super().validate_file_on_disk()

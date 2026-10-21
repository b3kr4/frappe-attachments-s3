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

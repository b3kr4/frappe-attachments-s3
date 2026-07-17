from __future__ import unicode_literals

import os
import re
from urllib.parse import quote

import boto3

from botocore.client import Config
from botocore.exceptions import ClientError

import frappe


import magic


class S3Operations(object):

    def __init__(self):
        """
        Function to initialise the aws settings from frappe S3 File attachment
        doctype.
        """
        self.s3_settings_doc = frappe.get_doc(
            'S3 File Attachment',
            'S3 File Attachment',
        )
        self.provider = self.s3_settings_doc.storage_provider or 'AWS S3'
        self.endpoint_url = self.s3_settings_doc.endpoint_url

        # Hetzner Object Storage exposes an S3-compatible API, but unlike AWS
        # it requires its regional endpoint and virtual-host bucket addressing.
        if self.provider == 'Hetzner Object Storage' and not self.endpoint_url:
            self.endpoint_url = 'https://{}.your-objectstorage.com'.format(
                self.s3_settings_doc.region_name
            )

        config_options = {'signature_version': 's3v4'}
        if self.provider == 'Hetzner Object Storage':
            config_options['s3'] = {
                'payload_signing_enabled': False,
                'addressing_style': 'virtual',
            }

        client_options = {
            'region_name': self.s3_settings_doc.region_name,
            'config': Config(**config_options),
        }
        if self.endpoint_url:
            client_options['endpoint_url'] = self.endpoint_url
        if self.s3_settings_doc.aws_key and self.s3_settings_doc.aws_secret:
            client_options['aws_access_key_id'] = self.s3_settings_doc.aws_key
            client_options['aws_secret_access_key'] = self.s3_settings_doc.aws_secret

        self.S3_CLIENT = boto3.client('s3', **client_options)
        self.BUCKET = self.s3_settings_doc.bucket_name
        self.folder_name = self.s3_settings_doc.folder_name

    def key_generator(self, content_hash, file_name, parent_doctype, parent_name):
        """Generate a deterministic, content-addressed object key.

        Old installations stored the complete S3 key in ``content_hash``. Keep
        those records readable during the transition to content-addressed keys.
        """
        if '/' in content_hash:
            return content_hash
        parts = [part for part in (self.folder_name, 'sha256', content_hash) if part]
        return '/'.join(parts)

    def object_exists(self, key):
        try:
            self.S3_CLIENT.head_object(Bucket=self.BUCKET, Key=key)
            return True
        except ClientError as error:
            error_code = error.response.get('Error', {}).get('Code')
            if error_code in ('404', 'NoSuchKey', 'NotFound'):
                return False
            raise

    def upload_files_to_s3_with_key(
            self, file_path, content_hash, file_name, is_private,
            parent_doctype, parent_name
    ):
        """
        Uploads a new file to S3.
        Strips the file extension to set the content_type in metadata.
        """
        mime_type = magic.from_file(file_path, mime=True)
        key = self.key_generator(
            content_hash, file_name, parent_doctype, parent_name
        )
        content_type = mime_type
        try:
            # All objects remain private. Frappe authorises access and returns
            # a short-lived signed download URL instead of exposing the bucket.
            if not self.object_exists(key):
                self.S3_CLIENT.upload_file(
                    file_path, self.BUCKET, key,
                    ExtraArgs={
                        "ContentType": content_type
                    }
                )

        except boto3.exceptions.S3UploadFailedError:
            frappe.throw(frappe._("File Upload Failed. Please try again."))
        return key

    def delete_from_s3(self, content_hash):
        """ Delete file from s3"""
        if self.s3_settings_doc.delete_file_from_cloud:
            try:
                self.S3_CLIENT.delete_object(
                    Bucket=self.s3_settings_doc.bucket_name,
                    Key=self.key_generator(content_hash, '', '', '')
                )
            except ClientError:
                frappe.throw(frappe._("Access denied: Could not delete file"))

    def read_file_from_s3(self, key):
        """
        Function to read file from a s3 file.
        """
        return self.S3_CLIENT.get_object(Bucket=self.BUCKET, Key=key)

    def get_url(self, key, file_name=None):
        """
        Return url.

        :param bucket: s3 bucket name
        :param key: s3 object key
        """
        if self.s3_settings_doc.signed_url_expiry_time:
            self.signed_url_expiry_time = self.s3_settings_doc.signed_url_expiry_time # noqa
        else:
            self.signed_url_expiry_time = 120
        params = {
                'Bucket': self.BUCKET,
                'Key': key,

        }
        if file_name:
            # Hetzner honours this S3 response override. It preserves the
            # original UTF-8 file name although the stored object key is a hash.
            params['ResponseContentDisposition'] = (
                "inline; filename*=UTF-8''{}".format(
                    quote(file_name, safe='')
                )
            )

        url = self.S3_CLIENT.generate_presigned_url(
            'get_object',
            Params=params,
            ExpiresIn=self.signed_url_expiry_time,
        )

        return url


def get_download_url(file_id, file_name=None):
    """Return a concise app route; do not persist Object Storage URLs."""
    url = "/s3/{}".format(file_id)
    if file_name:
        url += "/{}".format(file_name)
    return url


def update_attach_field_references(old_url, new_url):
    """Keep Attach fields (including child tables) in sync with File.file_url."""
    attach_fields = frappe.get_all(
        'DocField',
        filters={'fieldtype': ['in', ['Attach', 'Attach Image']]},
        fields=['parent', 'fieldname']
    )
    for field in attach_fields:
        if not frappe.db.table_exists(field.parent):
            continue
        table = 'tab{}'.format(field.parent).replace('`', '``')
        fieldname = field.fieldname.replace('`', '``')
        frappe.db.sql(
            "UPDATE `{}` SET `{}`=%s WHERE `{}`=%s".format(
                table, fieldname, fieldname
            ),
            (new_url, old_url)
        )


def get_file_for_key(key):
    file_name = frappe.db.get_value('File', {'content_hash': key}, 'name')
    if not file_name:
        frappe.throw(frappe._("File not found."), frappe.DoesNotExistError)
    file_doc = frappe.get_doc('File', file_name)
    if not file_doc.has_permission('read'):
        frappe.throw(frappe._("Not permitted."), frappe.PermissionError)
    return file_doc


def get_file_for_id(file_id):
    """Return a File document after checking its read permission."""
    file_doc = frappe.get_doc('File', file_id)
    if not file_doc.has_permission('read'):
        frappe.throw(frappe._("Not permitted."), frappe.PermissionError)
    return file_doc


def get_signed_url(file_doc, file_name=None):
    """Generate the authorised, short-lived Object Storage download URL."""
    s3_upload = S3Operations()
    object_key = s3_upload.key_generator(file_doc.content_hash, '', '', '')
    return s3_upload.get_url(object_key, file_name or file_doc.file_name)


def redirect_to_file(file_doc, file_name=None):
    signed_url = get_signed_url(file_doc, file_name)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = signed_url


@frappe.whitelist()
def file_upload_to_s3(doc, method):
    """
    check and upload files to s3. the path check and
    """
    s3_upload = S3Operations()
    path = doc.file_url
    site_path = frappe.utils.get_site_path()
    parent_doctype = doc.attached_to_doctype or 'File'
    parent_name = doc.attached_to_name
    ignore_s3_upload_for_doctype = frappe.local.conf.get('ignore_s3_upload_for_doctype') or ['Data Import']
    if parent_doctype not in ignore_s3_upload_for_doctype:
        if not doc.is_private:
            file_path = site_path + '/public' + path
        else:
            file_path = site_path + path
        s3_upload.upload_files_to_s3_with_key(
            file_path, doc.content_hash, doc.file_name,
            doc.is_private, parent_doctype,
            parent_name
        )

        file_url = get_download_url(doc.name, doc.file_name)
        os.remove(file_path)
        frappe.db.sql("""UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s WHERE name=%s""", (
            file_url, 'Home/Attachments', 'Home/Attachments', doc.name))

        doc.file_url = file_url
        update_attach_field_references(path, file_url)

        if parent_doctype and frappe.get_meta(parent_doctype).get('image_field'):
            frappe.db.set_value(parent_doctype, parent_name, frappe.get_meta(parent_doctype).get('image_field'), file_url)

        frappe.db.commit()


@frappe.whitelist()
def generate_file(key=None, file_name=None):
    """
    Function to stream file from s3.
    """
    if key:
        file_doc = get_file_for_key(key)
        redirect_to_file(file_doc, file_name)
    else:
        frappe.local.response['body'] = "Key not found."
    return


@frappe.whitelist()
def serve_legacy_file(legacy_file_url=None):
    """Resolve a missing /files URL through the authenticated download flow."""
    if not legacy_file_url or not legacy_file_url.startswith('/files/'):
        frappe.throw(frappe._("File not found."), frappe.DoesNotExistError)

    file_name = legacy_file_url.rsplit('/', 1)[-1]
    files = frappe.get_all(
        'File',
        filters={'file_name': file_name, 'is_private': 0},
        fields=['name', 'content_hash'],
        limit_page_length=2
    )
    if len(files) != 1:
        frappe.throw(frappe._("File not found."), frappe.DoesNotExistError)
    return serve_file_by_name(files[0].name)


@frappe.whitelist()
def serve_file_by_name(file_id=None):
    """Resolve a concise /s3/<File name> URL through the download flow."""
    if not file_id:
        frappe.throw(frappe._("File not found."), frappe.DoesNotExistError)
    return redirect_to_file(get_file_for_id(file_id))


def upload_existing_files_s3(name):
    """
    Function to upload all existing files.
    """
    file_doc_name = frappe.db.get_value('File', {'name': name})
    if file_doc_name:
        doc = frappe.get_doc('File', name)
        s3_upload = S3Operations()
        path = doc.file_url
        site_path = frappe.utils.get_site_path()
        parent_doctype = doc.attached_to_doctype
        parent_name = doc.attached_to_name
        if not doc.is_private:
            file_path = site_path + '/public' + path
        else:
            file_path = site_path + path

        # File exists?
        if not os.path.exists(file_path):
            return False, file_path

        s3_upload.upload_files_to_s3_with_key(
            file_path, doc.content_hash, doc.file_name,
            doc.is_private, parent_doctype,
            parent_name
        )

        file_url = get_download_url(doc.name, doc.file_name)

        # Remove file from local.
        os.remove(file_path)

        frappe.db.sql(
            """UPDATE `tabFile` SET file_url=%s, folder=%s,
            old_parent=%s WHERE name=%s""",
            (file_url, "Home/Attachments", "Home/Attachments", doc.name),
        )
        update_attach_field_references(path, file_url)
        frappe.db.commit()
        return True, None


def s3_file_regex_match(file_url):
    """Return whether a File URL is already served from S3."""
    return re.match(
        r'^(https:|/s3/|/api/method/frappe_s3_attachment.controller.generate_file)',
        file_url
    )


@frappe.whitelist()
def migrate_single_file(name):
    """Migrate one local File document to S3.

    ``name`` is the primary key of the File document (for example
    ``FILE-00001``), not its file name.
    """
    frappe.only_for('System Manager')

    file_url = frappe.db.get_value('File', name, 'file_url')
    if file_url is None:
        frappe.throw(frappe._('File not found.'), frappe.DoesNotExistError)
    if not file_url:
        frappe.throw(frappe._('File has no file URL.'))
    if s3_file_regex_match(file_url):
        frappe.throw(frappe._('File is already stored in S3.'))

    migrated, file_path = upload_existing_files_s3(name)
    if not migrated:
        frappe.throw(
            frappe._('Local file not found at {0}; migration was not performed.').format(
                file_path
            )
        )
    return {'name': name, 'migrated': True}


@frappe.whitelist()
def migrate_existing_files():
    """
    Function to migrate the existing files to s3.
    """

    files_list = frappe.get_all(
        'File',
        fields=['name', 'file_url']
    )
    for file in files_list:
        if file['file_url']:
            if not s3_file_regex_match(file['file_url']):
                upload_existing_files_s3(file['name'])
    return True


def delete_from_cloud(doc, method):
    """Delete file from s3"""
    duplicate_count = frappe.db.count(
        'File',
        filters={'content_hash': doc.content_hash, 'name': ['!=', doc.name]}
    )
    if not duplicate_count:
        s3 = S3Operations()
        s3.delete_from_s3(doc.content_hash)


@frappe.whitelist()
def make_existing_files_private():
    """Remove public-read ACLs from all objects tracked by this app."""
    s3_upload = S3Operations()
    files = frappe.db.sql(
        """SELECT name, content_hash FROM `tabFile`
        WHERE content_hash IS NOT NULL
        AND file_url LIKE %s""",
        ('/api/method/frappe_s3_attachment.controller.generate_file%',),
        as_dict=True
    )
    updated = 0
    for file_doc in files:
        try:
            s3_upload.S3_CLIENT.put_object_acl(
                Bucket=s3_upload.BUCKET,
                Key=s3_upload.key_generator(file_doc.content_hash, '', '', ''),
                ACL='private'
            )
            updated += 1
        except ClientError:
            frappe.log_error(frappe.get_traceback(), 'S3 ACL update failed')
    return updated


@frappe.whitelist()
def ping():
    """
    Test function to check if api function work.
    """
    return "pong"

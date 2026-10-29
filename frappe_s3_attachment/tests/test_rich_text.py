"""Storage integration tests; run with an initialised Frappe test site."""

import base64
import io
import json
import unittest
from unittest.mock import Mock, patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from frappe.core.doctype.file.file import File
from frappe_s3_attachment.controller import (
    file_upload_to_s3, get_file_for_id, get_file_redirect_url,
    update_upload_response,
)
from frappe_s3_attachment.file import S3File
from frappe_s3_attachment.www.s3_download import get_context


class TestRichText(unittest.TestCase):
    def make_file(self, url='/private/files/image.png', **values):
        return S3File(dict(
            doctype='File', name='test-image', file_name='image.png',
            file_url=url, is_private=1, **values,
        ))

    def test_pending_editor_url_keeps_local_path_for_other_hooks(self):
        doc = self.make_file()
        with patch.object(type(frappe.db.after_commit), 'add') as enqueue:
            file_upload_to_s3(doc, 'after_insert')
        enqueue.assert_called_once()
        self.assertEqual(doc.unique_url, '/s3/test-image/image.png')
        self.assertEqual(doc.file_url, '/private/files/image.png')

    def test_excluded_files_keep_local_unique_url(self):
        doc = self.make_file(attached_to_doctype='Data Import')
        with patch.object(type(frappe.db.after_commit), 'add') as enqueue:
            file_upload_to_s3(doc, 'after_insert')
        enqueue.assert_not_called()
        self.assertEqual(doc.unique_url, '/private/files/image.png?fid=test-image')

    def test_folders_and_remote_duplicates_are_not_scheduled(self):
        for doc in (self.make_file(is_folder=1), self.make_file('/s3/original/image.png')):
            with patch.object(type(frappe.db.after_commit), 'add') as enqueue:
                file_upload_to_s3(doc, 'after_insert')
            enqueue.assert_not_called()

    def test_local_fallback_has_private_file_id(self):
        doc = self.make_file()
        with patch('frappe_s3_attachment.controller.get_local_file_path'):
            self.assertEqual(
                get_file_redirect_url(doc), '/private/files/image.png?fid=test-image'
            )

    def test_s3_redirect_is_temporary(self):
        with patch('frappe_s3_attachment.www.s3_download.get_file_for_id'), patch(
            'frappe_s3_attachment.www.s3_download.get_file_redirect_url',
            return_value='https://signed.example/image.png',
        ), patch.dict(frappe.form_dict, file_id='test-image'):
            with self.assertRaises(frappe.Redirect) as redirect:
                get_context(frappe._dict())
        self.assertEqual(redirect.exception.http_status_code, 302)
        self.assertEqual(frappe.flags.redirect_location, 'https://signed.example/image.png')

    def test_denied_private_download_never_generates_a_signed_url(self):
        doc = Mock(is_private=1)
        doc.has_permission.return_value = False
        with patch('frappe_s3_attachment.controller.frappe.get_doc', return_value=doc), patch(
            'frappe_s3_attachment.controller.get_signed_url'
        ) as sign:
            with self.assertRaises(frappe.PermissionError):
                get_file_for_id('test-image')
        sign.assert_not_called()

    def test_get_content_reads_s3_bytes_and_closes_stream(self):
        doc = self.make_file('/s3/test-image/image.png', content_hash='image-hash')
        stream = io.BytesIO(b'image-bytes')
        with patch('frappe_s3_attachment.controller.S3Operations') as storage:
            storage.return_value.read_file_from_s3.return_value = {'Body': stream}
            self.assertEqual(doc.get_content(), b'image-bytes')
        self.assertTrue(stream.closed)

    def test_local_get_content_still_uses_frappe(self):
        with patch.object(File, 'get_content', return_value=b'local') as read:
            self.assertEqual(self.make_file().get_content(), b'local')
        read.assert_called_once()

    def test_pdf_inlines_authorised_s3_image(self):
        from frappe.utils.pdf import inline_private_images

        doc = self.make_file('/s3/test-image/image.png', content_hash='image-hash')
        with patch('frappe.utils.pdf.find_file_by_url', return_value=doc), patch(
            'frappe_s3_attachment.controller.S3Operations'
        ) as storage:
            storage.return_value.read_file_from_s3.return_value = {'Body': io.BytesIO(b'png')}
            html = inline_private_images('<img src="/s3/test-image/image.png">')
        self.assertIn('data:image/png;base64,' + base64.b64encode(b'png').decode(), html)

    def test_upload_response_is_rebuilt_after_commit(self):
        payload = {'message': {
            'doctype': 'File', 'name': 'test-image', 'file_url': '/private/files/image.png'
        }, 'other': 'preserved'}
        response = Response(json.dumps(payload), mimetype='application/json')
        request = Request(EnvironBuilder(path='/api/method/upload_file', method='POST').get_environ())
        with patch.object(frappe.db, 'get_value', return_value='/s3/test-image/image.png'):
            update_upload_response(response, request)
        result = response.get_json()
        self.assertEqual(result['message']['file_url'], '/s3/test-image/image.png')
        self.assertEqual(result['other'], 'preserved')
        self.assertEqual(int(response.headers['Content-Length']), len(response.data))

    def test_unrelated_and_failed_responses_are_untouched(self):
        for path, status in (('/api/method/other', 200), ('/api/method/upload_file', 500)):
            response = Response('{"message":{"doctype":"File","name":"test-image"}}',
                                status=status, mimetype='application/json')
            original = response.data
            request = Request(EnvironBuilder(path=path, method='POST').get_environ())
            with patch.object(frappe.db, 'get_value') as lookup:
                update_upload_response(response, request)
            lookup.assert_not_called()
            self.assertEqual(response.data, original)

    def test_s3_redirect_cannot_be_cached(self):
        response = Response(status=302)
        request = Request(EnvironBuilder(path='/s3/test-image/image.png').get_environ())
        update_upload_response(response, request)
        self.assertIn('no-store', response.headers['Cache-Control'])


class TestRichTextLifecycle(unittest.TestCase):
    """Use real Frappe documents/commits with only the S3 transport mocked."""

    def setUp(self):
        self.user = frappe.session.user
        frappe.set_user('Administrator')
        self.documents = []
        self.storage_patch = patch('frappe_s3_attachment.controller.S3Operations')
        self.storage = self.storage_patch.start().return_value
        self.storage.get_url.return_value = 'https://signed.example/image.png'

    def tearDown(self):
        # Cancel callbacks from a failed test before removing committed fixtures.
        frappe.db.rollback()
        try:
            for name in self.documents:
                for file_id in frappe.get_all(
                    'File', filters={'attached_to_doctype': 'ToDo', 'attached_to_name': name},
                    pluck='name',
                ):
                    frappe.delete_doc('File', file_id, ignore_permissions=True)
                if frappe.db.exists('ToDo', name):
                    frappe.delete_doc('ToDo', name, ignore_permissions=True)
            frappe.db.commit()
        finally:
            self.storage_patch.stop()
            frappe.set_user(self.user)

    def create_editor_document(self):
        from PIL import Image

        image = io.BytesIO()
        Image.new('RGB', (12, 12), 'blue').save(image, format='PNG')
        encoded = base64.b64encode(image.getvalue()).decode()
        doc = frappe.get_doc({
            'doctype': 'ToDo',
            'description': '<p>S3 editor integration test</p><img src="data:image/png;base64,'
                           + encoded + '">',
        }).insert()
        self.documents.append(doc.name)
        file_id = frappe.db.get_value('File', {'attached_to_name': doc.name}, 'name')
        return doc, frappe.get_doc('File', file_id)

    def test_editor_save_commit_duplicate_and_private_pdf(self):
        from frappe.utils.pdf import inline_private_images

        doc, file_doc = self.create_editor_document()
        expected_url = '/s3/{}/{}'.format(file_doc.name, file_doc.file_name)
        # Real Frappe extraction must embed the stable route before commit,
        # while hooks can still use the local File path.
        self.assertIn(expected_url, doc.description)
        self.assertTrue(file_doc.file_url.startswith('/private/files/'))
        content = file_doc.get_content()
        frappe.db.commit()
        file_doc.reload()
        self.assertEqual(file_doc.file_url, expected_url)
        self.assertIn(expected_url, frappe.db.get_value('ToDo', doc.name, 'description'))

        duplicate_doc, duplicate = self.create_editor_document()
        frappe.db.commit()
        self.assertEqual(duplicate.file_url, expected_url)
        self.assertEqual(duplicate.content_hash, file_doc.content_hash)
        self.assertIn(expected_url, duplicate_doc.description)
        self.storage.upload_files_to_s3_with_key.assert_called_once()

        self.storage.read_file_from_s3.return_value = {'Body': io.BytesIO(content)}
        html = inline_private_images(doc.description)
        self.assertIn('data:image/png;base64,', html)
        self.assertNotIn(expected_url, html)

        # The actual PDF lookup must not read S3 on behalf of an unauthorised user.
        frappe.set_user('Guest')
        self.storage.read_file_from_s3.reset_mock()
        self.assertIn(expected_url, inline_private_images(doc.description))
        self.storage.read_file_from_s3.assert_not_called()
        with self.assertRaises(frappe.PermissionError):
            get_file_for_id(file_doc.name)

    def test_failed_transfer_retains_local_download(self):
        import os
        from frappe_s3_attachment.controller import get_local_file_path

        doc, file_doc = self.create_editor_document()
        self.storage.upload_files_to_s3_with_key.side_effect = RuntimeError('S3 unavailable')
        with self.assertRaisesRegex(RuntimeError, 'S3 unavailable'):
            frappe.db.commit()
        file_doc.reload()
        self.assertTrue(os.path.isfile(get_local_file_path(file_doc.file_url, 1)))
        self.assertEqual(
            get_file_redirect_url(get_file_for_id(file_doc.name)),
            file_doc.file_url + '?fid=' + file_doc.name,
        )

    def test_direct_upload_response_after_real_commit(self):
        from frappe.handler import upload_file
        from frappe.utils.response import json_handler
        from PIL import Image

        doc = frappe.get_doc({'doctype': 'ToDo', 'description': 'S3 direct upload test'}).insert()
        self.documents.append(doc.name)
        image = io.BytesIO()
        Image.new('RGB', (13, 13), 'green').save(image, format='PNG')
        image.seek(0)
        request = Request(EnvironBuilder(
            path='/api/method/upload_file', method='POST',
            data={'file': (image, 's3-upload-test.png')},
        ).get_environ())
        form_data = frappe._dict(
            is_private=1, doctype='ToDo', docname=doc.name,
        )
        with patch.object(frappe.local, 'request', request, create=True), patch.object(
            frappe.local, 'form_dict', form_data, create=True
        ):
            uploaded = upload_file()
            self.assertTrue(uploaded.file_url.startswith('/private/files/'))
            response = Response(json.dumps({'message': uploaded}, default=json_handler),
                                mimetype='application/json')
            frappe.db.commit()
            update_upload_response(response, request)
        current_url = frappe.db.get_value('File', uploaded.name, 'file_url')
        self.assertTrue(current_url.startswith('/s3/'))
        self.assertEqual(response.get_json()['message']['file_url'], current_url)

    def test_generates_pdf_with_private_s3_image(self):
        import shutil
        from pypdf import PdfReader
        from frappe.utils.pdf import get_pdf

        if not shutil.which('wkhtmltopdf'):
            self.skipTest('wkhtmltopdf is not installed')
        doc, file_doc = self.create_editor_document()
        content = file_doc.get_content()
        frappe.db.commit()
        self.storage.read_file_from_s3.side_effect = lambda key: {'Body': io.BytesIO(content)}
        pdf = get_pdf('<html><head></head><body>' + doc.description + '</body></html>')
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(PdfReader(io.BytesIO(pdf)).pages[0].images), 0)
        self.storage.read_file_from_s3.assert_called_once()

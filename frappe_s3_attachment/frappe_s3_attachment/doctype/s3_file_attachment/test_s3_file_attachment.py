# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe and Contributors
# See license.txt
from __future__ import unicode_literals

import frappe
import unittest
from unittest.mock import Mock, patch

from frappe.core.doctype.file.file import File
from frappe_s3_attachment.controller import (
	get_content_hash_from_version_data,
	get_file_id_from_s3_url,
	get_file_for_id,
)
from frappe_s3_attachment.file import S3File

class TestS3FileAttachment(unittest.TestCase):
	def test_extracts_a_cleared_content_hash_from_version_data(self):
		version_data = {
			'changed': [
				['file_name', 'document.pdf', 'renamed-document.pdf'],
				['content_hash', 'previous-s3-key', None],
			],
		}
		self.assertEqual(
			get_content_hash_from_version_data(version_data), 'previous-s3-key'
		)

	def test_does_not_guess_a_content_hash_from_unrelated_history(self):
		self.assertIsNone(get_content_hash_from_version_data({
			'changed': [['content_hash', None, 'new-value']],
		}))

	def test_extracts_the_file_id_from_an_s3_download_url(self):
		self.assertEqual(
			get_file_id_from_s3_url('/s3/37dae744c8/document.pdf'),
			'37dae744c8',
		)
		self.assertIsNone(get_file_id_from_s3_url('/files/document.pdf'))

	def test_s3_route_preserves_content_hash_when_validated(self):
		"""Frappe's remote-file validation must not erase the S3 object key."""
		file_doc = S3File({
			'doctype': 'File',
			'file_url': '/s3/fd8bd9032e',
			'content_hash': 'a-content-hash',
		})

		def clear_content_hash(doc):
			doc.content_hash = None

		with patch.object(File, 'validate', clear_content_hash):
			file_doc.validate()

		self.assertEqual(file_doc.content_hash, 'a-content-hash')

	def test_public_s3_file_does_not_require_guest_read_permission(self):
		"""A public File remains available when the request is anonymous."""
		file_doc = Mock(is_private=0)
		with patch(
			'frappe_s3_attachment.controller.frappe.get_doc', return_value=file_doc
		):
			self.assertIs(get_file_for_id('fd8bd9032e'), file_doc)

		file_doc.has_permission.assert_not_called()

	def test_private_s3_file_still_requires_read_permission(self):
		file_doc = Mock(is_private=1)
		file_doc.has_permission.return_value = True
		with patch(
			'frappe_s3_attachment.controller.frappe.get_doc', return_value=file_doc
		):
			self.assertIs(get_file_for_id('fd8bd9032e'), file_doc)

		file_doc.has_permission.assert_called_once_with('read')

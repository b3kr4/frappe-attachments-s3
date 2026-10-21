# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe and Contributors
# See license.txt
from __future__ import unicode_literals

import frappe
import unittest
from unittest.mock import Mock, patch

from frappe_s3_attachment.controller import get_file_for_id

class TestS3FileAttachment(unittest.TestCase):
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

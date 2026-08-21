// Copyright (c) 2018, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('S3 File Attachment', {
	refresh: function(frm) {

	},
	migrate_existing_files: function (frm) {
		frappe.msgprint("Local files migration started in background. Progress and errors are logged in Error Log.", "S3 Migration");
        frappe.call({
            method: "frappe_s3_attachment.controller.migrate_existing_files",
            callback: function (data) {
                if (data.message && data.message.queued) {
					frappe.show_alert({message: 'S3-Migration enqueued', indicator: 'green'});
                } else {
                    frappe.msgprint('Retry');
                }
            }
        });
    },
});

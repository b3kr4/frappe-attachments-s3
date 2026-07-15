/* global frappe */

(function () {
	"use strict";

	function display_file_name(link) {
		var href = link.getAttribute("href") || "";
		var match = href.match(/\/s3\/[^/?#]+\/([^?#/]+)/);

		if (!match) {
			return;
		}

		var file_name;
		try {
			file_name = decodeURIComponent(match[1]);
		} catch (error) {
			file_name = match[1];
		}

		if (link.textContent.trim().indexOf("/s3/") !== -1) {
			link.textContent = file_name;
		}
		link.title = file_name;
	}

	function shorten_s3_links(root) {
		if (!root || root.nodeType !== Node.ELEMENT_NODE) {
			return;
		}

		if (root.matches && root.matches("a[href*='/s3/']")) {
			display_file_name(root);
		}
		root.querySelectorAll("a[href*='/s3/']").forEach(display_file_name);
	}

	function install() {
		shorten_s3_links(document.body);

		new MutationObserver(function (mutations) {
			mutations.forEach(function (mutation) {
				mutation.addedNodes.forEach(shorten_s3_links);
			});
		}).observe(document.body, {childList: true, subtree: true});
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", install);
	} else {
		install();
	}
}());

#!/usr/bin/env python3
"""Migrate local Frappe File records to S3 one file at a time.

This script calls the Frappe REST API and therefore can run from any machine
that can reach the Frappe site.  The supplied API user must have the System
Manager role, because the single-file migration endpoint requires it.
"""

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


S3_METHOD_PREFIX = '/api/method/frappe_s3_attachment.controller.generate_file'


def api_request(site, headers, path, data=None, retries=3):
    """Make one Frappe API request and return its decoded JSON response."""
    url = site.rstrip('/') + path
    body = urlencode(data).encode('utf-8') if data else None
    request_headers = dict(headers)
    if body is not None:
        request_headers['Content-Type'] = 'application/x-www-form-urlencoded'

    for attempt in range(1, retries + 1):
        try:
            request = Request(url, data=body, headers=request_headers)
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            response_body = error.read().decode('utf-8', errors='replace')
            if error.code < 500 or attempt == retries:
                try:
                    detail = json.loads(response_body).get('exception', response_body)
                except json.JSONDecodeError:
                    detail = response_body
                raise RuntimeError('HTTP {}: {}'.format(error.code, detail))
        except (URLError, TimeoutError) as error:
            if attempt == retries:
                raise RuntimeError('Connection error: {}'.format(error))

        wait_seconds = attempt * 2
        print('  temporary error; retrying in {} seconds...'.format(wait_seconds))
        time.sleep(wait_seconds)


def is_already_migrated(file_url):
    """Mirror the migration check used by the server-side app."""
    return file_url.startswith('https:') or file_url.startswith(S3_METHOD_PREFIX)


def find_pending_files(site, headers, page_size):
    """Return all File names whose URLs still point to local storage."""
    pending = []
    offset = 0
    scanned = 0

    while True:
        query = urlencode({
            'fields': json.dumps(['name', 'file_url']),
            'limit_start': offset,
            'limit_page_length': page_size,
        })
        response = api_request(site, headers, '/api/resource/File?' + query)
        files = response.get('data', [])
        if not files:
            break

        for file_doc in files:
            file_url = file_doc.get('file_url') or ''
            if file_url and not is_already_migrated(file_url):
                pending.append(file_doc['name'])

        scanned += len(files)
        print('\rIdentified: {} local files ({} records scanned)'.format(
            len(pending), scanned), end='', flush=True)
        offset += len(files)
        if len(files) < page_size:
            break

    print()
    return pending


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, help='Frappe base URL, e.g. https://erp.example.com')
    parser.add_argument('--api-key', default=os.getenv('FRAPPE_API_KEY'))
    parser.add_argument('--api-secret', default=os.getenv('FRAPPE_API_SECRET'))
    parser.add_argument('--page-size', type=int, default=500,
                        help='File records requested per API call (default: 500)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Only identify local files; do not migrate them')
    args = parser.parse_args()
    if not args.api_key or not args.api_secret:
        parser.error('provide --api-key and --api-secret, or set FRAPPE_API_KEY and FRAPPE_API_SECRET')
    if args.page_size < 1:
        parser.error('--page-size must be positive')
    return args


def main():
    args = parse_args()
    headers = {
        'Accept': 'application/json',
        'Authorization': 'token {}:{}'.format(args.api_key, args.api_secret),
    }
    pending = find_pending_files(args.site, headers, args.page_size)

    print('{} local file(s) found.'.format(len(pending)))
    if args.dry_run or not pending:
        return 0

    failed = []
    endpoint = '/api/method/frappe_s3_attachment.controller.migrate_single_file'
    for index, name in enumerate(pending, start=1):
        prefix = '[{}/{}] {}'.format(index, len(pending), name)
        try:
            api_request(args.site, headers, endpoint, {'name': name})
            print('{} migrated'.format(prefix))
        except RuntimeError as error:
            failed.append(name)
            print('{} FAILED: {}'.format(prefix, error), file=sys.stderr)

    print('Completed: {} migrated, {} failed.'.format(len(pending) - len(failed), len(failed)))
    if failed:
        print('Failed File names: {}'.format(', '.join(failed)), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

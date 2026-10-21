<a href="https://zerodha.tech"><img src="https://zerodha.tech/static/images/github-badge.svg" align="right" /></a>

## Frappe S3 Attachment

Frappe app to make file upload automatically upload and read from S3-compatible object storage.

This repository is a fork of [zerodha/frappe-attachments-s3](https://github.com/zerodha/frappe-attachments-s3).
The original project provides the S3 integration; this fork extends it for private,
Frappe-authorised use with Hetzner Object Storage.

#### Features from the original project

1. Upload both public and private files to s3.
2. Stream files from S3, when file is viewed everytime.
3. Lets you add S3 credentials
    (access key, secret key, bucket name, folder name) through UI and migrate existing
    files.
4. Deletes from s3 whenever a file is deleted in ui.

#### Additions in this fork

1. **Hetzner Object Storage** as a selectable S3-compatible provider. The endpoint
   is derived from the Hetzner bucket location or can be configured explicitly.
2. **Private object storage by default.** Bucket URLs are not stored or shown to
   users. Frappe verifies access to the corresponding `File` document and then
   redirects to a short-lived signed download URL.
3. **Content-addressed objects and deduplication.** Objects are stored below
   `{s3_folder_path}/sha256/{content_hash}`. Uploading identical content reuses the
   existing object; it is deleted only after the last referencing `File` is removed.
4. **Concise private download routes.** Attachments use `/s3/<file-id>/<file-name>`
   instead of public Object Storage URLs. The Frappe UI shows only the file name.
5. **Backward-compatible file links.** Existing `/files/...` links can continue to
   resolve through this app without modifying Frappe core or the web-server config.

#### Installation.

1. bench get-app https://bitbucket.org/hotset/frappe-attachments-s3.git
2. bench install-app frappe_s3_attachment

#### Configuration Setup.

1. Open single doctype "s3 File Attachment"
2. Select the storage provider and enter Bucket Name, S3 Access Key, S3 Secret Key,
    S3 bucket region name, and Folder Name.
    Folder Name- folder name is the default folder path in s3.
3. For **Hetzner Object Storage**, select that provider, enter the bucket location
    (for example `fsn1`) as the region, and use the S3 credentials generated in
    Hetzner Console. The endpoint is inferred as
    `https://&lt;region&gt;.your-objectstorage.com`; optionally enter it explicitly
    in **S3 Endpoint URL**.
    Hetzner buckets use virtual-host addressing, so public URLs are generated as
    `https://&lt;bucket&gt;.&lt;region&gt;.your-objectstorage.com/&lt;object-key&gt;`.
4. Migrate existing files queues the migration in Frappe's **long** worker. It
    processes bounded batches of 25 files, so large migrations do not keep the
    browser/API request open. Check the Error Log for individual files that
    could not be migrated.
5. Delete From Cloud when selected deletes the file form s3 bucket whenever a file
    is deleted from ui. By default the Delete from cloud will be unchecked.

### Migration helper

For large migrations, use `scripts/migrate_existing_files.py` from a machine
that can reach the Frappe site. It identifies local `File` records and migrates
them one at a time through the API, so every completed file is retained if a
later upload fails. The API key user requires the `System Manager` role. This
is also a good alternative if no long worker is configured.

```bash
python scripts/migrate_existing_files.py --site https://erp.example.com \\
  --api-key API_KEY --api-secret API_SECRET
```

Pass `--dry-run` to only list the number of files that would be migrated. API
credentials can also be supplied through `FRAPPE_API_KEY` and
`FRAPPE_API_SECRET` environment variables.

### Restore accidentally cleared S3 hashes

If older `/s3/` File records have an empty `content_hash`, first run the repair
in preview mode. It restores a value only when it is present as the old value
of a tracked File change, or when the `/s3/<file-id>/...` route references
another File record with a hash. Records without either source are reported and
left untouched.

```bash
bench --site SITE execute frappe_s3_attachment.controller.restore_missing_s3_content_hashes
```

After reviewing the returned `restored` and `unrecoverable` lists, apply the
same repair with:

```bash
bench --site SITE execute frappe_s3_attachment.controller.restore_missing_s3_content_hashes \
  --kwargs '{"dry_run": 0}'
```

#### License

MIT

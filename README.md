<a href="https://zerodha.tech"><img src="https://zerodha.tech/static/images/github-badge.svg" align="right" /></a>

## Frappe S3 Attachment

Frappe app to make file upload automatically upload and read from S3-compatible object storage.

#### Features.

1. Upload both public and private files to s3.
2. Stream files from S3, when file is viewed everytime.
3. Lets you add S3 credentials
    (access key, secret key, bucket name, folder name) through UI and migrate existing
    files.
4. Deletes from s3 whenever a file is deleted in ui.
5. Files are uploaded categorically in the format.
    {s3_folder_path}/{year}/{month}/{day}/{doctype}/{file_hash}

#### Installation.

1. bench get-app https://github.com/zerodhatech/Frappe-attachments-s3.git
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
4. Migrate existing files lets all the existing files in private and public folders
    to be migrated to s3.
5. Delete From Cloud when selected deletes the file form s3 bucket whenever a file
    is deleted from ui. By default the Delete from cloud will be unchecked.

#### License

MIT

# Snapshot storage

Choose one backend per radar series and keep its store outside the Skill directory.

## Backends

- `filesystem`: human-inspectable JSON and diff files, page locks, atomic writes, and index recovery.
- `sqlite`: one transactional WAL database for concurrent writers, compact backup, and querying.
- `git`: a dedicated, marked Git repository containing filesystem snapshots. Every non-idempotent capture becomes one commit and returns `git_commit` and `git_tree` provenance.
- `s3`: an S3-compatible private object-store prefix with AES-256 server-side encryption requests, create-only immutable snapshot objects, and conditional page-index updates that fail closed on concurrent writers.

Use `git` when immutable review history, change attribution, or later remote replication matters. It requires a new empty directory or an existing repository created by this backend. It refuses unmarked Git repositories and dirty working trees so it cannot silently commit unrelated user files. Commit identity is local to each command, hooks are disabled, and no remote is configured, contacted, fetched, or pushed.

Git history retains content even after a working-tree deletion. Store only public update/current-policy text. Never send authenticated Seller Center, account, customer, order, settlement, or credential-bearing content to this backend.

```text
python scripts/snapshot_platform_page.py --platform "Amazon" --url "https://..." --content-file page.txt --store radar-history.git --backend git --captured-at "2026-07-28T17:00:00+08:00" --output snapshot.json
daily-trade-radar snapshot-audit --store radar-history.git --output snapshot-audit.json
```

The audit checks Git object integrity, a clean working tree, tracked snapshot files, normalized-content hashes, snapshot filename/ID agreement, chronological predecessor chains, change-status semantics, and latest-page indexes. A failed audit is a blocking evidence-integrity gap. Resolve it before another capture or report delivery.

Remote replication remains an explicit operator action. If a private remote is later added, protect it with repository access controls and secret scanning; do not place credentials in remote URLs or the snapshot files. The Skill never pushes automatically.

## S3-compatible object storage

Use `s3` when multiple hosts need a shared private snapshot series. Install the optional dependency with
`pip install -e ".[s3]"`. Credentials come only from the standard AWS SDK credential chain; never put
access keys, session tokens, or signed query parameters in `--store` or `--s3-endpoint-url`.

```text
daily-trade-radar snapshot --platform "Amazon" --url "https://..." \
  --content-file page.txt --store "s3://private-radar/history" --backend s3 \
  --s3-region ap-southeast-1 --captured-at "2026-07-31T17:00:00+08:00" \
  --output snapshot.json
daily-trade-radar snapshot-audit --store "s3://private-radar/history" --backend s3 \
  --s3-region ap-southeast-1 --output snapshot-audit.json
```

For MinIO or another compatible service, add `--s3-endpoint-url https://objects.example.com`.
The backend requests `AES256` server-side encryption for every object. Bucket policy, versioning,
lifecycle retention, object lock, replication, and KMS policy remain operator-controlled infrastructure.
The backend uses `If-None-Match` for immutable snapshot/diff objects and an ETag `If-Match` update for
an existing page index. A store that does not implement conditional writes is unsupported because it
cannot protect the predecessor chain from concurrent lost updates.

The S3 audit walks every indexed predecessor chain and verifies object-key identity, canonical page
identity, normalized content hashes, chronological ordering, change semantics, exact stored diffs,
portable latest references, unreferenced objects, and the requested AES-256 encryption metadata.
Treat any audit failure as a blocking evidence-integrity gap.

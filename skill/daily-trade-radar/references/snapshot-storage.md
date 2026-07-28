# Snapshot storage

Choose one backend per radar series and keep its store outside the Skill directory.

## Backends

- `filesystem`: human-inspectable JSON and diff files, page locks, atomic writes, and index recovery.
- `sqlite`: one transactional WAL database for concurrent writers, compact backup, and querying.
- `git`: a dedicated, marked Git repository containing filesystem snapshots. Every non-idempotent capture becomes one commit and returns `git_commit` and `git_tree` provenance.

Use `git` when immutable review history, change attribution, or later remote replication matters. It requires a new empty directory or an existing repository created by this backend. It refuses unmarked Git repositories and dirty working trees so it cannot silently commit unrelated user files. Commit identity is local to each command, hooks are disabled, and no remote is configured, contacted, fetched, or pushed.

Git history retains content even after a working-tree deletion. Store only public update/current-policy text. Never send authenticated Seller Center, account, customer, order, settlement, or credential-bearing content to this backend.

```text
python scripts/snapshot_platform_page.py --platform "Amazon" --url "https://..." --content-file page.txt --store radar-history.git --backend git --captured-at "2026-07-28T17:00:00+08:00" --output snapshot.json
daily-trade-radar snapshot-audit --store radar-history.git --output snapshot-audit.json
```

The audit checks Git object integrity, a clean working tree, tracked snapshot files, normalized-content hashes, snapshot filename/ID agreement, chronological predecessor chains, change-status semantics, and latest-page indexes. A failed audit is a blocking evidence-integrity gap. Resolve it before another capture or report delivery.

Remote replication remains an explicit operator action. If a private remote is later added, protect it with repository access controls and secret scanning; do not place credentials in remote URLs or the snapshot files. The Skill never pushes automatically.

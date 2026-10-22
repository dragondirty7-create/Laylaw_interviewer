# Be Here Later — Stage 1 Independent Review

**Reviewing:** "Be Here Later: Manifest-first, client-pull download manager" (design proposal)
**Review date:** 2026-10-22
**Scope:** Planning and review only. No code was written, nothing was deployed, and no benchmark was run.
Every performance figure below is an estimate labelled **[untested]**.

---

## 0. Verdict: **REVISE** (core architecture: KEEP)

The core idea is sound and worth building: an immutable, content-addressed version, a small root manifest, a
streamed binary hash catalog, verified range pulls into one direct-offset temp file, a separate whole-file
SHA-256 gate, and an atomic rename. Nothing here needs to be rejected.

Eight revisions are needed before Claude Code starts. Items 1–4 change correctness or how the client
behaves on Windows; items 5–8 make it cheaper or simpler.

| # | Revision | Why |
|---|----------|-----|
| R1 | **Make `content_id` = the whole-file SHA-256** (content addressing). | A tampered manifest, a swapped source or a dishonest mirror can then cost time but can **never produce a false Ready**. Signed manifests drop out of the MVP. "Locate the original by content hash" comes for free. |
| R2 | **Separate hash granularity (fixed by the host) from request size (chosen by the client).** | Chunk size is part of the content version: the catalog depends on it, so the client cannot "adapt" it. The client adapts by asking for *runs* of adjacent chunks in one Range request and checking each chunk boundary as the bytes stream past. |
| R3 | **Fill the file in roughly ascending order with a bounded look-ahead window.** Do not write far ahead into a freshly extended file. | NTFS, exFAT and FAT zero-fill everything between the old valid data length and a new write. A first write at offset 900 GB into a just-extended file stalls on ~900 GB of zeroes. This is the most important Windows-specific failure mode in the proposal (§3). |
| R4 | **Flush before the final verify, read that verify unbuffered, and rename through the open handle.** | Otherwise the "100% verified" read can be served from the OS cache while the data never reached the disk. Renaming through the handle also closes the gap between verify and rename. |
| R5 | **Keep the state as a bitmap-in-pages SQLite schema**, not one row per chunk. | It meets "no per-chunk object or row" and keeps SQLite's tested crash safety. |
| R6 | **Make the whole-file gate the safety proof and the bitmap only an optimization.** Say this explicitly. | Then a lost or wrong checkpoint can only cost time, never integrity. The crash-test burden shrinks to "never Ready on a mismatch" plus "no wasted re-download at normal flush boundaries". |
| R7 | **Pilot as engine + console client first; GUI second.** Drop the two-pane browser from the pilot. | That is where the value and the risk are. The local-folder pane and host browser are UI work that proves nothing about integrity. |
| R8 | **Keep .NET Framework 4.8 for the pilot**, but put the engine in a `netstandard2.0` library behind small Windows-only interfaces. | It installs nothing, needs no admin rights and adds no runtime download. The engine stays testable in CI and portable to .NET 10 if measurements later justify a move (§5). |

---

## 1. Answers to the review questions

### Q1. Can a versioned immutable root manifest plus a streamed hash catalog describe every byte without unbounded RAM or metadata growth?

**Yes, for an immutable snapshot. No, for a *changing* source.** No manifest can describe a moving target. The
design is correct to require a snapshot: each new byte sequence gets a new version, which under R1 is
automatically a new `content_id`.

Metadata bounds, with chunk size picked at publish time (R2):

```
chunk_size = clamp(next_pow2(ceil(size / TARGET_CHUNKS)), 8 MiB, 1 GiB)     TARGET_CHUNKS = 65,536 (tunable)
catalog    = 32 B × chunk_count
bitmap     = chunk_count / 8 B
```

| File size | Chunk size | Chunks | Catalog (on disk) | Bitmap (RAM) |
|-----------|-----------|--------|-------------------|--------------|
| 1 B | 8 MiB | 1 | 32 B | 1 B |
| 20 GiB | 8 MiB | 2,560 | 80 KiB | 320 B |
| 1 TiB | 16 MiB | 65,536 | 2 MiB | 8 KiB |
| 100 TiB | 1 GiB | 102,400 | 3.1 MiB | 12.5 KiB |
| 8 PiB | 1 GiB | 8,388,608 | 256 MiB | 1 MiB |

The proposal's own example (1 TiB, 64 MiB chunks, 16,384 chunks, 524,288-byte catalog) is arithmetically
consistent; I checked it.

Client RAM is O(workers × buffer) + O(chunk_count / 8). It is about 1–2 MiB even at petabyte scale and does
not depend on file size beyond the bitmap. The catalog is read from disk one digest at a time, by index:
`offset = 32 × i`.

Validation guard rails (these are metadata sanity limits, **not** file-size limits):
`chunk_size` must be a power of two in [64 KiB, 4 GiB], and `chunk_count` ≤ 2^27 (4 GiB catalog, 16 MiB
bitmap). The largest describable file is then 2^59 B = 512 PiB, which is above NTFS's 8 PB per-file
implementation limit. In practice the guard rails never become the binding constraint.

### Q2. Is writing one file at fixed offsets safer and cheaper than assembling temporary parts?

**Yes. KEEP it.** It writes the data once instead of twice, needs one file's worth of disk instead of two,
creates no thousands-of-files directory churn, and finishes with one atomic rename. The bitmap, not the file
length, records what has arrived, so a pre-extended file proves nothing (as the proposal already says).

Windows-specific failure modes the build must handle:

| Failure mode | Effect | Mitigation |
|---|---|---|
| **Valid-data-length zero-fill** (NTFS, exFAT, FAT) | Writing far beyond the current end triggers a synchronous zero-fill of the gap. With large gaps it looks like a hang, wears SSDs and doubles HDD time. | R3: an ascending window, e.g. at most 4 × workers chunks ahead of the lowest missing chunk. Extend the file as the window advances. Repairs land behind the valid data length, so they cost nothing. `SetFileValidData` needs an admin privilege and exposes stale disk contents, so it is **forbidden**. NTFS sparse files are an optional later experiment, not the default (exFAT and FAT have no sparse support). |
| Defender or other antivirus scanning on close or rename | Rename fails with a sharing violation, or a 1 TB archive is scanned for minutes. | Retry the rename with backoff, show "Waiting for antivirus scan to release file", and never treat this as an integrity failure. |
| Destination inside OneDrive, Dropbox or Google Drive | The client uploads a multi-TB `.part` file mid-transfer. | Detect known sync roots and warn before starting. |
| NTFS-compressed or EFS-encrypted destination folder | Random writes become very slow, and huge compressed files can fail with resource errors. | Detect the attribute, warn, and suggest another folder. |
| Network share (SMB) destination | Flush semantics and SQLite locking are unreliable. | **Refuse in the MVP**, with a clear message. |
| USB drive unplugged, or drive letter changed | I/O errors; the job "disappears". | The state and `.part` live in the same folder, so they fail together and consistently. Record the volume GUID and serial number; on mismatch, ask Brian to locate the folder. |
| Sleep or hibernate | Sockets die silently. | Use an inactivity watchdog per read, not a total timeout. Optionally call `SetThreadExecutionState(ES_SYSTEM_REQUIRED)` *only while actively downloading*, as a user setting that is off by default. |
| Hostile `display_name` | Names like `file.zip:evil` create an NTFS alternate data stream; also `..\`, `CON`, `NUL`, trailing dots or spaces, control characters. | Sanitize to a leaf name, reject `:` and reserved device names, and let Brian confirm the final path. |
| Long paths | `PathTooLongException` | Use the `\\?\` prefix internally (supported on .NET 4.6.2+). The app manifest declares `longPathAware`. |
| Two instances, or another process writing the target | Interleaved writes. | A named mutex keyed on the normalized `.part` path, the `.part` opened with `FileShare.Read` only, and SQLite in exclusive locking mode. |
| `.part` replaced or copied by hand | The state store points at a different file. | Store the file ID and volume serial (`GetFileInformationByHandle`). On mismatch, treat every chunk as unverified and run an **adopt audit**, which rehashes from disk and keeps the matches. Discarding the data is never the default. |

### Q3. Can progress metadata claim completion before the data is durable? (with crash tests)

**Not if the ordering below is followed, and a false "Ready" is impossible even if it isn't** (R6).

Required ordering for each checkpoint:

```
1. workers write chunk bytes at their offsets              (OS cache)
2. chunk SHA-256 matches        -> chunk enters set P (verified, not yet durable)
3. checkpoint: snapshot S := P; FlushFileBuffers(.part)     (FileStream.Flush(true))
4. SQLite txn (synchronous=FULL): set bits for S; COMMIT    (bits now durable)
5. P := P \ S
```

A bit is set only after the bytes under it were flushed. That holds on honest hardware. Some USB enclosures
and consumer drives acknowledge a flush that never happened, and no program can defend against that
directly. So:

- **Unclean-exit rule:** state holds a `clean_close` flag. If it is missing at startup, re-verify the chunks
  committed in the last 2 checkpoints (a few GB at most) before resuming.
- **Final gate (R4):** `FlushFileBuffers` → full sequential SHA-256 with `FILE_FLAG_NO_BUFFERING`
  (sector-aligned 4 MiB reads, so the hash reads the disk and not the cache) → compare the length and digest
  → rename. A lie at any earlier step is caught here, and the chunk audit then repairs it.
- **Rename:** use `SetFileInformationByHandle(FileRenameInfo, ReplaceIfExists = false)` on the same handle
  that was verified. Fall back to `MoveFileEx(MOVEFILE_WRITE_THROUGH)` with no replace flag. The old name
  can never be replaced; a name that already exists produces a conflict prompt.
- **Post-rename crash:** state says `Sealing`. If the final file exists and `.part` does not, rehash the
  final file before showing Ready. The receipt is written only after that.

**Crash-test demonstration plan.** These tests are designed but **not yet executed**. They gate Stage 2,
step 3.

The engine runs as a child process. Environment variable `BHL_FAULT=<point>:<n>` kills it with
`TerminateProcess` the *n*-th time execution reaches a fault point. A `LyingDisk` test backend simulates power
loss by discarding a random subset of writes made since the last honest flush.

| Fault point | Kill or fault between | Invariant checked after restart |
|---|---|---|
| F1 | chunk bytes written → hash computed | Bit not set; chunk re-fetched |
| F2 | hash OK → flush | Bit not set; chunk re-fetched |
| F3 | flush → SQLite commit | Bit not set; at most one checkpoint of data is re-fetched |
| F4 | SQLite commit → next write | Bit set; data on disk matches the catalog |
| F5 | all bits set → final verify | Final verify runs again from the start |
| F6 | verify OK → rename | `.part` re-verified, then renamed; never Ready before that |
| F7 | rename → receipt | Final file rehashed, then Ready |
| F8 | `LyingDisk` drops unflushed + "flushed" writes | The unclean-exit window or the final gate catches it; the chunk audit repairs it; **never a false Ready** |
| F9 | `.part` byte flipped while paused | The final gate fails → audit finds exactly that chunk → one chunk re-fetched |

Pass criterion, run 1,000× with random *n*: zero false Ready, and zero re-downloads of chunks whose bits
were committed (except under F8 and F9).

### Q4. Do adaptive chunks, four workers, on-disk catalogs and SHA-256 scale from 2 GB to enormous files on HDDs and SSDs?

**Yes in principle. Every number here is [untested] until benchmarked on Brian's machine.**

- **SHA-256 throughput** [untested estimate]: about 1.5–2 GB/s per core with SHA-NI CPU instructions, about
  0.3–0.5 GB/s per core without them. Many Windows 10-era desktops (Skylake through Comet Lake Intel) lack
  SHA-NI. Hashing runs on the workers in parallel during transfer; the final verify is one sequential
  stream.
- **Final verify time for 1 TiB** [untested]: an HDD at about 150–250 MB/s takes about 1.2–2 h; a SATA SSD
  takes about 40 min; NVMe is CPU-bound, about 10–60 min depending on SHA-NI. The proposal is right not to
  skip this. It needs its own progress bar and ETA, as specified.
- **HDD:** R3's ascending window keeps writes near each other, so four workers behave almost like
  sequential writes. Without R3, an HDD seeks across the whole platter.
- **Workers:** start at 4. Adaptive 1–8 is a later feature: the pilot ships a fixed, configurable count.
- **On .NET 4.8**, `ServicePointManager.DefaultConnectionLimit` is **2 per host** by default and must be
  raised, or "4 workers" is really 2. `HttpClient.Timeout` (default 100 s) must be infinite, with a
  per-read inactivity watchdog; otherwise any chunk that takes over 100 s fails.
- **Request sizing (R2):** one request covers `k` adjacent missing chunks, up to about 30 s of transfer at the
  measured speed (ceiling 256 MiB). This removes per-request overhead without making hash granularity coarse.
- **Measured alternatives to run:** a single-stream `curl --range` baseline; 1, 2, 4 and 8 workers; 8, 16
  and 64 MiB hash chunks; HDD vs SSD. Report throughput, peak RAM (working set), CPU and on-disk overhead
  (state + catalog bytes).

### Q5. Is WinForms on .NET Framework 4.8 plus a small HTTP host the leanest reliable choice for Windows 10 Pro?

**For the client: KEEP it, with the engine isolated (R8).**

| | .NET Framework 4.8 / 4.8.1 WinForms | .NET 10 WinForms (LTS) |
|---|---|---|
| Runtime on Win10 | Built into Windows 10 1903+ (4.8); nothing to install | Must be bundled (self-contained, tens of MB) or installed separately |
| Admin rights | None | None if self-contained |
| 64-bit file I/O | `FileStream` is `long`-based; positional writes need a lock around `Seek` + `Write` | `RandomAccess.Write(handle, buf, offset)` is thread-safe positional I/O |
| HTTP | `HttpClient` over `HttpWebRequest`: connection-limit and timeout quirks (above) | `SocketsHttpHandler`: cleaner |
| JSON | Needs `System.Text.Json` from NuGet (netstandard2.0) | Built in |
| Support horizon | Tied to the Windows lifecycle | LTS through about Nov 2028 [verify] |

The quirks on 4.8 are well understood and fixable in a few lines each. For a portable, no-install tool on a
Windows 10 box, an in-box runtime is the leaner choice. Revisit only if a benchmark shows 4.8 is a measurable
bottleneck, which is unlikely: the network or disk is.

**Host: Go is a good fit. KEEP it as the recommendation, not a requirement.** `net/http`'s `ServeContent`
correctly implements `Range`, `If-Range`, `206`, `Content-Range` and `416`. The wrapper must (a) set a
strong `ETag` *before* calling `ServeContent` so `If-Range` is evaluated, (b) **reject multi-range requests**
(the client never sends them, and `ServeContent` would answer `multipart/byteranges`), (c) disable
compression, and (d) check the bearer token. One static binary runs on any host OS. Do not put a CDN or
proxy in front unless tested: some rewrite strong ETags as weak ones or compress responses.

### Q6. How do we enforce correct HTTP ranges, no content transformation, remote identity, and safe authentication?

**Request** (exactly one range, always):
```
GET /files/<content_id> HTTP/1.1
Range: bytes=<start>-<end>               ; inclusive end, single range only
If-Range: "<strong_etag>"                ; strong ETag = "sha256-<hex>"
Accept-Encoding: identity
Cache-Control: no-transform
Authorization: Bearer <token>            ; only to the configured origin
```

**Response accepted only if every check passes**, otherwise the response is disposed **immediately**. Never
drain a 200 that may be the whole multi-TB body.

1. Status is exactly `206`. A `200` means the server ignored the range or `If-Range` failed: abort and mark
   *Source changed / unsupported*. A `416` re-reads the manifest.
2. `Content-Type` is not `multipart/byteranges`.
3. `Content-Range` is parsed strictly as `bytes S-E/T`, with digits only, no sign, no whitespace tricks,
   ≤ 19 digits, and checked `long`. Require `S == start`, `E == end` and `T == size_bytes`. Reject `*`.
4. `ETag` is present, strong, and byte-equal to `strong_etag`.
5. `Content-Encoding` is absent or `identity`. On .NET 4.8, `HttpClientHandler.AutomaticDecompression = None`
   (the default) and the raw header is checked.
6. If `Content-Length` is present it equals `E − S + 1`. Either way the body is counted, and the response is
   rejected on short **or long** bodies.
7. Each chunk's streamed SHA-256 equals `catalog[i]`.

**Remote identity:** a content-addressed URL plus a strong ETag plus the final hash. Under R1, no identity
confusion can survive to Ready.

**Authentication:**
- Bearer token stored with DPAPI (`ProtectedData`, CurrentUser) or Windows Credential Manager. Never in the
  manifest, state DB or logs.
- `AllowAutoRedirect = false`. Redirects are followed manually and only to the same origin; a token is never
  sent to another host.
- `content_url` and `hash_catalog.url` must share the manifest's origin in the MVP.
- TLS certificate validation stays on; `ServerCertificateValidationCallback` is never overridden, and
  `SecurityProtocol = SystemDefault`. Windows 10 SChannel provides TLS 1.2. For a LAN-only host without a
  public certificate, see decision D2.
- 401/403 → *Needs sign-in*. These are not retried with backoff.

**Manifest trust:** fetch over authenticated HTTPS from Brian's configured host. Parse JSON strictly:
reject duplicate keys, unknown `schema_version`, non-canonical decimal strings and negative values. With R1,
signatures are only needed later for untrusted mirrors, and even then only to prevent wasted bandwidth, not
false Ready.

### Q7. What happens weeks later when the host's original disappears or changes?

| Guarantee | Depends on |
|---|---|
| Local `.part`, catalog, state and bitmap survive pause, exit, reboot and app update; only OVER IT deletes them | **Local only.** Guaranteed by design, barring disk failure, Brian deleting files, or antivirus quarantine. |
| Already-verified chunks are never re-downloaded on resume | **Local only.** After an unclean exit, the last-window re-verify can re-fetch a little. |
| The job can finish | **Host retention.** The host must still serve that exact `content_id`. |
| No mixing of versions | **Enforced locally** by content ID, ETag and the final hash. |

Resume flow: fetch `GET /manifests/<content_id>`.
- `200` with identical identity fields → continue.
- `404` or `410` → **Waiting for source** (all bytes kept, backoff while the app is open, no polling when
  closed).
- `401` or `403` → **Needs sign-in**.
- Network failure → **Waiting for source**.
- Identity fields differ → **Source changed — paused safely** (never mixed).

*Locate original by content hash:* Brian pastes another manifest URL. It is accepted only if `sha256_full`,
`size_bytes`, `chunk_size_bytes` and the catalog SHA-256 all match, and then the bitmap is reused unchanged.
If only the chunk size differs, an adopt audit can rehash the local bytes under the new catalog. That is
deferred past the pilot.

*Long gap with a clean close:* a full re-audit of a TB file is hours of disk reading. **Recommendation:** on
resume after more than 7 days, spot-check 64 random verified chunks plus the last checkpoint window, and rely
on the final gate for the rest. "Verify Again" runs the full audit on demand. Decision D6 is Brian's.

**Host retention is a policy, not a technical guarantee.** The manifest may carry an informational
`retain_until`, and the UI must never imply indefinite availability.

### Q8. Can a file pass the whole-file SHA-256 and still be unusable?

**Yes.** A matching hash proves the bytes equal the published bytes, nothing more. A source that was already
truncated, half-rendered or corrupt arrives perfectly intact and perfectly broken. Optional format checks,
reported separately from integrity:

| Format | Check | Where |
|---|---|---|
| ZIP / ZIP64 | Read the central directory and recompute the CRC-32 of every entry (`System.IO.Compression` reads ZIP64) | Host before publishing; client optional after Ready |
| 7z / RAR | Test the archive (`7z t`); both carry CRCs | Host |
| FLAC | `flac -t` checks the embedded MD5 of the decoded audio | Host |
| WAV / AIFF / BWF | Header data-chunk length is consistent with the file length; RIFF/RF64 for files over 4 GiB | Host and client (cheap) |
| Video / compressed audio | `ffmpeg -v error -i f -f null -` full decode | Host only (slow) |
| DAW projects (Pro Tools, Logic, etc.) | No open validator; producer opens and re-saves before publishing | Host, manual attestation |

The result is shown as "Format check: passed / failed / not run", **never** merged into Ready.

### Q9. What should be removed to finish a reliable prototype quickly?

Cut from the pilot (most of it returns later):

- the left local-folder pane (a destination picker is enough)
- the right host-browser pane (pilot input is "Open manifest URL")
- adaptive concurrency (fixed and configurable instead)
- the bandwidth cap (keep the hook only)
- alternate URLs and mirrors, and signed manifests (unnecessary given R1)
- format checks (host-side ZIP and FLAC later)
- the download-history UI (keep a one-line receipt file)
- sparse-file mode
- most Egyptian styling (palette only; motifs after the integrity gates pass)
- sleep inhibition
- network-share destinations (refused)

**Kept, non-negotiable:** every integrity gate, crash ordering, OVER IT, Waiting for source, the strict range
validator, and the overflow-safe arithmetic.

### Q10. Are size fields, offsets, indexes, progress, bitmap addressing and host responses 64-bit safe?

Rules:

1. Every byte count, offset, index and count is `long` (`Int64`) and computed in `checked` contexts. `int`
   is allowed only for buffer lengths ≤ 1 MiB and bitmap byte offsets, which are validated ≤ 2^24.
2. Manifest validation uses `checked` throughout:
   - `size ≥ 1`; `chunk_size` is a power of two in [2^16, 2^32].
   - `chunk_count == (size + chunk_size − 1) / chunk_size`, computed as `(size − 1) / chunk_size + 1` to
     avoid overflow near 2^63.
   - `chunk_count ≤ 2^27`.
   - `catalog_size == 32 × chunk_count`.
   - `last_len = size − (chunk_count − 1) × chunk_size`, with `1 ≤ last_len ≤ chunk_size`.
3. Chunk offsets are derived as `i × chunk_size` (checked). The manifest never supplies offsets. The range
   end is `start + len − 1` (checked).
4. Bitmap addressing: `byte = i >> 3`, `bit = i & 7`, with `i` validated `< chunk_count` first. SQLite rows
   hold 4 KiB pages covering 32,768 chunks each: `page = i >> 15`.
5. Progress: the WinForms `ProgressBar` gets `(int)Math.Round(10000.0 * done / size)`. `double` is used only
   for display; values above 2^53 lose sub-byte precision, which is invisible at 0.01%. Counters stay `long`.
6. JSON: all byte counts are decimal **strings** (also `chunk_size_bytes`, for consistency), parsed with
   `NumberStyles.None`. Reject a leading `+` or `-`, leading zeros (except `"0"`), more than 19 digits, and
   values above `long.MaxValue`.
7. Content-Range is parsed with the same strict parser (Q6).

**Overflow test vectors** (pure-logic and mock-I/O tests; nothing large written to disk):

- 2^31 − 1, 2^31, 2^32 − 1, 2^32, 2^32 + 1, 2^53, 2^53 + 1, 2^63 − 1
- `size = 2^63 − 1` with `chunk_size = 2^32`: validates arithmetically, then is rejected by the filesystem
  check with an exact message
- `(chunk_count − 1) × chunk_size` overflow attempts
- Content-Range totals of 20 digits, `-1`, `+5`, `0005`, and embedded whitespace
- a catalog length off by ±1 and ±32
- a last chunk of exactly `chunk_size`, and a last chunk of 1 byte

**Realistic maximum on Brian's disk** (verify against Microsoft's "NTFS overview" for the installed build):

- NTFS (Win10 1709+): about 8 PB per file, but the volume size depends on cluster size. With 4 KiB clusters
  the volume caps at about 16 TB.
- exFAT: volume-limited.
- FAT32: 4 GiB − 1 B.

**In practice the maximum is the free space on the destination volume**, for example less than 4 TB on a
4 TB drive. The client reports the binding limit by name before starting: *"FAT32 cannot store files of
4 GiB or more"*, or *"needs 3.2 TB, 1.1 TB free on D:"*. The app imposes no size cap of its own.

---

## 2. Revised architecture (deltas from the proposal only)

**Root manifest v1.** Same as the proposal, plus:
- `"content_id": "sha256-<64 hex>"` (R1)
- all byte counts as strings
- `"hash_alg": "sha-256"`
- `"chunking": "fixed-pow2-v1"`
- optional `"retain_until"` and `"format_check": {"tool", "result", "at"}`

**Host publishing (`bhl-host publish <file>`):**
1. Stat the source (size, mtime, file ID).
2. Make a single streaming pass: read the source → write the managed store → compute the full SHA-256 and
   the per-chunk SHA-256 → append raw digests to the catalog file.
3. Re-stat the source. Abort if anything changed. The copy is self-consistent by construction, but a source
   that changed mid-pass is almost certainly a torn file.
4. Rename the store entry to `sha256-<hex>`, then mark it read-only.
5. Write `manifest.json`.

Never hard-link: a hard link shares the original's bytes, so later edits to the original would change the
published version. At serve time, refuse an entry whose size or mtime drifted.

**Client storage**, all in the destination folder on the same volume:
- `<name>.bhl.part` — the data
- `<name>.bhl.cat` — the verified catalog
- `<name>.bhl.state` — SQLite, `journal_mode=WAL`, `synchronous=FULL`, exclusive locking. Tables:
  - `meta`: manifest JSON, its SHA-256, file ID, volume serial, `clean_close`, schema version
  - `bitmap_page(page INTEGER PRIMARY KEY, bits BLOB(4096))`
  - `event_log`: capped ring buffer for diagnostics

**Client engine pipeline:**
- The scheduler picks the lowest missing runs within the window (R3).
- Workers stream 256 KiB buffers: hash incrementally, then a positional write under the file lock.
- The checkpointer flushes, then commits (Q3), every 2 s or 256 MiB, whichever comes first.
- The sealer runs flush → unbuffered full hash → handle rename → receipt.
- On a final mismatch: audit all chunks from disk → re-fetch failures → re-seal. If the audit finds nothing
  wrong, the state is **Failed integrity — manifest/source inconsistency** with no retry loop.

**Retries:**
- Per chunk: at most 5 attempts, with exponential backoff and full jitter (1 s → 60 s). `Retry-After` is
  honored for 429 and 503.
- At the job level: **Waiting for source**, backoff capped at 15 min, only while the app is open.
- Auth and validation failures are never auto-retried.

States and microcopy stay as proposed. Add **Needs sign-in**, kept distinct from *Waiting for source*.

---

## 3. Prioritized build checklist (Stage 2, once this review is accepted)

**P0 — engine core, pure logic, CI on Linux and Windows:**
1. Strict decimal and Content-Range parsers; manifest validator with checked arithmetic; overflow test vectors (Q10).
2. Catalog streaming (download to a sidecar file, verify its SHA-256, read digest `i` by seek).
3. Chunk planner: window, runs, and repair queue.
4. State store: SQLite bitmap pages, checkpoint protocol, `clean_close`.
5. The `IFileBackend` / `IHttpTransport` interfaces, a `MockSparseFile` backend (offsets up to 2^63) and the `LyingDisk` backend.

**P1 — host and transport:**
6. `bhl-host` (Go): `publish` and `serve` with token auth, strong ETag, single-range-only, no compression.
7. An **"evil proxy" test fixture** that can:
   - flip byte *k* of chunk *n*
   - return 200 instead of 206
   - shift `Content-Range` boundaries
   - send a weak or wrong ETag
   - gzip the body
   - truncate the body, or send extra bytes
   - send multipart
   - redirect to another host
8. HTTP client with the full validation list (Q6) and the .NET 4.8 connection-limit and timeout fixes.

**P2 — Windows durability:**
9. Ascending-window file extension (R3); positional writes; `FlushFileBuffers`.
10. The sealer: unbuffered verify, handle rename with no replace, write-through fallback, conflict prompt, receipt.
11. Fault-injection harness F1–F9 (Q3), run 1,000× in CI on Windows.
12. Locks and mutex, the file-ID ownership check and adopt audit, the free-space and filesystem preflight, path sanitization.

**P3 — client console (`bhl get <manifest-url> <dest>`):** pause on Ctrl+C, resume, verify, over-it — the pilot deliverable.

**P4 — WinForms GUI:** toolbar, virtual-mode queue list, log pane, state vocabulary, OVER IT confirmation text exactly as specified, palette.

**P5 — soak and benchmarks** on real Windows 10 Pro hardware (§4). Then a portable zip and a short manual.

## 4. Test plan

**Tier A — automated, every commit:**
- parsers and overflow vectors
- planner and bitmap logic
- `MockSparseFile` transfers at offsets above 2^31, 2^32, 2^53 and near 2^63
- catalog-streaming memory test: simulated 2^27-entry catalog, assert peak working set < 64 MiB
- all evil-proxy cases → the expected rejection state
- F1–F9 fault injection

**Tier B — Windows 10 Pro integration, per milestone.** Use deterministic seeded-random files of:
1 B, exactly 1 chunk, 1 chunk + 1 B, 2 GiB, 4 GiB + 1 B, and 20 GiB (full soak).

Scenarios:
- out-of-order and duplicate arrivals
- kill mid-request
- pull the USB drive
- change the drive letter
- low disk space and exhaustion mid-transfer
- the FAT32 4 GiB refusal
- locked final name
- existing destination
- a second instance
- a destination under OneDrive
- a long path
- Defender holding the file on rename
- source replaced with the same name and size → *Source changed*
- host down → *Waiting for source*
- token revoked → *Needs sign-in*
- state rolled back to fake a multi-week gap
- deliberate corruption repaired without re-fetching unaffected chunks (the receipt shows the re-fetched chunk list)

**Tier C — evidence pack:**
- recorded SHA-256 equality (host vs client receipt) for at least 5 completed files
- the interrupted-and-resumed 20 GiB transfer, plus the largest size storage allows (target ≥ 100 GiB), with
  byte counters proving no verified data was re-downloaded
- throughput, peak RAM, CPU and on-disk overhead against a single-stream baseline

**No benchmark numbers are to be written down until they are measured.**

## 5. Risk list

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Zero-fill stalls on far-ahead writes | High without R3 | Looks hung; HDD time doubles | R3 window; test 100 GiB on HDD |
| Windows 10 security support | **Already material**: consumer ESU ended 2026-10-13 [verify enrollment] | Unpatched TLS stack and OS | Outbound-only client; no listening ports; commercial ESU or upgrade path is a decision for Brian and Michael (D7) |
| Drive or enclosure lies about flushes | Medium (USB) | Re-fetches after power loss | Unclean-exit window plus the final gate; never a false Ready |
| Host retention lapses | Medium over weeks | Job blocked | Visible *Waiting for source*; `retain_until`; content-hash relocate |
| Proxy or CDN alters ETag or encoding | Low–Medium | Transfers refused | Strict validator gives a clear "unsupported host" message; no CDN in the MVP |
| Antivirus interference on 1 TB files | Medium | Rename delays | Retry with a clear message |
| .NET 4.8 HTTP quirks | Certain | 2 connections; 100 s timeouts | Fixed in P1 #8 |
| Scope creep into an FTP client | Medium | Delay | R7; this review's cut list |
| Full verify time on big HDD files | Certain | Hours per TB | Honest separate progress; it is the gate and is not skippable |

## 6. Acceptance criteria for the pilot (P0–P3)

1. Zero false Ready across all fault-injection runs and every evil-proxy case.
2. A 20 GiB transfer interrupted at least 5 times (kill, reboot, unplug) finishes with matching SHA-256 and
   ≤ 1 checkpoint of re-download per interruption.
3. One injected bad chunk is detected and only that chunk is re-fetched (shown by the byte counter).
4. A changed source is refused, and a missing source shows *Waiting for source* with every local byte kept.
5. OVER IT is the only path that deletes, and it shows the specified confirmation text.
6. Peak working set ≤ 64 MiB at 4 workers on a 2^27-chunk simulated catalog.
7. All overflow vectors pass, and the filesystem limits produce exact, named messages.
8. Measured throughput is within 20% of the single-stream baseline or better on the same link (the target,
   to be confirmed by measurement).

## 7. Verified facts vs assumptions vs untested claims

**Treated as established** (standards or well-documented platform behaviour; re-check against current docs
during implementation):
- RFC 9110 range semantics: inclusive end, 206, `Content-Range`, `If-Range` requires a strong validator, and
  failure gives a 200 full response.
- FAT32's 4 GiB − 1 file limit.
- NTFS valid-data-length zero-fill on extending writes.
- `SetFileValidData` requires `SE_MANAGE_VOLUME_NAME`.
- The .NET Framework `DefaultConnectionLimit = 2` and `HttpClient.Timeout = 100 s` defaults.
- `FileStream.Flush(true)` calls `FlushFileBuffers`.
- Go `ServeContent` range handling.
- Windows 10 support ended 2025-10-14.
- The proposal's 1 TiB / 64 MiB / 524,288-byte catalog arithmetic (checked here).

**Assumptions to verify:**
- Brian's machine has .NET 4.8 or later (default on Win10 1903+).
- The destination is NTFS on local disk.
- The host is reachable over HTTPS.
- The consumer ESU end date is 2026-10-13 and Brian's ESU status is unknown.
- The NTFS 8 PB per-file figure applies to Brian's build.
- The .NET 10 LTS support window and its Windows 10 support policy.

**Untested performance claims:** every throughput, hash-speed, verify-time and memory figure in this document.

## 8. Unresolved decisions for Brian and Michael

- **D1** — Where does the host run (OS, machine), and how is it reached: LAN, VPN or internet? (This document
  authorizes no exposure.)
- **D2** — TLS trust: a public certificate on a domain, a private CA installed in Brian's user certificate
  store, or a pinned certificate fingerprint in the connection profile (validation still on, but anchored to
  one key)?
- **D3** — Authentication: one long-lived token per user, or per-file expiring tokens? Who issues and revokes
  them?
- **D4** — Host retention policy: how long published versions stay, who deletes them, and whether
  `retain_until` is shown.
- **D5** — Runtime: accept .NET Framework 4.8 for the pilot (recommended) or fund the move to .NET 10 now.
- **D6** — Resume after a long gap: spot-check plus final gate (recommended), or a mandatory full re-audit.
- **D7** — Windows 10 security posture: enroll in ESU, accept the risk for an outbound-only tool, or plan an
  OS upgrade.
- **D8** — Real workload: typical and largest file sizes and formats, so the soak test and format checks
  (ZIP? FLAC? WAV/RF64?) target real files.
- **D9** — Keep verification receipts after Ready (recommended: yes, one small text file each)?

---

*The approval boundary is unchanged: this review authorizes no implementation, deployment, network exposure,
distribution or spending. Stage 2 begins only when Brian (and Michael, where relevant) accepts it.*

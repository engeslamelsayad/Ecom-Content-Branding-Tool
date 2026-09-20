# Media Studio and review workflow

This release retains all script/strategy modules and adds final image, audio and
multi-scene video files. It is designed for the existing single-process Railway
deployment and client membership system. Self-service billing, subscriptions,
invitations and account recovery are separate follow-up work.

## Connect production

1. Create a fal account, add a balance and create an API key at
   https://fal.ai/dashboard/keys.
2. As the application owner, open **استوديو الإنتاج → اتصال API**, paste the key,
   and save. It is encrypted on the server; the API never returns it to members.
   Do not put the key in browser code, Git, an issue or a chat message.
3. The optional read-only check verifies API reachability and reports explicit
   authentication errors. It does **not** guarantee model access, account balance
   or a successful paid generation.
4. Choose a brand and produce one reviewed image, then test Arabic speech and a
   short video. Review product details, Arabic text, pronunciation and brand fit.

Optional server fallback: `FAL_KEY`. A saved encrypted connection takes precedence.
To rotate, save a replacement key in the same panel and revoke the old key in fal.

Models (verified against official schemas on 2026-09-20):

| Output | Endpoint | Settings |
| --- | --- | --- |
| Image | `fal-ai/nano-banana-pro` | PNG, 1K, one image |
| Image with reference | `fal-ai/nano-banana-pro/edit` | Reference product photo sent as data URI |
| Video scene | `fal-ai/kling-video/v2.6/pro/text-to-video` | 5 or 10 seconds, silent |
| Video with reference | `fal-ai/kling-video/v2.6/pro/image-to-video` | Product reference image |
| Narration | `fal-ai/elevenlabs/tts/eleven-v3` | Arabic or English, selected standard voice |

Official schemas: [image](https://fal.ai/models/fal-ai/nano-banana-pro/api),
[image edit](https://fal.ai/models/fal-ai/nano-banana-pro/edit/api),
[video](https://fal.ai/models/fal-ai/kling-video/v2.6/pro/text-to-video/api),
[reference video](https://fal.ai/models/fal-ai/kling-video/v2.6/pro/image-to-video/api),
[speech](https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3/api),
[queue](https://fal.ai/docs/documentation/model-apis/inference/queue).

The app generates up to six scenes, normalizes their size and joins them with
ffmpeg. Optional narration is a separate request. The last frame is held when
speech outlasts the scenes, with a three-minute narration limit. Keep spoken copy
short; for longer episodes use a dedicated editing workflow. These are narrated
scene videos, without automatic presenter lip synchronization, subtitles or music.
Script tables are not automatically interpreted into final shot directions:
review and enter each scene and the spoken text separately.

## Railway and data

- Keep the current Python Bookworm Docker image, Postgres and `/data` volume.
  ffmpeg and ffprobe are already installed by the Dockerfile.
- Keep **one replica and one Uvicorn worker**. Text streams and media processing
  require a queue/lease design before scaling to multiple processes.
- This release adds tables via the existing `create_all` startup. It does not
  remove columns or rewrite existing outputs. Back up the database before rollout.
- Set `STORAGE_DIR=/data/storage`. Generated files are copied from fal to the
  volume and served through authenticated, brand-scoped routes. Monitor free space;
  generated scenes and final files are retained, and no automatic retention policy
  deletes them. fal output links can be public/temporary; do not rely on those links
  for long-term storage.
- When `CONNECTION_ENCRYPTION_KEY` is unset, a Fernet key is generated at
  `STORAGE_DIR/.integration.key`. Back it up with the database and volume. An
  alternative is a securely managed Fernet key in the Railway variable. Changing
  that encryption key without migrating the stored credential requires entering
  the fal key again.
- Only selected prompts, voice text, reference image, brand name/description and
  visual guidance go to fal. Full financial data and the complete Brand Brain do
  not go to the media provider.

## Reliability and cost controls

`PRODUCTION_DAILY_LIMIT=30` and `PRODUCTION_MAX_ACTIVE=2` apply per client across
its brands; they are **job count limits**, not dollar budgets. A video job may
contain several billable scene requests. `MAX_CONCURRENT_RUNS=3` caps active text
jobs per client and process concurrency. These settings are in `.env.example`.

Repeated client requests use an idempotency key. Each accepted provider request
ID is saved before polling. A crash during submission with an unknown outcome
sets `needs_attention`; it does not automatically make a second paid request.
Review the fal dashboard before creating a replacement. Poll/download network
timeouts are retried, whereas provider refusals become visible errors.
Cancellation stops subsequent stages and requests provider cancellation; work
already started may still be charged. An assembly failure after all provider
files are saved can be retried without paid generation.

The usage view records text runs, completed field assistance/bootstrap calls and
media submissions. Text costs are estimates based on reported tokens. fal costs
are shown as unknown and must be read from the provider invoice. Interrupted
streams can lack final usage, and a timed-out submission may have incurred a
provider charge even without a confirmed request ID. This ledger is not yet a
complete subscription billing system. Bootstrap calls before brand creation have
no brand and are retained in the ledger but not the per-brand screen.

## Review and access

- Editors can generate, edit and request reviews; viewers can read and comment.
- Client admins (and the global owner) can approve strategy into Brand Brain.
- Manual edits and regenerated sections become drafts. Approved core stays intact
  until the updated full output is approved. Existing core entries are preserved.
- Output edits carry a version: stale saves return a conflict instead of silently
  overwriting another editor. Historical output copies can be restored as drafts.
- Campaign launch saves the brief first; linking results to a campaign is manual.
- Module form drafts are scoped to the signed-in user, brand and module in tab
  session storage. Files must be selected again; logout clears tab drafts.

## Validation

```sh
pip install -r backend/requirements-dev.txt
pytest -q
cd frontend
npm ci --no-audit --no-fund
npm run build
```

GitHub Actions installs ffmpeg and runs both API/worker tests and an actual
multi-scene/audio assembly check. Provider calls in automated tests use fixtures:
passing tests verifies protocol handling and recovery, not provider access or
creative output quality. Paid end-to-end tests require the owner's funded key.

Windows sandbox note: if esbuild cannot load the Vite config because it attempts
to inspect a restricted ancestor directory, run lint followed by
`node node_modules/vite/bin/vite.js build --configLoader runner`. The regular
Docker/Linux build continues to use `npm run build`.

# AGENTS.md

nanoMuse is an open-source personal agent for every device a person owns: a phone app (Android and iOS, built on OpenMinis), a desktop app (a DeepSeek Harness plugin in an Electron shell), a Python runtime for the hands, a web console, and the relay that signs people in and lets their devices talk. Everything is GPL-3.0-or-later; read [CONTRIBUTING.md](CONTRIBUTING.md) first and [docs/architecture.md](docs/architecture.md) before touching the runtime.

## Repository layout

```
nanomuse/               Python runtime: agent loop, Sentinel, tools, hands (phone/computer operators), server for the web app
cloud/                  nanoMuse Cloud, the relay: FastAPI + SQLite; sign-in, models, hub, conversation sync, console at /app
web/                    the web console (Vite + React); `npm run build` writes nanomuse/server/static/, which is committed
harness/dsh-nanomuse/   the desktop app proper: a DeepSeek Harness plugin (TypeScript, React client, i18n in src/client/locales.ts)
harness/desktop/        the Electron shell around dsh + the plugin; ships the Python runtime for the hands
android/                OpenMinis 1.13 subtree (GPL-3.0); do not restructure
android/src/android     the Android app; ours lives in io.github.nanomuse.* and res/values*/nm_strings.xml
android/src/ios         the iOS app; ours lives in NanoMuse/ (Swift), strings in Localizable.xcstrings
demo/                   the showcase (recorded traces, pages under site/)
docs/                   user and contributor docs; the VitePress site in website/ projects this directory
scripts/                release, rebrand, icon and catalogue generators; self-host.sh
tests/                  pytest for the Python runtime (MockLLM only, no network)
website/                VitePress config for the docs site (srcDir ../docs)
```

## Commands

Run the checks for the area you changed. CI runs the same lines on Node 22; the Python matrix also runs on macOS and Windows runners.

```sh
# Python runtime (nanomuse/, tests/, scripts/)
uv venv && uv pip install -e ".[dev]"
ruff check nanomuse tests scripts && ruff format --check nanomuse tests scripts
mypy
python -m pytest -q -m "not live"

# Relay (cloud/)
cd cloud && pip install -e ".[dev]" && ruff check . && pytest

# Web console (web/); the built app under nanomuse/server/static/ is committed; rebuild and commit it
cd web && npm ci && npm run check && npm run build

# Desktop plugin (harness/dsh-nanomuse/)
cd harness/dsh-nanomuse && pnpm install --frozen-lockfile && pnpm build && pnpm typecheck && pnpm test
# from the repository root (the scripts live in scripts/, not in the plugin)
node scripts/connectors-json.mjs --check        # the phones' copies of the connectors catalogue are current
node scripts/providers-json.mjs --check         # the clients' copies of the provider catalogue are current

# Desktop shell (harness/desktop/)
cd harness/desktop && npm ci && npm run typecheck && npm test

# Android (android/src/android); JDK 21, NDK r27c; natives first: bash scripts/android/build-natives.sh
cd android/src/android && ./gradlew :app:assembleDebug --console=plain --no-daemon
./gradlew :app:testDebugUnitTest --tests 'io.github.nanomuse.*' --console=plain --no-daemon # our unit tests; CI runs them too

# iOS (android/src/ios); macOS only; the device build must finish with zero warnings in NanoMuse/
xcodebuild build -project Minis.xcodeproj -scheme Minis -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO

# Docs site (website/)
cd website && npm ci && npm run docs:build       # also the dead-link check; `npm run docs:dev` serves it
```

## Conventions

- **Two trees, two sets of rules.** `android/` is an upstream subtree we must keep pullable: new code in new files (`io.github.nanomuse.*`, `NanoMuse/*.swift`); an edit inside an upstream file carries a `// nanoMuse:` comment, one change per spot; never rename the Kotlin package, the Gradle namespace or the sandbox paths. Rebranding is `scripts/rebrand.py` (plus `gen-android-icons.py`, `gen-ios-icons.py`), idempotent; fix the script, not the miss. Details in [CONTRIBUTING.md](CONTRIBUTING.md).
- **Our Android strings** live in `res/values*/nm_strings.xml` with `nm_` keys; upstream's `strings.xml` stays theirs.
- **Generated files are regenerated, not edited.** The connectors catalogue is `harness/dsh-nanomuse/src/connectors-catalogue.ts`; `node scripts/connectors-json.mjs` writes the phones' `connectors.json` and CI runs `--check`. The own-key provider catalogue is `nanomuse/llm/providers.json` (ids, base URLs, key pages, capabilities, defaults, verified against the vendors' docs); `node scripts/providers-json.mjs` writes the desktop's and the phones' `providers.json` and CI runs `--check`. The ideas lists `ideas.en.json`/`ideas.zh.json` under `harness/dsh-nanomuse/assets/` must be byte-identical to the Android app's copies under `app/src/main/assets/nanomuse/` (`tests/fences.test.mjs` checks). The web build writes `nanomuse/server/static/`; commit it with the change.
- **Lock files resolve against the public registry only.** After any `npm install`, every `resolved` URL in the lock file must point at `https://registry.npmjs.org/`; CI greps for anything else. A private mirror's host never lands in the repository.
- **Every string in every locale.** A user-visible string is added in English first, then 简体中文, then every other locale the file already has: `nm_strings.xml` per `values-*`, `Localizable.xcstrings`, `locales.ts` (`en` and `zh`), the relay's console and e-mail templates. Never assume a +86 number, a Chinese app or Beijing time; SMS codes reach mainland-China numbers only, so a sign-in screen says so and points to e-mail.
- **Voice.** Plain, specific, human sentences; say what a thing does. No marketing words, no exclamation marks, no superlatives. Chinese copy follows the same rule. Never copy Meta's UI text verbatim; describe the same behaviour in our words.
- **Docs accompany code.** A change that alters what a person sees or does updates the page under `docs/` in the same change, and adds a line under *Unreleased* in `CHANGELOG.md` (past tense, concrete, user-facing).
- **No version bumps outside release commits.** `pyproject.toml`, `cloud/pyproject.toml`, the two `harness/*/package.json`, the Android `versionName`/`versionCode` and the iOS `MARKETING_VERSION` move together in the release commit only.
- **Commits** follow Conventional Commits (`feat(android): …`, `fix(relay): …`), carry a DCO sign-off (`git commit -s`), and are merged by rebase or merge commit, never squash.
- **No secrets, ever.** No keys, tokens, phone numbers, e-mail addresses or private hosts in code, docs, tests or fixtures. `config/config.toml` and `cloud/.env` are git-ignored; secrets reach the model as `{{vault:NAME}}` and nothing else.
- **Everything that acts goes through the Sentinel** with an honest `risk`; tests use `MockLLM`; Ruff line length 100; type hints everywhere.

## Wire contracts

The three protocols are documented and versioned; change the doc in the same change as the code, and keep old clients working for one release.

- **Hub frames**: devices of one account talking through the relay (`/v1/hub`): [docs/hub.md](docs/hub.md); implementations in `nanomuse/hub/`, `harness/dsh-nanomuse/src/hub.ts`, the phones' `Hub*` files.
- **Conversation sync and accounts**: [docs/cloud.md](docs/cloud.md); the relay's own README is [cloud/README.md](cloud/README.md).
- **The operator**: how the hands see a screen and act on it, phone and computer alike: [docs/gui.md](docs/gui.md).

## Platform notes

- **iOS** targets iOS 16; use the `.nmOnChange(of:)` helper, not the two-parameter `onChange` (iOS 17+). The device build treats warnings in `NanoMuse/` as failures. Xcode and TestFlight details: [docs/ios.md](docs/ios.md).
- **Android** builds with JDK 21, SDK CMake 3.22.1, NDK r27c, Go 1.25+; phone features are tested on real arm64 hardware (the emulator cannot run the APK).
- **Desktop** is a dsh plugin: profile overlays in `cordis.patch.yml`, the relay URL in the plugin's `config.baseURL`; [docs/desktop.md](docs/desktop.md). The Electron shell and the plugin carry the same version.
- **CI** uses Node 22 for every JavaScript job; keep `engines` and lock files compatible with it even when you develop on a newer Node.

## Writing a release

One branch and one pull request per version; `scripts/release-bump.sh` moves the version files, `scripts/rebrand.py` writes the phones' versions, `scripts/release-docs.py` opens the `CHANGELOG.md` block and moves the READMEs' download links, and `scripts/release-apk.sh <version>` builds and publishes (the tag `v*` starts the desktop, harness and Docker workflows). The notes are `docs/releases/v<version>.md` in the shape of [docs/release-notes-template.md](docs/release-notes-template.md): a short story, *Highlights*, *Upgrade Notes*, *Community*, English first and the same in Chinese in a collapsed block. Move the *Unreleased* bullets of `CHANGELOG.md` under the new version in the same commit as the version bump. The maintainers' recipe is in [CONTRIBUTING.md](CONTRIBUTING.md#releasing-maintainers).

## Editing these instructions

`CLAUDE.md` is a symlink to this file; edit `AGENTS.md`. Keep it under 150 lines: one fact, one home; link the page that owns the detail rather than restating it.

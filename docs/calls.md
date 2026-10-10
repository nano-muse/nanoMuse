# Calls (removed in 0.1.22)

Versions 0.1.20 and 0.1.21 could place a voice or video call with the agent
through Qwen Omni's real-time socket. It was expensive to run for everyone and
out of the project's way (a personal agent that *does things*), so 0.1.22 took
it out of every app and the relay. Older ledger rows of kind `realtime` and
messages marked "said on a call" still display.

What remains is voice **input**: on the phone the microphone button in the
composer (the system's or a provider's speech recognition, as in OpenMinis);
in nanoMuse Web and the desktop app a microphone button next to *Send* that
uses the browser's own speech recognition where it exists (Chrome, Edge,
Safari); nothing is sent anywhere by nanoMuse, no model is involved, and the
words land in the box for you to send.

The design and the code of the calls live in the history of the repository
(`git show v0.1.21:docs/calls.md`).

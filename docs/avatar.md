# The avatar studio

The agent's face is the bundled dragon until you ask for another; inspiration cards do
not change that default. On the phone since
0.1.20 and, from 0.1.23, on the web app and the desktop through the runtime
(`nanomuse/avatar/studio.py`), the studio draws one from a description, in the chat:

1. **Ask.** In the chat: 「换个形象：一只戴圆眼镜的橘猫」, "new avatar: a robot owl",
   "change your avatar to a small fox with a scarf". Or on the studio screen (the pen on
   the avatar in the profile sheet → *Avatar studio…*, or the studio tile in *Settings*), the
   phone's page: the face at the top with what it is, a description, the seven style chips,
   *Draw four*, and the rest of this list without a card in the chat (the progress comes over
   the socket as `{"kind": "studio", "current"}`). The agent is not run for it.
2. **Your image provider.** Add an image provider and API key under *Models* first.
   nanoMuse Cloud no longer pays for image or video generation. The studio keeps the
   generated files on your device and uses the provider you selected.
   Four illustrated inspiration cards sit above the description on Android, iPhone, web
   and desktop. Tapping one fills its description and style; it does not replace the face
   until you ask your own provider to draw and then choose a result. The examples are
   *Moss Courier*, *Tide Tinker*, *Dusk Moth* and *Copper Acorn*. Their five-state image
   sets are under `assets/avatar-presets/`; generation details and
   the non-sensitive prompts are in `source.json` there. Names, descriptions and style hints
   follow the app language; the stable preset ids are not user-facing copy.
3. **Four to choose from.** The same subject four times (classic colouring, lighter, darker
   with a small accessory, a playful take), in the studio's 3D toy style, full body on white. Tap
   one, or say which (「第二个」, "the first one", "top right"); *Redraw* for four more.
4. **The poses.** The pick is the idle still; four edits of it are the other moods (working
   with headphones at a laptop, waiting with a crystal ball, happy hugging a star, sorry with a
   sweat drop), the set the dragon has. They land in the workspace under
   `avatar/<face>/<mood>.webp`; the profile's `avatar` becomes the face id; every app on the
   account shows it (through `/api/files/avatar/<face>/<mood>.webp`). A pose that could not
   be drawn shows the idle picture instead.

The inspiration assets are labelled as AI-generated in their canonical `source.json`. They
were made through authenticated, metered Bailian model-inference HTTP APIs, not Model Studio's
experience UI: `qwen-image-3.0-pro` used the native synchronous multimodal endpoint for 20
pictures. The manifest records the endpoint type, maintainer attestation, prompts, per-file
SHA-256 and official API and terms links, but no credential, account, private host, request id
or signed result URL. The manifest also records the terms distinction and the GPL contribution
of any rights held by the API caller; it is factual project documentation, not legal advice.

Where the pictures come from: the chat model's host and key. The relay speaks the OpenAI
images API (`/v1/images/generations`, `/v1/images/edits`), as does any OpenAI-compatible
provider that draws; Alibaba Cloud Model Studio's own host has neither and is called on its
native multimodal endpoint with the same key (qwen-image-3.0 by default). Which model draws
is the `[image]` block in `config.toml` (`[llm] image_model` still works), the *Making
pictures* row on *Connections* in the web console, or *Settings → Models* on the phones and
the desktop; empty means *Automatic*: the chat model's provider when it draws (qwen-image-3.0
on Model Studio), else another image provider configured by the person, else none, and then the chat
says so plainly instead of trying.

On Android, a Google Gemini provider added with an API key can supply the image model
for drawing and editing the avatar. Choose its image-capable model in *Settings → Models*;
image model IDs containing `nano-banana` are recognised too. The app uses Gemini's native
`generateContent` endpoint with text and image output, and sends the selected picture when
creating its poses. Imagen models are excluded from this native Gemini list because they
use a different API. OpenAI-compatible providers keep their existing image route.

Once the stills are on, the studio makes the four short clips the phone's does (idle,
working, waiting, happy; the same fixed motions) from them, when the endpoint has a video
model from a provider configured by the person, such as Wan on Model Studio, through the asynchronous
video API (an upload, a task, polling, the MP4), the `[video]` slot (or the older `[llm] video_model`,
[configuration.md](configuration.md#image-and-video)) overriding the choice
and `[llm] video_base_url` naming the host of that API when it is not the chat model's (a
relaying host such as the showcase gateway sets it for its runtimes). They land in `avatar/<face>/<mood>.mp4`; the card shows the stage `animating` while they
come, the cost card counts them, and a clip that fails leaves its still. An OpenAI-compatible
provider without a video API gives stills only. The web and the desktop play the clips at
44 px and above (the dragon's own four ship with the web app) and show stills below that,
in lists and pickers, under `prefers-reduced-motion`, or when a clip is missing.

`GET /api/avatar` says whether a face can be drawn here (and with which clip model), which
session is under way, and which face the profile wears and what it is: its description,
style and model, kept in `avatar/<face>/face.json` when the poses land; `POST
/api/avatar/begin|start|choose|cancel` drive a session (the chat card and the studio screen
use them), `POST /api/avatar/moods` draws the poses and clips of the worn face again. Candidates
of finished sessions are cleared after a day; faces stay in the workspace as long as the
profile, or you, want them.

With a nanoMuse Cloud account the face follows you to every device ([docs/cloud.md](cloud.md)):
the stills go to the relay once, the other devices wear them from `avatar/sync-<hash>/`
with the description and style in their `face.json`, and a device keeps the face it drew,
clips and all, when the account's pictures are the ones it already wears.

## Your own clip

A short video of your own can take the place of the clips. On the phone, pick one under the
pen on the face in the profile (*Your own clip…*) or in the *Your own clip* section of the
avatar studio; on the desktop, in the avatar studio or the profile drawer. The clip plays
muted in a loop wherever the face moves: for the mood at rest, and for every other mood too,
since there is only the one clip. Where a still is shown (under the clip until its first frame
is on screen, in the share cards, in the tiles) the stills of a studio face keep their place,
and with no studio face the clip's first frame is the still. Before anything changes, a
preview plays the clip in the face's own round frame, with *Use* and *Cancel*; *Default face*
removes the clip, and the studio face or the dragon shows again.

The limits, the same on every device ([every-device.md](every-device.md)): MP4 or MOV, at most
15 seconds and 30 MB, with H.264 video; HEVC too where the device can play it (iOS always; the
desktop where the system has the decoder, and its preview refuses a clip it cannot play; Android
takes H.264 only today). A longer or larger clip, or another format, is refused with a sentence
that states the limits; nothing is trimmed or re-encoded, and the sound is never played.

The clip stays on the device that chose it. It is not uploaded to nanoMuse Cloud and does not
sync to your other devices, unlike the stills of a studio face; each device chooses its own.
On Android it lives under `minis-global/nanomuse/avatar/own-clip.mp4` with its first frame
beside it as `own-clip.png`, filed with the signed-in account's other files; on iOS under the
app's `Application Support/nanomuse/avatar/own-clip.mp4`; on the desktop under
`$DSH_HOME/nanomuse/avatar/own-clip.mp4`. It survives a new studio face and a reset to the
built-in one.

On Android that folder is inside the app's own storage, which no file manager or shell can
open, so the workbench's menu has *Save to gallery*: it copies the base picture, the mood stills,
the four candidates of the last generation, the animated moods and your own clips to
`Pictures/nanoMuse/avatar` and `Movies/nanoMuse/avatar`, each batch named by the minute it
was saved, and says how many pictures and clips landed. Nothing goes anywhere but the gallery
of the same phone; it is the way to keep a face or a clip before clearing the app's data or
moving to a new phone. ([#664](https://github.com/nano-muse/nanoMuse/issues/664))

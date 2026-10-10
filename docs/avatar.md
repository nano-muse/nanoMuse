# The avatar studio

The agent's face is the bundled dragon until you ask for another. On the phone since
0.1.20 and, from 0.1.23, on the web app and the desktop through the runtime
(`nanomuse/avatar/studio.py`), the studio draws one from a description, in the chat:

1. **Ask.** In the chat: 「换个形象：一只戴圆眼镜的橘猫」, "new avatar: a robot owl",
   "change your avatar to a small fox with a scarf". Or on the studio screen (the pen on
   the avatar in the profile sheet → *Avatar studio…*, or the studio tile in *Settings*), the
   phone's page: the face at the top with what it is, a description, the seven style chips,
   *Draw four*, and the rest of this list without a card in the chat (the progress comes over
   the socket as `{"kind": "studio", "current"}`). The agent is not run for it.
2. **The cost first.** A card says what it will take: with the account's model (nanoMuse
   Cloud), the relay's figure (`GET /v1/estimate`) next to what is left in your allowance
   (about ¥1.5 for the eight pictures at qwen-image-3.0's price); with a key of your own, the
   count, at your provider's prices. *Draw* or *Not now*.
3. **Four to choose from.** The same subject four times (classic colouring, lighter, darker
   with a small accessory, a playful take), Muse's vinyl-toy style, full body on white. Tap
   one, or say which (「第二个」, "the first one", "top right"); *Redraw* for four more.
4. **The poses.** The pick is the idle still; four edits of it are the other moods (working
   with headphones at a laptop, waiting with a crystal ball, happy hugging a star, sorry with a
   sweat drop), the set the dragon has. They land in the workspace under
   `avatar/<face>/<mood>.webp`; the profile's `avatar` becomes the face id; every app on the
   account shows it (through `/api/files/avatar/<face>/<mood>.webp`). A pose that could not
   be drawn shows the idle picture instead.

Where the pictures come from: the chat model's host and key. The relay speaks the OpenAI
images API (`/v1/images/generations`, `/v1/images/edits`), as does any OpenAI-compatible
provider that draws; Alibaba Cloud Model Studio's own host has neither and is called on its
native multimodal endpoint with the same key (qwen-image-3.0 by default). Which model draws
is the `[image]` block in `config.toml` (`[llm] image_model` still works), the *Making
pictures* row on *Connections* in the web console, or *Settings → Models* on the phones and
the desktop; empty means *Automatic*: the chat model's provider when it draws (qwen-image-3.0
on Model Studio), else the relay's image model for the account, else none, and then the chat
says so plainly instead of trying.

Once the stills are on, the studio makes the four short clips the phone's does (idle,
working, waiting, happy; the same fixed motions) from them, when the endpoint has a video
model: the relay's (`wan2.2-i2v-flash`) or Wan on Model Studio, through the asynchronous
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

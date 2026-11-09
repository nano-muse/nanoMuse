# Migrating from another assistant

You can bring selected memories and text documents into the desktop app, then reconnect
the services you use. nanoMuse does not currently import a Muse export ZIP as a complete
account, restore its conversations, or convert its connectors and tags automatically.
Keep the original export while checking what has moved.

## What can be moved

| Exported material | Where it goes in nanoMuse | What is preserved |
| --- | --- | --- |
| Short facts and preferences | **Soul & memory → Import memory** | Selected text, one memory per line |
| Notes and conversation transcripts | **Library → Import Markdown files…** | Text documents, not resumable chat sessions |
| Connector definitions and scripts | Configure each service under **Settings → Connectors** | Only the capabilities of the connector or MCP server you configure |
| Tags or categories | Keep them in document headings or text when present in the export | Text only, not imported tag metadata |
| Conversation manifests and resources | Keep them with the original archive | No automatic reconstruction of turns, attachments or session IDs |

An export can only transfer what it contains. If tags or connector files are missing,
nanoMuse cannot recover them from a transcript or a manifest. Check your own export;
different export paths may include different material.

## Import selected memories

1. Open your agent's profile, choose **Soul & memory**, then **Import memory**.
   The same action is available under **Settings → Data controls**.
2. Paste facts you want the agent to remember, one per line. Review them first;
   keep long notes and transcripts in the Library.
3. Import a small batch, check the saved lines, then continue with the rest.

An import accepts at most **200 nonempty lines**, each at most **400 characters** after
whitespace and leading list markers are normalized. Desktop memory holds **400 entries
in total**, including existing memories. Lines differing only in letter case or extra
whitespace count as duplicates and are not added again. Punctuation is preserved when
comparing lines, so negative numbers and decimals remain distinct.

If any limit is exceeded, the current implementation rejects the **whole batch** and
keeps the existing memory unchanged. It does not shorten imported lines or remove old
memories to make room. Split a large batch, shorten individual facts yourself, or review
unneeded memories before trying again. Older builds can truncate lines or discard old
entries, so use a build containing the import-limit fix before moving your full set.

If the pasted text is too large to send, the app asks you to send a smaller amount in
your selected language. Split it into smaller batches and retry.

If the app cannot write the imported memories to disk, it shows an error instead of
success. The new lines may still be visible in memory. Check disk space and write
access, then retry the same import before closing the app; a retry saves the lines
even when they are already listed as duplicates.

Desktop memories contain text and a source marker, such as **Imported**. They do not
have the Python runtime's `category` field. The runtime's
[`nanomuse memory add --category …`](cli.md#memory) writes to its own memory store;
it does not add categories to desktop memories or import Muse tags. A prefix such as
`[Project]` in a desktop memory is ordinary text and counts toward the length limit.

## Keep conversations as reference documents

In the **Library**, open the menu beside **Create…** and choose **Import Markdown
files…**. It accepts `.md`, `.markdown` and `.txt` files up to **2 MB each**. Split larger
transcripts into readable files first. Files are copied into the Library; a number is
added to the filename when a name is already taken.

This makes a transcript available as a document. It does not recreate the chat list,
roles, timestamps, tool calls, attachments or a conversation that can be resumed. Keep
images and other resources with the original export and check the references in any
documents you convert. Importing a text file does not import its linked resources.

Do not write foreign transcripts into the harness's session files or manufacture relay
sync records. Those formats belong to nanoMuse's session and sync lifecycle and are not
an external conversation import API.

## Reconfigure connectors

For each service you need, list the actions it provided, its authentication method and
any local files it used. Then check **Settings → Connectors** for a supported connection.
For a custom connection, configure a server that actually implements MCP, using its
documented transport and authentication. See the
[desktop connector settings](desktop-muse.md#settings) and, for the Python runtime,
[MCP server configuration](configuration.md#mcp-servers).

Files named `connector.yaml` or `CONNECTOR.md` can help you understand the old setup,
but nanoMuse has no importer for that connector format. A Python script that calls a
service's API is not automatically an MCP server. It needs a reviewed adapter that
implements MCP before an MCP client can discover and call its tools. Copying the file
or pointing a server command at an ordinary client script does not supply that adapter.

Enter credentials through the supported connector setup, and keep runtime secrets in
the vault. Select the tools and permissions you need, then verify a read-only operation
before using the connection for changes. Bring over your own preferences as selected
facts; do not copy another product's system prompt or assume its instructions configure
nanoMuse's tools and permissions.

## Check the result

Compare the imported memory count with the number of new, distinct facts you expected.
Open a sample of the documents and check their text and resource references. Confirm
each reconfigured connection exposes the intended tools. Keep the original archive
until these checks pass; it remains the source for history and metadata that have no
import path yet.

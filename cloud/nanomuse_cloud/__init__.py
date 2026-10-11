"""nanoMuse Cloud — the optional relay behind "start now".

A phone number or an e-mail address, a six-digit code, and the app gets a key
that works out of the box: the relay speaks the OpenAI API to the app and
forwards to the model provider with the project's own key, counting tokens
against the account's grant. Nothing about the conversation is stored — only
the token counts. See README.md in this folder.
"""

__version__ = "0.24.1"

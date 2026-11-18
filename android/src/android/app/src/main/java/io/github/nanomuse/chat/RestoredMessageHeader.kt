package io.github.nanomuse.chat

/** Metadata needed to restore a checkpoint divider without retaining raw JSON bodies. */
data class RestoredMessageHeader(val id: String, val createdAt: Long)

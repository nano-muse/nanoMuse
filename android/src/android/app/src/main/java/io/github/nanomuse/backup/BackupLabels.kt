package io.github.nanomuse.backup

import com.openminis.app.R
import com.openminis.app.backup.BackupCategory

/** One category vocabulary for the page, history and resumable exporter. */
object BackupLabels {
    fun categoryNameRes(category: BackupCategory): Int = when (category) {
        BackupCategory.CHATS -> R.string.backup_category_chats
        BackupCategory.SHARED_FILES -> R.string.backup_category_shared_files
        BackupCategory.SKILLS -> R.string.backup_category_skills
        BackupCategory.MEMORY -> R.string.backup_category_memory
        BackupCategory.PROVIDERS -> R.string.backup_category_providers
        BackupCategory.MCP_SERVERS -> R.string.backup_category_mcp
        BackupCategory.ENVIRONMENT_VARIABLES -> R.string.backup_category_env_vars
        BackupCategory.VOICE_CORRECTIONS -> R.string.backup_category_voice
    }
}

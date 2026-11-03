package io.github.nanomuse.backup

import android.content.Context
import android.content.SharedPreferences
import com.openminis.app.data.db.ProviderDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Fixed, app-owned destinations. Neither the package nor a journal can choose a pathname. */
object AndroidRestoreRecovery {
    private val lock = Any()
    private fun journal(context: Context): RestoreRecovery {
        val files = context.filesDir
        fun file(path: String) = FileRecoveryTarget(File(files, path), files)
        fun prefs(name: String) = PreferencesRecoveryTarget(context.getSharedPreferences(name, Context.MODE_PRIVATE))
        return RestoreRecovery(File(files, "restore-recovery"), mapOf(
            "shared_files" to file("minis-global/shared"),
            "skills" to file("minis-global/skills"),
            "memory" to file("minis-global/memory"),
            "mcp_servers" to file("minis-global/mcp-servers"),
            "providers" to CompositeRecoveryTarget(listOf(
                ProviderRecoveryTarget(context), prefs("provider_config"), prefs("provider_secrets"),
            )),
            "environment_variables" to CompositeRecoveryTarget(listOf(
                file("env-vars.json"), prefs("env_var_values"),
            )),
        ))
    }

    fun recover(context: Context): List<String> = synchronized(lock) {
        val prefs = context.getSharedPreferences("restore_recovery_notice", Context.MODE_PRIVATE)
        try {
            val result = journal(context).recover()
            if (result.isNotEmpty()) prefs.edit().putString("status", "recovered").commit()
            result
        } catch (error: Exception) {
            prefs.edit().putString("status", "failed").commit()
            throw error
        }
    }

    fun showNotice(context: Context) {
        val prefs = context.getSharedPreferences("restore_recovery_notice", Context.MODE_PRIVATE)
        val status = prefs.getString("status", null) ?: return
        prefs.edit().remove("status").apply()
        val message = if (status == "recovered") com.openminis.app.R.string.nm_restore_recovered
            else com.openminis.app.R.string.nm_restore_recovery_failed
        android.widget.Toast.makeText(context, message, android.widget.Toast.LENGTH_LONG).show()
    }
    fun begin(context: Context, category: String): Boolean = synchronized(lock) {
        if (category == "chats" || category == "voice_corrections") return false
        journal(context).begin(category)
        true
    }
    fun complete(context: Context, category: String) = synchronized(lock) { journal(context).complete(category) }
}

private class CompositeRecoveryTarget(private val targets: List<RecoveryTarget>) : RecoveryTarget {
    override fun snapshot(destination: File) {
        targets.forEachIndexed { index, target ->
            target.snapshot(File(destination, index.toString()).apply { mkdirs() })
        }
    }
    override fun restore(snapshot: File) {
        targets.forEachIndexed { index, target -> target.restore(File(snapshot, index.toString())) }
    }
}

private class PreferencesRecoveryTarget(private val prefs: SharedPreferences) : RecoveryTarget {
    override fun snapshot(destination: File) {
        val json = JSONObject()
        for ((key, value) in prefs.all) {
            val type = when (value) {
                is String -> "string"
                is Boolean -> "boolean"
                is Int -> "int"
                is Long -> "long"
                is Float -> "float"
                is Set<*> -> "set"
                else -> error("Unsupported preference type")
            }
            json.put(key, JSONObject().put("type", type).put("value", if (value is Set<*>) JSONArray(value.toList()) else value))
        }
        durableWrite(File(destination, "preferences.json"), json.toString().toByteArray())
    }
    override fun restore(snapshot: File) {
        val json = JSONObject(File(snapshot, "preferences.json").readText())
        val editor = prefs.edit().clear()
        for (key in json.keys()) {
            val item = json.getJSONObject(key)
            when (item.getString("type")) {
                "string" -> editor.putString(key, item.getString("value"))
                "boolean" -> editor.putBoolean(key, item.getBoolean("value"))
                "int" -> editor.putInt(key, item.getInt("value"))
                "long" -> editor.putLong(key, item.getLong("value"))
                "float" -> editor.putFloat(key, item.getDouble("value").toFloat())
                "set" -> editor.putStringSet(key, item.getJSONArray("value").let { a -> (0 until a.length()).map { a.getString(it) }.toSet() })
                else -> error("Invalid preference snapshot")
            }
        }
        check(editor.commit()) { "Cannot recover preferences" }
    }
}

/** Row snapshots through SQLite, including WAL contents; never copies an open DB file. */
private class ProviderRecoveryTarget(private val context: Context) : RecoveryTarget {
    private val tables = listOf("provider_agent_loop_ids", "provider_model_groups", "provider_model_entries",
        "provider_thinking_rules", "provider_instances", "provider_config_meta")
    private val database get() = ProviderDatabase.getInstance(context).openHelper.writableDatabase

    override fun snapshot(destination: File) {
        val db = database
        val result = JSONObject()
        db.beginTransaction()
        try {
            for (table in tables) {
                db.query("SELECT * FROM $table").use { cursor ->
                    val rows = JSONArray()
                    while (cursor.moveToNext()) {
                        val row = JSONArray()
                        for (i in 0 until cursor.columnCount) row.put(when (cursor.getType(i)) {
                            android.database.Cursor.FIELD_TYPE_NULL -> JSONObject.NULL
                            android.database.Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(i)
                            android.database.Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(i)
                            android.database.Cursor.FIELD_TYPE_STRING -> cursor.getString(i)
                            else -> error("Unsupported provider column")
                        })
                        rows.put(row)
                    }
                    result.put(table, JSONObject().put("columns", JSONArray(cursor.columnNames.toList())).put("rows", rows))
                }
            }
            durableWrite(File(destination, "rows.json"), result.toString().toByteArray())
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    override fun restore(snapshot: File) {
        val source = JSONObject(File(snapshot, "rows.json").readText())
        val db = database
        db.beginTransaction()
        try {
            for (table in tables) db.execSQL("DELETE FROM $table")
            for (table in tables.asReversed()) {
                val data = source.getJSONObject(table)
                val columns = data.getJSONArray("columns")
                val names = (0 until columns.length()).map { columns.getString(it) }
                val actual = db.query("SELECT * FROM $table LIMIT 0").use { it.columnNames.toSet() }
                check(names.toSet() == actual) { "Provider schema changed; recovery retained" }
                val rows = data.getJSONArray("rows")
                val sql = "INSERT INTO $table (${names.joinToString(",") { "`$it`" }}) VALUES (${names.joinToString(",") { "?" }})"
                for (i in 0 until rows.length()) {
                    val row = rows.getJSONArray(i)
                    db.execSQL(sql, Array<Any?>(row.length()) { index -> row.opt(index).takeUnless { it == JSONObject.NULL } })
                }
            }
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
}

package io.github.nanomuse.ui.models

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import io.github.nanomuse.models.CodexCatalogueState

@Composable
fun CodexCatalogueNotice(instance: ProviderInstance, state: CodexCatalogueState, modifier: Modifier = Modifier) {
    if (instance.providerType != ProviderType.openAI || instance.credentialType != ProviderCredential.oauth) return
    val fallback by remember(instance.id, state) { state.fallback(instance.id) }.collectAsState(false)
    if (fallback) Text(
        stringResource(R.string.nm_codex_catalogue_fallback),
        modifier = modifier.padding(vertical = 4.dp),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

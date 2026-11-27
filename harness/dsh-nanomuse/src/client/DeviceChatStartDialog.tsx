import { createElement as h, type ReactNode } from 'react'
import { Button } from '@deepseek-ai/dsh-client-ui-primitives'
import type { Translate } from './api.ts'
import { canStartBoundDeviceChat, deviceChatLabel } from '../device-chat.ts'
import type { LiveDevice } from './live.ts'

export function DeviceChatStartDialog({
  t, devices, busy, onLocal, onDevice, onDismiss,
}: {
  t: Translate
  devices: LiveDevice[]
  busy: boolean
  onLocal(): void
  onDevice(device: LiveDevice): void
  onDismiss(): void
}): ReactNode {
  return h('div', { role: 'dialog', 'aria-modal': true, 'aria-labelledby': 'nm-device-chat-title', className: 'nm-device-chat-picker' },
    h('div', { className: 'nm-device-chat-picker-card' },
      h('h2', { id: 'nm-device-chat-title' }, t('deviceChatDestination')),
      h(Button, { disabled: busy, onClick: onLocal }, t('deviceChatHere')),
      ...devices.filter((device) => device.kind !== 'web').map((device) =>
        h(Button, {
          key: device.id,
          disabled: busy,
          'aria-label': `${deviceChatLabel(device)} · ${availability(t, device)}`,
          onClick: () => onDevice(device),
        }, `${deviceChatLabel(device)} · ${availability(t, device)}`)),
      h(Button, { variant: 'outline', disabled: busy, onClick: onDismiss }, t('cancel'))))
}

function availability(t: Translate, device: LiveDevice): string {
  if (!device.online) return t('deviceOffline')
  return canStartBoundDeviceChat(device) ? t('deviceOnline') : t('deviceNotReachable')
}

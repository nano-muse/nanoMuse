import type { LiveDevice } from './client/live.ts'

export function canStartBoundDeviceChat(device: Pick<LiveDevice, 'online' | 'actions'>): boolean {
  return device.online && device.actions.includes('task.status')
}

export function deviceChatLabel(device: Pick<LiveDevice, 'id' | 'name' | 'kind'>): string {
  return `${device.kind === 'phone' ? '📱' : '▣'} ${device.name} · ${device.id.slice(-6)}`
}

export function deviceChatAccent(id: string): string {
  const hue = [...id].reduce((value, char) => (value * 31 + char.charCodeAt(0)) % 360, 0)
  return `hsl(${hue} 48% 48%)`
}

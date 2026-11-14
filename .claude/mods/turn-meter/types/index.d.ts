export type TurnStats = {
  input: number
  cacheRead: number
  cacheWrite: number
  output: number
  seconds: number
  usd: number | null
  agents: number
  model: string
}

export type Totals = {
  input: number
  output: number
  seconds: number
  turns: number
}

declare module 'claude-code' {
  interface PluginState {
    'turn-meter': { last: TurnStats | null; totals: Totals; isHidden: boolean }
  }
}
